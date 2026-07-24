#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

fail() {
  printf 'PostgreSQL backup failed: %s\n' "$1" >&2
  exit 1
}

require_environment() {
  local name="$1"
  [[ -n "${!name:-}" ]] || fail "${name} must be supplied through the environment"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command is unavailable: $1"
}

require_positive_integer() {
  local name="$1"
  local value="$2"
  [[ "${value}" =~ ^[1-9][0-9]*$ ]] || fail "${name} must be a positive integer"
}

require_environment POSTGRES_HOST
require_environment POSTGRES_PORT
require_environment POSTGRES_DATABASE
require_environment POSTGRES_USER
require_environment BACKUP_OUTPUT_DIR

require_command date
require_command find
require_command pg_dump
require_command pg_restore
require_command sha256sum

BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-35}"
PGCONNECT_TIMEOUT="${PGCONNECT_TIMEOUT:-10}"
REQUIRE_BACKUP_ENCRYPTION="${REQUIRE_BACKUP_ENCRYPTION:-true}"
BACKUP_ENCRYPTION_PROGRAM="${BACKUP_ENCRYPTION_PROGRAM:-}"

require_positive_integer BACKUP_RETENTION_DAYS "${BACKUP_RETENTION_DAYS}"
require_positive_integer PGCONNECT_TIMEOUT "${PGCONNECT_TIMEOUT}"
[[ "${REQUIRE_BACKUP_ENCRYPTION}" == "true" || "${REQUIRE_BACKUP_ENCRYPTION}" == "false" ]] \
  || fail "REQUIRE_BACKUP_ENCRYPTION must be true or false"
[[ "${POSTGRES_DATABASE}" =~ ^[A-Za-z0-9_.-]+$ ]] \
  || fail "POSTGRES_DATABASE contains characters unsafe for a backup filename"
[[ "${BACKUP_OUTPUT_DIR}" == /* ]] \
  || fail "BACKUP_OUTPUT_DIR must be an absolute path"

if [[ "${REQUIRE_BACKUP_ENCRYPTION}" == "true" && -z "${BACKUP_ENCRYPTION_PROGRAM}" ]]; then
  fail "BACKUP_ENCRYPTION_PROGRAM is required when encryption is enforced"
fi
if [[ -n "${BACKUP_ENCRYPTION_PROGRAM}" && ! -x "${BACKUP_ENCRYPTION_PROGRAM}" ]]; then
  fail "BACKUP_ENCRYPTION_PROGRAM must reference an executable wrapper"
fi

mkdir -p -- "${BACKUP_OUTPUT_DIR}"
backup_directory="$(cd -- "${BACKUP_OUTPUT_DIR}" && pwd -P)"
[[ "${backup_directory}" != "/" ]] || fail "BACKUP_OUTPUT_DIR must not resolve to root"

export PGCONNECT_TIMEOUT
timestamp="$(date -u +'%Y%m%dT%H%M%SZ')"
backup_prefix="${POSTGRES_DATABASE}-${timestamp}"
plain_name="${backup_prefix}.dump"
plain_partial="${backup_directory}/.${plain_name}.partial"
final_name="${plain_name}"
final_path="${backup_directory}/${final_name}"

cleanup() {
  rm -f -- "${plain_partial}"
}
trap cleanup EXIT INT TERM

pg_dump \
  --host="${POSTGRES_HOST}" \
  --port="${POSTGRES_PORT}" \
  --username="${POSTGRES_USER}" \
  --dbname="${POSTGRES_DATABASE}" \
  --format=custom \
  --compress=9 \
  --no-owner \
  --no-acl \
  --file="${plain_partial}"

[[ -s "${plain_partial}" ]] || fail "pg_dump produced an empty archive"
pg_restore --list "${plain_partial}" >/dev/null

if [[ -n "${BACKUP_ENCRYPTION_PROGRAM}" ]]; then
  final_name="${plain_name}.enc"
  final_path="${backup_directory}/${final_name}"
  "${BACKUP_ENCRYPTION_PROGRAM}" "${plain_partial}" "${final_path}"
  [[ -s "${final_path}" ]] || fail "encryption wrapper produced an empty archive"
  rm -f -- "${plain_partial}"
else
  mv -- "${plain_partial}" "${final_path}"
fi

(
  cd -- "${backup_directory}"
  sha256sum -- "${final_name}" >"${final_name}.sha256"
)

# The local tier retains daily archives for the configured period. Promotion to
# monthly/yearly immutable tiers is owned by external object-storage lifecycle.
find "${backup_directory}" \
  -maxdepth 1 \
  -type f \
  -name "${POSTGRES_DATABASE}-*.dump*" \
  -mtime "+${BACKUP_RETENTION_DAYS}" \
  -delete

printf 'Backup created and checksummed: %s\n' "${final_path}"

