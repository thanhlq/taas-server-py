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

/* This is max options to test max performance of create user API. You can adjust the stages and thresholds as needed for your testing goals.
 */
export const options = {
  scenarios: {
    // Push as many requests as possible and measure real server capacity
    capacity: {
      executor: 'ramping-arrival-rate',
      startRate: 50,
      timeUnit: '1s',
      preAllocatedVUs: 200,
      maxVUs: 500,
      stages: [
        { duration: '30s', target: 200 },   // 200 req/s
        { duration: '1m',  target: 500 },    // push to 500 req/s
        { duration: '30s', target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<500'],
    http_req_failed: ['rate<0.01'],
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