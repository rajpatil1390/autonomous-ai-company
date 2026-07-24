#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

fail() {
  printf 'PostgreSQL restore refused or failed: %s\n' "$1" >&2
  exit 1
}

require_environment() {
  local name="$1"
  [[ -n "${!name:-}" ]] || fail "${name} must be supplied through the environment"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command is unavailable: $1"
}

require_environment POSTGRES_HOST
require_environment POSTGRES_PORT
require_environment POSTGRES_DATABASE
require_environment POSTGRES_USER
require_environment BACKUP_FILE
require_environment RESTORE_CONFIRM_DATABASE
require_environment RESTORE_WORK_DIR

[[ "${ALLOW_POSTGRES_RESTORE:-}" == "I_UNDERSTAND_THIS_REPLACES_DATABASE_CONTENTS" ]] \
  || fail "ALLOW_POSTGRES_RESTORE does not contain the required confirmation token"
[[ "${RESTORE_CONFIRM_DATABASE}" == "${POSTGRES_DATABASE}" ]] \
  || fail "RESTORE_CONFIRM_DATABASE does not match POSTGRES_DATABASE"
[[ "${RESTORE_WORK_DIR}" == /* ]] || fail "RESTORE_WORK_DIR must be an absolute path"
[[ -f "${BACKUP_FILE}" ]] || fail "BACKUP_FILE does not exist"

CHECKSUM_FILE="${CHECKSUM_FILE:-${BACKUP_FILE}.sha256}"
BACKUP_DECRYPTION_PROGRAM="${BACKUP_DECRYPTION_PROGRAM:-}"
PGCONNECT_TIMEOUT="${PGCONNECT_TIMEOUT:-10}"

require_command pg_restore
require_command sha256sum
[[ "${PGCONNECT_TIMEOUT}" =~ ^[1-9][0-9]*$ ]] \
  || fail "PGCONNECT_TIMEOUT must be a positive integer"
[[ -f "${CHECKSUM_FILE}" ]] || fail "CHECKSUM_FILE does not exist"
if [[ -n "${BACKUP_DECRYPTION_PROGRAM}" && ! -x "${BACKUP_DECRYPTION_PROGRAM}" ]]; then
  fail "BACKUP_DECRYPTION_PROGRAM must reference an executable wrapper"
fi

backup_directory="$(cd -- "$(dirname -- "${BACKUP_FILE}")" && pwd -P)"
backup_name="$(basename -- "${BACKUP_FILE}")"
checksum_directory="$(cd -- "$(dirname -- "${CHECKSUM_FILE}")" && pwd -P)"
checksum_name="$(basename -- "${CHECKSUM_FILE}")"
[[ "${checksum_directory}" == "${backup_directory}" ]] \
  || fail "checksum and backup must be in the same directory"

(
  cd -- "${backup_directory}"
  sha256sum --check --status "${checksum_name}"
) || fail "backup checksum verification failed"

mkdir -p -- "${RESTORE_WORK_DIR}"
restore_work_directory="$(cd -- "${RESTORE_WORK_DIR}" && pwd -P)"
[[ "${restore_work_directory}" != "/" ]] || fail "RESTORE_WORK_DIR must not resolve to root"
temporary_directory="$(mktemp -d "${restore_work_directory%/}/postgres-restore.XXXXXXXX")"

cleanup() {
  rm -rf -- "${temporary_directory}"
}
trap cleanup EXIT INT TERM

archive_path="${backup_directory}/${backup_name}"
if [[ -n "${BACKUP_DECRYPTION_PROGRAM}" ]]; then
  archive_path="${temporary_directory}/restore.dump"
  "${BACKUP_DECRYPTION_PROGRAM}" "${BACKUP_FILE}" "${archive_path}"
  [[ -s "${archive_path}" ]] || fail "decryption wrapper produced an empty archive"
fi

pg_restore --list "${archive_path}" >/dev/null
export PGCONNECT_TIMEOUT
pg_restore \
  --host="${POSTGRES_HOST}" \
  --port="${POSTGRES_PORT}" \
  --username="${POSTGRES_USER}" \
  --dbname="${POSTGRES_DATABASE}" \
  --clean \
  --if-exists \
  --no-owner \
  --no-acl \
  --exit-on-error \
  --single-transaction \
  "${archive_path}"

printf 'Restore completed for database: %s\n' "${POSTGRES_DATABASE}"

