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

export const options = {
  scenarios: {metrics: profile},
  thresholds: {
    [policy.thresholds.error_rate.metric]: [policy.thresholds.error_rate.limit],
    [policy.thresholds.successful_checks.metric]: [
      policy.thresholds.successful_checks.limit,
    ],
  },
};

export default function () {
  const response = http.get(`${baseUrl}/metrics`, {
    headers: {Accept: 'text/plain'},
    tags: {endpoint: 'metrics'},
  });
  check(response, {
    'metrics endpoint succeeds': (result) => result.status === 200,
    'prometheus content returned': (result) =>
      result.headers['Content-Type'].includes('text/plain'),
  });
  sleep(1);
}

export function handleSummary(data) {
  const path = __ENV.SUMMARY_PATH || 'metrics-summary.json';
  return {[path]: JSON.stringify(data, null, 2)};
}
