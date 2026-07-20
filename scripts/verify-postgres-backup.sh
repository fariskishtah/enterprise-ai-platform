#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  echo "Usage: $0 BACKUP_FILE" >&2
}

if (($# != 1)); then
  usage
  exit 2
fi

backup_argument=$1
if [[ ! -f "$backup_argument" ]]; then
  echo "Backup file does not exist: $backup_argument" >&2
  exit 2
fi

backup_directory="$(cd "$(dirname "$backup_argument")" && pwd -P)"
backup_file="$backup_directory/$(basename "$backup_argument")"
checksum_file="$backup_file.sha256"
container_id=""

cleanup() {
  local exit_code=$?
  if [[ -n "$container_id" ]]; then
    docker stop --time 5 "$container_id" >/dev/null 2>&1 || true
  fi
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

checksum_status="not provided"
if [[ -f "$checksum_file" ]]; then
  expected_checksum="$(awk 'NR == 1 {print $1}' "$checksum_file")"
  if [[ ${#expected_checksum} -ne 64 || "$expected_checksum" =~ [^0-9a-fA-F] ]]; then
    echo "Checksum file is not a valid SHA-256 record: $checksum_file" >&2
    exit 1
  fi
  actual_checksum="$(calculate_sha256 "$backup_file")"
  if [[ "$actual_checksum" != "$expected_checksum" ]]; then
    echo "Backup checksum verification failed." >&2
    exit 1
  fi
  checksum_status="verified"
fi

cd "$ROOT_DIR"
postgres_image="$({
  docker compose config | awk '
    $0 == "  postgres:" { in_postgres = 1; next }
    in_postgres && $0 ~ /^    image: / {
      sub(/^    image: /, "")
      print
      exit
    }
    in_postgres && $0 ~ /^  [^ ]/ { exit }
  '
})"
if [[ -z "$postgres_image" ]]; then
  echo "Could not resolve the PostgreSQL image from Docker Compose." >&2
  exit 1
fi

container_name="postgres-backup-verify-$$-$RANDOM"
container_id="$(docker run --detach --rm \
  --name "$container_name" \
  --env POSTGRES_DB=backup_verification \
  --env POSTGRES_USER=backup_verification \
  --env POSTGRES_PASSWORD=ephemeral-verification-only \
  "$postgres_image")"

ready=false
for _ in {1..30}; do
  if docker exec "$container_id" pg_isready \
    --username backup_verification \
    --dbname backup_verification >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 1
done
if [[ "$ready" != true ]]; then
  echo "Ephemeral PostgreSQL did not become ready for restore verification." >&2
  exit 1
fi

docker cp "$backup_file" "$container_id:/tmp/backup.dump" >/dev/null
docker exec "$container_id" pg_restore --list /tmp/backup.dump >/dev/null
docker exec "$container_id" pg_restore \
  --exit-on-error \
  --no-owner \
  --no-privileges \
  --username backup_verification \
  --dbname backup_verification \
  /tmp/backup.dump >/dev/null

schema_count="$(docker exec "$container_id" psql \
  --tuples-only --no-align \
  --username backup_verification \
  --dbname backup_verification \
  --command="SELECT count(*) FROM pg_namespace WHERE nspname NOT LIKE 'pg_%' AND nspname <> 'information_schema';")"
table_count="$(docker exec "$container_id" psql \
  --tuples-only --no-align \
  --username backup_verification \
  --dbname backup_verification \
  --command="SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog', 'information_schema');")"

if [[ ! "$schema_count" =~ ^[0-9]+$ || ! "$table_count" =~ ^[0-9]+$ ]]; then
  echo "Restored schema inspection returned an invalid result." >&2
  exit 1
fi
if ((schema_count < 1 || table_count < 1)); then
  echo "Restored archive did not contain an inspectable application schema and table." >&2
  exit 1
fi

printf 'PostgreSQL backup verification complete.\nArchive: %s\nChecksum: %s\nSchemas inspected: %s\nTables inspected: %s\n' \
  "$backup_file" "$checksum_status" "$schema_count" "$table_count"
