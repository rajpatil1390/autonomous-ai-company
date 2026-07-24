#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 3 ]]; then
  echo "Usage: $0 RELEASE NAMESPACE PREVIOUS_REVISION" >&2
  exit 64
fi

release="$1"
namespace="$2"
previous_revision="$3"

for command in helm kubectl; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command is unavailable: ${command}" >&2
    exit 69
  }
done

if [[ -z "${previous_revision}" ]]; then
  echo "No prior Helm revision exists; atomic install cleanup is authoritative."
  exit 0
fi

[[ "${previous_revision}" =~ ^[1-9][0-9]*$ ]] || {
  echo "Previous Helm revision must be a positive integer" >&2
  exit 64
}

helm rollback "${release}" "${previous_revision}" \
  --namespace "${namespace}" \
  --cleanup-on-fail \
  --wait \
  --timeout 15m

kubectl rollout status deployment/autonomous-ai-company-api \
  --namespace "${namespace}" \
  --timeout 5m

