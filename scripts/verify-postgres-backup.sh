#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  echo "Usage: $0 POSTGRES_BACKUP [DATASET_ARCHIVE]" >&2
}

if (($# < 1 || $# > 2)); then
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
dataset_archive=""
if (($# == 2)); then
  dataset_argument=$2
  if [[ ! -f "$dataset_argument" ]]; then
    echo "Dataset archive does not exist: $dataset_argument" >&2
    exit 2
  fi
  dataset_directory="$(cd "$(dirname "$dataset_argument")" && pwd -P)"
  dataset_archive="$dataset_directory/$(basename "$dataset_argument")"
elif [[ "$(basename "$backup_file")" == postgres-*.dump ]]; then
  backup_suffix="$(basename "$backup_file")"
  backup_suffix="${backup_suffix#postgres-}"
  backup_suffix="${backup_suffix%.dump}"
  inferred_dataset_archive="$backup_directory/dataset-${backup_suffix}.tar.gz"
  if [[ -f "$inferred_dataset_archive" ]]; then
    dataset_archive="$inferred_dataset_archive"
  fi
fi
dataset_checksum_file="${dataset_archive:+${dataset_archive}.sha256}"
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
if [[ -n "$dataset_archive" && "$checksum_status" != "verified" ]]; then
  echo "A paired PostgreSQL backup checksum is required: $checksum_file" >&2
  exit 1
fi

dataset_checksum_status="not provided"
if [[ -n "$dataset_archive" ]]; then
  if [[ ! -f "$dataset_checksum_file" ]]; then
    echo "Dataset archive checksum is required: $dataset_checksum_file" >&2
    exit 1
  fi
  expected_dataset_checksum="$(awk 'NR == 1 {print $1}' "$dataset_checksum_file")"
  if [[ ${#expected_dataset_checksum} -ne 64 || \
        "$expected_dataset_checksum" =~ [^0-9a-fA-F] ]]; then
    echo "Dataset checksum file is not a valid SHA-256 record." >&2
    exit 1
  fi
  actual_dataset_checksum="$(calculate_sha256 "$dataset_archive")"
  if [[ "$actual_dataset_checksum" != "$expected_dataset_checksum" ]]; then
    echo "Dataset archive checksum verification failed." >&2
    exit 1
  fi
  dataset_checksum_status="verified"
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

if [[ -n "$dataset_archive" ]]; then
  docker cp "$dataset_archive" "$container_id:/tmp/dataset.tar.gz" >/dev/null
  dataset_listing="$(docker exec "$container_id" tar -tzf /tmp/dataset.tar.gz)" || {
    echo "Dataset archive validation failed." >&2
    exit 1
  }
  while IFS= read -r member; do
    [[ -z "$member" ]] && continue
    case "$member" in
      /*|..|../*|*/../*|*/..)
        echo "Dataset archive contains an unsafe path." >&2
        exit 1
        ;;
    esac
  done <<<"$dataset_listing"
  docker exec "$container_id" sh -ceu \
    'tar -tvzf /tmp/dataset.tar.gz | awk '\''{
       kind = substr($1, 1, 1)
       if (kind != "-" && kind != "d") exit 1
     }'\'''
fi

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
vector_extension_count="$(docker exec "$container_id" psql \
  --tuples-only --no-align \
  --username backup_verification \
  --dbname backup_verification \
  --command="SELECT count(*) FROM pg_extension WHERE extname = 'vector';")"

if [[ ! "$schema_count" =~ ^[0-9]+$ || ! "$table_count" =~ ^[0-9]+$ || \
      ! "$vector_extension_count" =~ ^[0-9]+$ ]]; then
  echo "Restored schema inspection returned an invalid result." >&2
  exit 1
fi
if ((schema_count < 1 || table_count < 1)); then
  echo "Restored archive did not contain an inspectable application schema and table." >&2
  exit 1
fi
if [[ -n "$dataset_archive" && "$vector_extension_count" != "1" ]]; then
  echo "Restored archive does not contain the required vector extension." >&2
  exit 1
fi

printf 'Application backup verification complete.\nPostgreSQL archive: %s\nPostgreSQL checksum: %s\nDataset archive: %s\nDataset checksum: %s\nVector extension count: %s\nSchemas inspected: %s\nTables inspected: %s\n' \
  "$backup_file" "$checksum_status" "${dataset_archive:-not provided}" \
  "$dataset_checksum_status" "$vector_extension_count" "$schema_count" "$table_count"
