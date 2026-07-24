#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

fail() {
  printf 'Backup verification failed: %s\n' "$1" >&2
  exit 1
}

require_environment() {
  local name="$1"
  [[ -n "${!name:-}" ]] || fail "${name} must be supplied through the environment"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command is unavailable: $1"
}

require_environment BACKUP_FILE
require_environment VERIFY_WORK_DIR

CHECKSUM_FILE="${CHECKSUM_FILE:-${BACKUP_FILE}.sha256}"
BACKUP_DECRYPTION_PROGRAM="${BACKUP_DECRYPTION_PROGRAM:-}"
REQUIRED_RELATIONS="${REQUIRED_RELATIONS:-audit_events}"

require_command pg_restore
require_command sha256sum
[[ "${VERIFY_WORK_DIR}" == /* ]] || fail "VERIFY_WORK_DIR must be an absolute path"
[[ -f "${BACKUP_FILE}" ]] || fail "BACKUP_FILE does not exist"
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

mkdir -p -- "${VERIFY_WORK_DIR}"
verify_work_directory="$(cd -- "${VERIFY_WORK_DIR}" && pwd -P)"
[[ "${verify_work_directory}" != "/" ]] || fail "VERIFY_WORK_DIR must not resolve to root"
temporary_directory="$(mktemp -d "${verify_work_directory%/}/postgres-verify.XXXXXXXX")"

cleanup() {
  rm -rf -- "${temporary_directory}"
}
trap cleanup EXIT INT TERM

archive_path="${backup_directory}/${backup_name}"
if [[ -n "${BACKUP_DECRYPTION_PROGRAM}" ]]; then
  archive_path="${temporary_directory}/verify.dump"
  "${BACKUP_DECRYPTION_PROGRAM}" "${BACKUP_FILE}" "${archive_path}"
  [[ -s "${archive_path}" ]] || fail "decryption wrapper produced an empty archive"
fi

catalog_path="${temporary_directory}/catalog.txt"
pg_restore --list "${archive_path}" >"${catalog_path}"
[[ -s "${catalog_path}" ]] || fail "archive catalog is empty"

IFS=',' read -r -a required_relations <<<"${REQUIRED_RELATIONS}"
for relation in "${required_relations[@]}"; do
  relation="${relation//[[:space:]]/}"
  [[ -n "${relation}" ]] || continue
  grep -F -- "${relation}" "${catalog_path}" >/dev/null \
    || fail "required relation is absent from archive: ${relation}"
done

printf 'Backup checksum and archive catalog verified: %s\n' "${BACKUP_FILE}"

