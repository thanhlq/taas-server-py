/*
  Signup stability SOAK test.

  Goal: prove the whole signup pipeline (api -> Keycloak -> outbox -> worker)
  stays healthy under a steady, sustainable load for a long time (1-2 hours).
  This is NOT a max-capacity test -- we hold a constant arrival rate and watch
  for error creep, latency drift and memory growth over the run.

  Executor: constant-vus (closed model). VUS virtual users each send signups
  back-to-back (no think time), so the offered load self-throttles to whatever
  the pipeline can actually complete -- exactly "constantly sending this signup
  request". VUS is therefore the *concurrency* knob.

  IMPORTANT concurrency finding (see README): a single signup is a multi-step
  Keycloak flow (create org -> set domain -> create user -> add member) that is
  NOT robust to being run in parallel with itself -- with VUS>=2 you will see a
  steady ~8-20% of 5xx ("Organization not found." / "Domain ... already linked")
  caused by Keycloak eventual-consistency races, independent of the email/org
  strategy below. VUS=1 (the default) is 100% clean and is the right setting for
  a leak / stability soak, where you want a clean steady signal. Raise VUS only
  when you specifically want to probe that concurrency behaviour.

  Email strategy (EMAIL_MODE):
    per-vu (default) : each VU uses ONE stable email (signup_test_vu<N>@domain).
                       The app's SIGNUP_TEST_MODE deletes the duplicate on each
                       repeat, so the DB stays bounded (<= number of VUs used)
                       over a multi-hour run, and no two in-flight requests ever
                       touch the same email (a VU runs its iterations serially),
                       so there are NO delete/create races.
    fixed            : every request uses the single SIGNUP_EMAIL. Matches the
                       original sample exactly. Only safe at very low concurrency
                       (RATE small enough that requests don't overlap).
    unique           : brand-new email every iteration. Exercises pure inserts
                       (no dedup path) but grows the DB unbounded over the run.

  All knobs are env vars -- see README.md. Example:
    VUS=1 DURATION=2h k6 run stress-signup.js
*/
import http from 'k6/http';
import exec from 'k6/execution';
import { check } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

const BASE_URL     = __ENV.BASE_URL     || 'http://localhost:8191';
const SIGNUP_PATH  = __ENV.SIGNUP_PATH  || '/api/v1/auth/signup';
const VUS          = Number(__ENV.VUS   || 1);        // concurrency (see header)
const DURATION     = __ENV.DURATION     || '2h';
const OTP          = __ENV.OTP          || '807689';
const EMAIL_MODE   = __ENV.EMAIL_MODE   || 'per-vu';  // per-vu | fixed | unique
const FIXED_EMAIL  = __ENV.SIGNUP_EMAIL || 'ngocle1401@gmail.com';
const EMAIL_DOMAIN = __ENV.EMAIL_DOMAIN || 'example.com';
const PASSWORD     = __ENV.PASSWORD     || 'Abcd@1234';
const REGION       = __ENV.REGION       || 'US';

// Custom metrics so the end-of-test summary calls out signup health explicitly.
const signupOk       = new Rate('signup_ok');          // fraction of HTTP 200
const signupDuration = new Trend('signup_duration', true);
const signupErrors   = new Counter('signup_errors');

export const options = {
  scenarios: {
    soak: {
      executor: 'constant-vus',
      vus: VUS,
      duration: DURATION,
    },
  },
  thresholds: {
    // Stability = almost no failures and no latency blow-up. These do NOT abort
    // the run (a soak should keep going); they just flip the run's pass/fail.
    // At VUS=1 these should stay green for the whole run; sustained red is the
    // signal that something degraded (leak, pool exhaustion, broker backlog).
    http_req_failed:   ['rate<0.01'],
    signup_ok:         ['rate>0.99'],
    http_req_duration: ['p(95)<8000'],
  },
};

// Per-run seed so 'unique' mode never collides with emails a previous run
// already inserted. (Date.now() is available in the k6 runtime.)
export function setup() {
  return { runId: `${Date.now()}` };
}

// Returns { email, org } for this iteration.
//
// CRITICAL org-name constraint: the app turns the org name into a Keycloak
// organization DOMAIN via generate_saas_subdomain(name, max_length=12) --
// lowercase, spaces->'-', invalid chars dropped, then TRUNCATED TO 12 CHARS.
// Two orgs whose names share the same first-12 sanitized chars collide on that
// domain ("Domain ... already linked"). Keycloak also rejects '@' in an org
// name. So org names here are kept short and unique within the first 12 chars,
// with the distinguishing id at the FRONT (not behind a long prefix).
function identityFor(runId) {
  if (EMAIL_MODE === 'fixed') {
    return { email: FIXED_EMAIL, org: 'org-fixed' };
  }
  if (EMAIL_MODE === 'unique') {
    // Unique per iteration across the whole test. base36 keeps it within the
    // 12-char domain budget (36^9 ids). NOTE: not seeded per run, so wipe
    // leftover 'u*' orgs (or run your dedup cleanup) before re-running.
    const uid = exec.scenario.iterationInTest.toString(36);
    return { email: `signup_${runId}_${__VU}_${__ITER}@${EMAIL_DOMAIN}`, org: `u${uid}` };
  }
  // per-vu (default): one stable identity per VU. "vu<N>-o" stays < 12 chars for
  // N up to ~1e6, and the number sits right after "vu" so vu1 / vu10 / vu11 map
  // to distinct domains (vu1-o, vu10-o, vu11-o). Dedup keeps the DB bounded to
  // the number of VU ids actually used.
  return { email: `signup_test_vu${__VU}@${EMAIL_DOMAIN}`, org: `vu${__VU}-o` };
}

export default function (data) {
  const { email, org } = identityFor(data.runId);

  const payload = JSON.stringify({
    otp: OTP,
    first_name: 'Soak',
    last_name: `VU${__VU}`,
    email,
    password: PASSWORD,
    organization_name: org,
    preferred_region: REGION,
  });

  const res = http.post(`${BASE_URL}${SIGNUP_PATH}`, payload, {
    headers: { 'Content-Type': 'application/json' },
    tags: { name: 'signup' },
  });

  const ok = res.status === 200;
  signupOk.add(ok);
  signupDuration.add(res.timings.duration);

  if (!ok) {
    signupErrors.add(1);
    // status=0 => no HTTP response arrived; the reason is in res.error, not body.
    console.error(
      `FAIL status=${res.status} err_code=${res.error_code} err="${res.error}" ` +
      `body=${String(res.body).slice(0, 300)}`,
    );
  }

  check(res, { 'status is 200': (r) => r.status === 200 });
}
