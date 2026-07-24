import http from 'k6/http';
import { check, sleep } from 'k6';

const policy = JSON.parse(open('./thresholds.json'));
const profileName = __ENV.LOAD_PROFILE || 'smoke';
const profile = policy.profiles[profileName];

if (!profile) {
  throw new Error(`Unknown LOAD_PROFILE: ${profileName}`);
}

function requiredEnvironment(name) {
  const value = __ENV[name];
  if (!value) {
    throw new Error(`${name} must be supplied through the environment`);
  }
  return value;
}

const baseUrl = requiredEnvironment('BASE_URL').replace(/\/$/, '');
const username = requiredEnvironment('PERF_USERNAME');
const password = requiredEnvironment('PERF_PASSWORD');

export const options = {
  scenarios: {login: profile},
  thresholds: {
    [policy.thresholds.login_p95.metric]: [policy.thresholds.login_p95.limit],
    [policy.thresholds.error_rate.metric]: [policy.thresholds.error_rate.limit],
    [policy.thresholds.successful_checks.metric]: [
      policy.thresholds.successful_checks.limit,
    ],
  },
};

export default function () {
  const response = http.post(
    `${baseUrl}/auth/login`,
    JSON.stringify({username, password}),
    {
      headers: {'Content-Type': 'application/json'},
      tags: {endpoint: 'login'},
    },
  );
  check(response, {
    'login succeeds': (result) => result.status === 200,
    'bearer token returned': (result) => result.json('token_type') === 'bearer',
    'access token returned': (result) => Boolean(result.json('access_token')),
  });
  sleep(1);
}

export function handleSummary(data) {
  const path = __ENV.SUMMARY_PATH || 'login-summary.json';
  return {[path]: JSON.stringify(data, null, 2)};
}
