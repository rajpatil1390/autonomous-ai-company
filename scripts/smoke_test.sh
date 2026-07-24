#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 BASE_URL" >&2
  exit 64
fi

base_url="${1%/}"
: "${SMOKE_USERNAME:?SMOKE_USERNAME must be supplied through a protected secret}"
: "${SMOKE_PASSWORD:?SMOKE_PASSWORD must be supplied through a protected secret}"

for command in curl jq grep; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command is unavailable: ${command}" >&2
    exit 69
  }
done

temporary_directory="$(mktemp -d)"
token=""
cleanup() {
  token=""
  rm -rf "${temporary_directory}"
}
trap cleanup EXIT

curl --fail --silent --show-error \
  --connect-timeout 10 --max-time 30 \
  "${base_url}/health" > "${temporary_directory}/health.json"
jq -e '.status == "ok"' "${temporary_directory}/health.json" >/dev/null

curl --fail --silent --show-error \
  --connect-timeout 10 --max-time 30 \
  "${base_url}/version" > "${temporary_directory}/version.json"
jq -e \
  '.application == "Autonomous AI Company" and .version == "1.0.0"' \
  "${temporary_directory}/version.json" >/dev/null

jq -n \
  --arg username "${SMOKE_USERNAME}" \
  --arg password "${SMOKE_PASSWORD}" \
  '{username: $username, password: $password}' \
  > "${temporary_directory}/login.json"
curl --fail --silent --show-error \
  --connect-timeout 10 --max-time 30 \
  --header "Content-Type: application/json" \
  --data-binary "@${temporary_directory}/login.json" \
  "${base_url}/auth/login" > "${temporary_directory}/token.json"
token="$(jq -er '.access_token | select(length > 0)' "${temporary_directory}/token.json")"

jq -n '{
  dataset: [
    {revenue: 100, cost: 60, customer_id: "smoke-customer", segment: "Smoke"},
    {revenue: 120, cost: 70, customer_id: "smoke-customer", segment: "Smoke"}
  ],
  previous_dataset: [
    {revenue: 80, cost: 50, customer_id: "smoke-customer", segment: "Smoke"}
  ],
  data_scientist_series: [10, 20, 30, 40],
  business_context: "Post-deployment production smoke test.",
  executive_question: "Confirm the workflow is operational."
}' > "${temporary_directory}/workflow.json"

curl --fail --silent --show-error \
  --connect-timeout 10 --max-time 180 \
  --header "Authorization: Bearer ${token}" \
  --header "Content-Type: application/json" \
  --data-binary "@${temporary_directory}/workflow.json" \
  "${base_url}/workflow/run" > "${temporary_directory}/workflow-response.json"
jq -e \
  '.executive_summary | type == "string" and length > 0' \
  "${temporary_directory}/workflow-response.json" >/dev/null
jq -e \
  '.business_health | IN("critical", "concerning", "stable", "strong")' \
  "${temporary_directory}/workflow-response.json" >/dev/null

curl --fail --silent --show-error \
  --connect-timeout 10 --max-time 30 \
  "${base_url}/metrics" > "${temporary_directory}/metrics.txt"
grep -q '^autonomous_ai_company_' "${temporary_directory}/metrics.txt"

curl --fail --silent --show-error --no-buffer \
  --connect-timeout 10 --max-time 180 \
  --header "Authorization: Bearer ${token}" \
  --header "Content-Type: application/json" \
  --data-binary "@${temporary_directory}/workflow.json" \
  "${base_url}/workflow/stream" > "${temporary_directory}/events.txt"
grep -q '^event: workflow_started$' "${temporary_directory}/events.txt"
grep -q '^event: workflow_completed$' "${temporary_directory}/events.txt"

echo "Production smoke tests passed."

