import http from 'k6/http';
import { check, sleep } from 'k6';

// export const options = {
//   vus: 1,
//   iterations: 1,   // run the function exactly once
// };

export const options = {
  stages: [
    { duration: '30s', target: 20 },  // ramp up to 20 virtual users
    { duration: '1m', target: 20 },  // hold at 20 for 1 min
    { duration: '30s', target: 0 },   // ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<500'],   // 95% of requests under 500ms
    http_req_failed: ['rate<0.01'],   // less than 1% failures
  },
};

let counter = 0;
export default function () {
  const url = 'http://localhost:8191/api/v1/users/';
  counter++
  const user = {
    "email": `thanhabc${counter}@gmail.com`,
    "password": "Thanh@210481",
    "name": `Thanh Le ${counter}`,
    "username": `thanhlq${counter}`,
    "phone": null,
    "isSuperuser": false,
    "isActive": true,
    "isVerified": false
  }

  // Unique payload per request so you don't hit duplicate-email errors
  const payload = JSON.stringify(user);

  const params = {
    headers: {
      'Content-Type': 'application/json',
      // 'Authorization': 'Bearer YOUR_TOKEN',  // if needed
    },
  };

  const res = http.post(url, payload, params);
  // Print the full response so you can eyeball it
  // console.log(`Status: ${res.status}`);
  // console.log(`Body: ${res.body}`);

  check(res, {
    'status is 200': (r) => r.status === 200,
    'has user id': (r) => r.json('id') !== undefined,
  });

  sleep(1);  // pause 1s between iterations per VU
}