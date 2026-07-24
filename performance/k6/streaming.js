import http from 'k6/http';
import { check, fail, sleep } from 'k6';

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
  scenarios: {sse_workflow: profile},
  thresholds: {
    [policy.thresholds.login_p95.metric]: [policy.thresholds.login_p95.limit],
    [policy.thresholds.error_rate.metric]: [policy.thresholds.error_rate.limit],
    [policy.thresholds.successful_checks.metric]: [
      policy.thresholds.successful_checks.limit,
    ],
  },
};

const workflowPayload = {
  dataset: [
    {revenue: 100, cost: 60, customer_id: 'stream-customer', segment: 'Enterprise'},
  ],
  previous_dataset: [
    {revenue: 80, cost: 50, customer_id: 'stream-customer', segment: 'Enterprise'},
  ],
  data_scientist_series: [10, 20, 30],
  business_context: 'SSE performance test workload.',
  executive_question: 'Which priority should be approved?',
};

function authenticate() {
  const response = http.post(
    `${baseUrl}/auth/login`,
    JSON.stringify({username, password}),
    {
      headers: {'Content-Type': 'application/json'},
      tags: {endpoint: 'login'},
    },
  );
  if (!check(response, {'stream login succeeds': (result) => result.status === 200})) {
    fail('Authentication failed');
  }
  return response.json('access_token');
}

export default function () {
  const token = authenticate();
  const response = http.post(
    `${baseUrl}/workflow/stream`,
    JSON.stringify(workflowPayload),
    {
      headers: {
        Accept: 'text/event-stream',
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      tags: {endpoint: 'streaming'},
      timeout: '45s',
    },
  );
  check(response, {
    'stream responds successfully': (result) => result.status === 200,
    'stream starts workflow': (result) => result.body.includes('event: workflow_started'),
    'stream reaches terminal event': (result) =>
      result.body.includes('event: workflow_completed') ||
      result.body.includes('event: workflow_failed'),
  });
  sleep(1);
}

export function handleSummary(data) {
  const path = __ENV.SUMMARY_PATH || 'streaming-summary.json';
  return {[path]: JSON.stringify(data, null, 2)};
}
