import http from 'k6/http';
import { check } from 'k6';

/*
  READ stress test -- LIST users (GET /api/v1/users/).

  Mirrors stress-test-create-user.js but exercises the read path. No setup() and
  no unique-data generation are needed: reads don't collide, so every VU/
  iteration hits the same URL.

  ramping-arrival-rate = open model: k6 injects N req/s regardless of server
  speed. When the server saturates you'll see http_req_failed climb, p(95)
  spike, and dropped_iterations appear (k6 ran out of VUs to fire requests).
  The last level it holds cleanly (errors <1%, dropped_iterations ~0) is your
  max read capacity.
*/
export const options = {
  scenarios: {
    capacity: {
      executor: 'ramping-arrival-rate',
      startRate: 100,
      timeUnit: '1s',
      // maxVUs >= target_rps * expected_latency_seconds, with headroom.
      preAllocatedVUs: 500,
      maxVUs: 3000,
      stages: [
        { duration: '30s', target: 200 },
        { duration: '1m',  target: 500 },   // hold 500/s
        { duration: '1m',  target: 1000 },  // hold 1000/s
        { duration: '1m',  target: 2000 },  // hold 2000/s
        { duration: '1m',  target: 3000 },  // hold 3000/s
        { duration: '1m',  target: 5000 },  // hold 5000/s
        { duration: '30s', target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_failed:   [{ threshold: 'rate<0.01', abortOnFail: false }],
    http_req_duration: [{ threshold: 'p(95)<2000', abortOnFail: false }],
  },
};

export default function () {
  const url = 'http://localhost:8191/api/v1/users/';

  const params = {
    headers: {
      'accept': 'application/json',
      // 'Authorization': 'Bearer YOUR_TOKEN',  // if needed
    },
  };

  const res = http.get(url, params);

  // status=0 means no HTTP response arrived (transport failure): the real
  // reason is in res.error / res.error_code, NOT the body (which is null).
  if (res.status < 200 || res.status >= 300) {
    console.error(
      `FAIL status=${res.status} error_code=${res.error_code} error="${res.error}" body=${res.body}`,
    );
  }

  check(res, {
    'status is 2xx': (r) => r.status >= 200 && r.status < 300,
    // OffsetPagination response shape: { items: [...], total, limit, offset }.
    'has items array': (r) => Array.isArray(r.json('items')),
  });
}
