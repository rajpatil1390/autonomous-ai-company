#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 6 ]]; then
  echo "Usage: $0 RELEASE NAMESPACE CHART VALUES IMAGE_REPOSITORY IMAGE_TAG" >&2
  exit 64
fi

release="$1"
namespace="$2"
chart="$3"
values="$4"
image_repository="$5"
image_tag="$6"

for command in helm kubectl jq; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command is unavailable: ${command}" >&2
    exit 69
  }
done

[[ -d "${chart}" ]] || { echo "Helm chart not found: ${chart}" >&2; exit 66; }
[[ -f "${values}" ]] || { echo "Values file not found: ${values}" >&2; exit 66; }
[[ -n "${image_repository}" ]] || { echo "Image repository is required" >&2; exit 64; }
[[ "${image_tag}" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+([._-][0-9A-Za-z.-]+)?$ ]] || {
  echo "Image tag must be an immutable semantic release tag" >&2
  exit 64
}

previous_revision=""
if history_json="$(helm history "${release}" --namespace "${namespace}" --output json 2>/dev/null)"; then
  previous_revision="$(
    jq -r '[.[] | select(.status == "deployed")] | last | .revision // empty' \
      <<<"${history_json}"
  )"
fi

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  echo "previous_revision=${previous_revision}" >> "${GITHUB_OUTPUT}"
fi

helm upgrade --install "${release}" "${chart}" \
  --namespace "${namespace}" \
  --create-namespace \
  --values "${values}" \
  --set-string "image.repository=${image_repository}" \
  --set-string "image.tag=${image_tag}" \
  --atomic \
  --cleanup-on-fail \
  --wait \
  --wait-for-jobs \
  --timeout 15m \
  --history-max 10

kubectl rollout status deployment/autonomous-ai-company-api \
  --namespace "${namespace}" \
  --timeout 5m

