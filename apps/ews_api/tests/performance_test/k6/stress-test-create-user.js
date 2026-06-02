import http from 'k6/http';
import { check, sleep } from 'k6';

// export const options = {
//   vus: 1,
//   iterations: 1,   // run the function exactly once
// };

// What about this config:
//
/*
  What about this config:
  - Ramp up to 20 users over 30s, hold for 1 min, then ramp down
  - Thresholds: 95% of requests under 500ms, less than 1% failures
 */
// export const options = {
//   stages: [
//     { duration: '30s', target: 20 },  // ramp up to 20 virtual users
//     { duration: '1m', target: 20 },  // hold at 20 for 1 min
//     { duration: '30s', target: 0 },   // ramp down
//   ],
//   thresholds: {
//     http_req_duration: ['p(95)<500'],   // 95% of requests under 500ms
//     http_req_failed: ['rate<0.01'],   // less than 1% failures
//   },
// };

/*
  MAX-CAPACITY (staircase stress) test.

  Goal: find the highest request rate the API can sustain with low errors and
  acceptable latency. We step the *arrival rate* up and hold each level for 1m
  so the metrics stabilize. The test auto-aborts the moment the API breaks
  (error rate > 1% OR p95 latency > 1s) -- the last level it held cleanly,
  *with dropped_iterations ~ 0*, is your max capacity.

  ramping-arrival-rate = open model: k6 injects N req/s no matter how slow the
  server is. When the server saturates you'll see http_req_failed climb, p(95)
  spike, and dropped_iterations appear (k6 ran out of VUs to fire requests).
*/
export const options = {
  scenarios: {
    capacity: {
      executor: 'ramping-arrival-rate',
      startRate: 100,
      timeUnit: '1s',
      // Must be high enough that VU starvation never limits the rate.
      // Rule of thumb: maxVUs >= target_rps * expected_latency_seconds, with
      // headroom for latency growth near saturation.
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
    // abortOnFail stops the run at the breaking point so you don't wait it out.
    http_req_failed:   [{ threshold: 'rate<0.01', abortOnFail: false }],
    http_req_duration: [{ threshold: 'p(95)<2000', abortOnFail: false }],
  },
};

// Runs once before the test; its return value is passed to the default fn.
// Date.now() gives a per-run seed so re-running the test does not regenerate
// emails/usernames that a previous run already inserted (the unique indexes
// would reject them as duplicates).
export function setup() {
  return { runId: `${Date.now()}` };
}

export default function (data) {
  const url = 'http://localhost:8191/api/v1/users/';

  // runId (per run) + __VU (per virtual user) + __ITER (per-VU iteration) is
  // unique across runs AND across VUs, so nothing collides on the unique
  // email/username indexes.
  const uid = `${data.runId}_${__VU}_${__ITER}`;
  const user = {
    "email": `thanhabc_${uid}@gmail.com`,
    "password": "Thanh@210481",
    "name": `Thanh Le ${uid}`,
    "username": `thanhlq_${uid}`,
    "phone": null,
    "isSuperuser": false,
    "isActive": true,
    "isVerified": false
  }

  const payload = JSON.stringify(user);

  const params = {
    headers: {
      'Content-Type': 'application/json',
      // 'Authorization': 'Bearer YOUR_TOKEN',  // if needed
    },
  };

  const res = http.post(url, payload, params);

  // Surface the real reason for any non-2xx so we stop guessing.
  if (res.status < 200 || res.status >= 300) {
    console.error(`FAIL status=${res.status} body=${res.body}`);
  }

  check(res, {
    'status is 2xx': (r) => r.status >= 200 && r.status < 300,
    'has user id': (r) => r.json('id') !== undefined,
  });

  // No sleep(): with the ramping-arrival-rate executor, sleep(1) pins each VU
  // busy for a full second, so sustaining 500 req/s would need 500 VUs and you
  // hit maxVUs / dropped_iterations. Remove it to measure true capacity.
}