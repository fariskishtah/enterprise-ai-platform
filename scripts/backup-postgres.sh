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
dataset_backup_name="dataset-${timestamp}.tar.gz"
dataset_backup_path="$BACKUP_DIR/$dataset_backup_name"
dataset_checksum_path="$dataset_backup_path.sha256"
temporary_backup=""
temporary_checksum=""
temporary_dataset_backup=""
temporary_dataset_checksum=""

cleanup() {
  local exit_code=$?
  [[ -z "$temporary_backup" ]] || rm -f -- "$temporary_backup"
  [[ -z "$temporary_checksum" ]] || rm -f -- "$temporary_checksum"
  [[ -z "$temporary_dataset_backup" ]] || rm -f -- "$temporary_dataset_backup"
  [[ -z "$temporary_dataset_checksum" ]] || rm -f -- "$temporary_dataset_checksum"
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

if [[ -e "$backup_path" || -e "$checksum_path" || \
      -e "$dataset_backup_path" || -e "$dataset_checksum_path" ]]; then
  echo "Refusing to overwrite an existing timestamped backup set: $backup_path" >&2
  exit 1
fi

# Capture PostgreSQL first. Dataset objects are immutable and are durably written
# before their metadata transaction commits, so the later object archive may
# contain harmless newer objects but cannot omit an object referenced by this
# database snapshot under the current non-destructive dataset lifecycle.
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

backend_container_id="$(docker compose ps -q backend)"
if [[ -z "$backend_container_id" ]]; then
  echo "Dataset backup failed because the backend container is not running." >&2
  exit 1
fi
dataset_volume="$(docker inspect --format \
  '{{range .Mounts}}{{if eq .Destination "/app/data/datasets"}}{{.Name}}{{end}}{{end}}' \
  "$backend_container_id")"
backend_image="$(docker inspect --format '{{.Config.Image}}' "$backend_container_id")"
if [[ -z "$dataset_volume" || -z "$backend_image" ]]; then
  echo "Dataset backup failed because its managed volume could not be resolved." >&2
  exit 1
fi

temporary_dataset_backup="$(mktemp "$BACKUP_DIR/.dataset-backup.XXXXXX.tmp")"
if ! docker run --rm \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --mount "type=volume,src=${dataset_volume},dst=/source,readonly" \
  --entrypoint python \
  "$backend_image" \
  -c 'import pathlib, sys, tarfile
root = pathlib.Path("/source")
with tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz", format=tarfile.PAX_FORMAT) as archive:
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise RuntimeError("The dataset volume contains an unsupported entry.")
        archive.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)' \
  >"$temporary_dataset_backup"; then
  echo "Dataset backup failed; no completed backup set was written." >&2
  exit 1
fi
if [[ ! -s "$temporary_dataset_backup" ]]; then
  echo "Dataset backup failed because the archive is empty." >&2
  exit 1
fi

checksum="$(calculate_sha256 "$temporary_backup")"
temporary_checksum="$(mktemp "$BACKUP_DIR/.postgres-checksum.XXXXXX.tmp")"
printf '%s  %s\n' "$checksum" "$backup_name" >"$temporary_checksum"
dataset_checksum="$(calculate_sha256 "$temporary_dataset_backup")"
temporary_dataset_checksum="$(mktemp "$BACKUP_DIR/.dataset-checksum.XXXXXX.tmp")"
printf '%s  %s\n' "$dataset_checksum" "$dataset_backup_name" \
  >"$temporary_dataset_checksum"

# Publish object artifacts first and the PostgreSQL checksum last. The checksum
# is the completion marker for a usable pair, so interruption cannot expose a
# checksummed database archive without its matching object archive.
mv -- "$temporary_dataset_backup" "$dataset_backup_path"
temporary_dataset_backup=""
mv -- "$temporary_dataset_checksum" "$dataset_checksum_path"
temporary_dataset_checksum=""
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
    \( -name 'postgres-*.dump' -o -name 'postgres-*.dump.sha256' \
       -o -name 'dataset-*.tar.gz' -o -name 'dataset-*.tar.gz.sha256' \) \
    -mtime "+$retention_mtime" -print0
)

backup_size="$(wc -c <"$backup_path" | tr -d '[:space:]')"
dataset_backup_size="$(wc -c <"$dataset_backup_path" | tr -d '[:space:]')"
printf 'Application backup set complete.\nPostgreSQL archive: %s\nPostgreSQL size: %s bytes\nPostgreSQL checksum: %s\nDataset archive: %s\nDataset size: %s bytes\nDataset checksum: %s\nExpired files removed: %s\n' \
  "$backup_path" "$backup_size" "$checksum_path" \
  "$dataset_backup_path" "$dataset_backup_size" "$dataset_checksum_path" \
  "$removed_files"
