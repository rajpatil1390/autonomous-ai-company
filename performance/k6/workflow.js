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

function threshold(names) {
  return Object.fromEntries(
    names.map((name) => {
      const rule = policy.thresholds[name];
      return [rule.metric, [rule.limit]];
    }),
  );
}

const baseUrl = requiredEnvironment('BASE_URL').replace(/\/$/, '');
const username = requiredEnvironment('PERF_USERNAME');
const password = requiredEnvironment('PERF_PASSWORD');

export const options = {
  scenarios: {
    authenticated_workflow: profile,
  },
  thresholds: threshold([
    'health_p95',
    'login_p95',
    'workflow_p95',
    'error_rate',
    'successful_checks',
  ]),
};

const workflowPayload = {
  dataset: [
    {revenue: 100, cost: 60, customer_id: 'load-customer', segment: 'Enterprise'},
  ],
  previous_dataset: [
    {revenue: 80, cost: 50, customer_id: 'load-customer', segment: 'Enterprise'},
  ],
  data_scientist_series: [10, 20, 30],
  business_context: 'Controlled performance test workload.',
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
  const valid = check(response, {
    'login succeeds': (result) => result.status === 200,
    'login returns token': (result) => Boolean(result.json('access_token')),
  });
  if (!valid) {
    fail('Authentication failed');
  }
  return response.json('access_token');
}

export default function () {
  const health = http.get(`${baseUrl}/health`, {tags: {endpoint: 'health'}});
  check(health, {'health is ready': (response) => response.status === 200});

  const token = authenticate();
  const response = http.post(
    `${baseUrl}/workflow/run`,
    JSON.stringify(workflowPayload),
    {
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      tags: {endpoint: 'workflow'},
      timeout: '30s',
    },
  );
  check(response, {
    'workflow succeeds': (result) => result.status === 200,
    'workflow returns recommendation': (result) =>
      Boolean(result.json('final_recommendation')),
  });
  sleep(1);
}

export function handleSummary(data) {
  const path = __ENV.SUMMARY_PATH || 'workflow-summary.json';
  return {[path]: JSON.stringify(data, null, 2)};
}
