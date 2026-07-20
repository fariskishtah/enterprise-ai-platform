#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups/postgres}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"

if [[ ! "$RETENTION_DAYS" =~ ^[0-9]+$ ]] || ((RETENTION_DAYS < 1)); then
  echo "RETENTION_DAYS must be a positive integer." >&2
  exit 2
fi

if [[ -e "$BACKUP_DIR" && ! -d "$BACKUP_DIR" ]]; then
  echo "Backup path exists but is not a directory: $BACKUP_DIR" >&2
  exit 2
fi

mkdir -p -- "$BACKUP_DIR"
BACKUP_DIR="$(cd "$BACKUP_DIR" && pwd -P)"
cd "$ROOT_DIR"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_name="postgres-${timestamp}.dump"
backup_path="$BACKUP_DIR/$backup_name"
checksum_path="$backup_path.sha256"
temporary_backup=""
temporary_checksum=""

cleanup() {
  local exit_code=$?
  [[ -z "$temporary_backup" ]] || rm -f -- "$temporary_backup"
  [[ -z "$temporary_checksum" ]] || rm -f -- "$temporary_checksum"
  exit "$exit_code"
}
trap cleanup EXIT

calculate_sha256() {
  local path=$1

  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$path" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$path" | awk '{print $1}'
  else
    echo "A SHA-256 utility (sha256sum or shasum) is required." >&2
    return 1
  fi
}

if [[ -e "$backup_path" || -e "$checksum_path" ]]; then
  echo "Refusing to overwrite an existing timestamped backup: $backup_path" >&2
  exit 1
fi

temporary_backup="$(mktemp "$BACKUP_DIR/.postgres-backup.XXXXXX.tmp")"
if ! docker compose exec -T postgres sh -ceu \
  'exec pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --format=custom --no-owner --no-privileges' \
  >"$temporary_backup"; then
  echo "PostgreSQL backup failed; no completed archive was written." >&2
  exit 1
fi

if [[ ! -s "$temporary_backup" ]]; then
  echo "PostgreSQL backup failed because pg_dump produced an empty archive." >&2
  exit 1
fi

checksum="$(calculate_sha256 "$temporary_backup")"
temporary_checksum="$(mktemp "$BACKUP_DIR/.postgres-checksum.XXXXXX.tmp")"
printf '%s  %s\n' "$checksum" "$backup_name" >"$temporary_checksum"

mv -- "$temporary_backup" "$backup_path"
temporary_backup=""
mv -- "$temporary_checksum" "$checksum_path"
temporary_checksum=""

removed_files=0
retention_mtime=$((RETENTION_DAYS - 1))
while IFS= read -r -d '' expired_file; do
  rm -f -- "$expired_file"
  ((removed_files += 1))
done < <(
  find "$BACKUP_DIR" -maxdepth 1 -type f \
    \( -name 'postgres-*.dump' -o -name 'postgres-*.dump.sha256' \) \
    -mtime "+$retention_mtime" -print0
)

backup_size="$(wc -c <"$backup_path" | tr -d '[:space:]')"
printf 'PostgreSQL backup complete.\nArchive: %s\nSize: %s bytes\nChecksum: %s\nExpired files removed: %s\n' \
  "$backup_path" "$backup_size" "$checksum_path" "$removed_files"
