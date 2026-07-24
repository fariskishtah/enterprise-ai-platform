#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

backup_target="${BACKUP_TARGET:-local}"
backup_dir="${BACKUP_DIR:-$repo_root/backups/application}"
retention_days="${BACKUP_RETENTION_DAYS:-14}"
encryption_passphrase="${BACKUP_ENCRYPTION_PASSPHRASE:-}"
s3_uri="${BACKUP_S3_URI:-}"
s3_endpoint="${BACKUP_S3_ENDPOINT_URL:-}"
s3_sse="${BACKUP_S3_SSE:-AES256}"
operation_id="pilot-$(date -u +%Y%m%dT%H%M%SZ)-$(openssl rand -hex 4)"
staging_dir="$(mktemp -d "${TMPDIR:-/tmp}/ai-platform-backup.XXXXXX")"
payload_dir="$staging_dir/payload"
plain_archive="$staging_dir/${operation_id}.tar.gz"
encrypted_archive="$staging_dir/${operation_id}.tar.gz.enc"
hmac_file="$encrypted_archive.hmac"
published=false
compose_arguments=()
if [[ -n "${BACKUP_COMPOSE_PROJECT_NAME:-}" ]]; then
  compose_arguments+=(--project-name "$BACKUP_COMPOSE_PROJECT_NAME")
fi
if [[ -n "${BACKUP_COMPOSE_ENV_FILE:-}" ]]; then
  compose_arguments+=(--env-file "$BACKUP_COMPOSE_ENV_FILE")
fi
if [[ -n "${BACKUP_COMPOSE_FILES:-}" ]]; then
  IFS=: read -r -a compose_files <<<"$BACKUP_COMPOSE_FILES"
  for compose_file in "${compose_files[@]}"; do
    compose_arguments+=(-f "$compose_file")
  done
fi

compose() {
  docker compose "${compose_arguments[@]}" "$@"
}

audit_result() {
  local result=$1
  set +e
  compose exec -T backend \
    python -m app.cli.audit_operation backup.executed "$result" "$operation_id" \
    >/dev/null 2>&1
  set -e
  return 0
}

cleanup() {
  local exit_code=$?
  trap - EXIT
  if ((exit_code != 0)) && [[ "$published" != true ]]; then
    audit_result failure
  fi
  rm -rf -- "$staging_dir"
  exit "$exit_code"
}
trap cleanup EXIT

if [[ "$backup_target" != "local" && "$backup_target" != "s3" ]]; then
  echo "BACKUP_TARGET must be local or s3." >&2
  exit 2
fi
if [[ -z "$encryption_passphrase" ]]; then
  echo "BACKUP_ENCRYPTION_PASSPHRASE is required." >&2
  exit 2
fi
if [[ ! "$retention_days" =~ ^[1-9][0-9]*$ ]]; then
  echo "BACKUP_RETENTION_DAYS must be a positive integer." >&2
  exit 2
fi
if [[ "$backup_target" == "s3" && -z "$s3_uri" ]]; then
  echo "BACKUP_S3_URI is required for the S3 target." >&2
  exit 2
fi
if [[ -n "$s3_endpoint" && "$s3_endpoint" != https://* ]]; then
  echo "BACKUP_S3_ENDPOINT_URL must use HTTPS." >&2
  exit 2
fi
for command_name in docker openssl python3; do
  command -v "$command_name" >/dev/null || {
    echo "$command_name is required." >&2
    exit 2
  }
done
if [[ "$backup_target" == "s3" ]]; then
  command -v aws >/dev/null || {
    echo "The AWS CLI is required for the S3-compatible target." >&2
    exit 2
  }
fi

mkdir -p -- "$payload_dir"
backend_container="$(compose ps -q backend)"
if [[ -z "$backend_container" ]]; then
  echo "The backend container must be running." >&2
  exit 1
fi
backend_image="$(docker inspect --format '{{.Config.Image}}' "$backend_container")"

compose exec -T postgres sh -ceu \
  'exec pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --format=custom --no-owner --no-privileges' \
  >"$payload_dir/postgres.dump"
[[ -s "$payload_dir/postgres.dump" ]] || {
  echo "PostgreSQL produced an empty archive." >&2
  exit 1
}

archive_volume() {
  local destination=$1
  local output_name=$2
  local volume_name
  volume_name="$(docker inspect --format \
    "{{range .Mounts}}{{if eq .Destination \"$destination\"}}{{.Name}}{{end}}{{end}}" \
    "$backend_container")"
  [[ -n "$volume_name" ]] || {
    echo "Could not resolve the managed volume for $destination." >&2
    return 1
  }
  docker run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true \
    --mount "type=volume,src=${volume_name},dst=/source,readonly" \
    --entrypoint python "$backend_image" \
    -c 'import pathlib,sys,tarfile
root=pathlib.Path("/source")
with tarfile.open(fileobj=sys.stdout.buffer,mode="w|gz",format=tarfile.PAX_FORMAT) as out:
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise RuntimeError("unsupported volume entry")
        out.add(path,arcname=path.relative_to(root).as_posix(),recursive=False)' \
    >"$payload_dir/$output_name"
}

archive_volume /app/data/datasets datasets.tar.gz
archive_volume /app/data/model-artifacts model-artifacts.tar.gz
archive_volume /app/data/ai-artifacts ai-artifacts.tar.gz
archive_volume /app/data/mlflow mlflow.tar.gz

application_version="$(awk -F'\"' '/^version = / {print $2; exit}' backend/pyproject.toml)"
git_commit="$(git rev-parse HEAD)"
migration_revision="$(compose exec -T backend alembic current 2>/dev/null |
  awk 'NF {value=$1} END {print value}')"
cat >"$payload_dir/manifest.env" <<EOF
BACKUP_ID=$operation_id
CREATED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
APPLICATION_VERSION=$application_version
GIT_COMMIT=$git_commit
DATABASE_MIGRATION_REVISION=$migration_revision
RETENTION_DAYS=$retention_days
ENCRYPTION=aes-256-cbc-pbkdf2
CONTENTS=postgres,datasets,model-artifacts,ai-artifacts,mlflow
EOF
(
  cd "$payload_dir"
  shasum -a 256 postgres.dump datasets.tar.gz model-artifacts.tar.gz \
    ai-artifacts.tar.gz mlflow.tar.gz manifest.env >checksums.sha256
)
tar -C "$staging_dir" -czf "$plain_archive" payload
openssl enc -aes-256-cbc -salt -pbkdf2 -iter 200000 \
  -in "$plain_archive" -out "$encrypted_archive" \
  -pass env:BACKUP_ENCRYPTION_PASSPHRASE
python3 -c 'import hashlib,hmac,os,pathlib,sys
path=pathlib.Path(sys.argv[1])
key=hashlib.sha256(os.environ["BACKUP_ENCRYPTION_PASSPHRASE"].encode()).digest()
pathlib.Path(sys.argv[2]).write_text(hmac.new(key,path.read_bytes(),hashlib.sha256).hexdigest()+"\n")' \
  "$encrypted_archive" "$hmac_file"

if [[ "$backup_target" == "local" ]]; then
  mkdir -p -- "$backup_dir"
  destination="$backup_dir/$(basename "$encrypted_archive")"
  [[ ! -e "$destination" ]] || {
    echo "Refusing to overwrite $destination." >&2
    exit 1
  }
  mv -- "$encrypted_archive" "$destination"
  mv -- "$hmac_file" "$destination.hmac"
  find "$backup_dir" -maxdepth 1 -type f -name 'pilot-*.tar.gz.enc' \
    -mtime "+$((retention_days - 1))" -delete
  find "$backup_dir" -maxdepth 1 -type f -name 'pilot-*.tar.gz.enc.hmac' \
    -mtime "+$((retention_days - 1))" -delete
else
  destination="${s3_uri%/}/$(basename "$encrypted_archive")"
  aws_arguments=(s3 cp "$encrypted_archive" "$destination" --only-show-errors)
  [[ -z "$s3_endpoint" ]] || aws_arguments+=(--endpoint-url "$s3_endpoint")
  if [[ "$s3_sse" == "aws:kms" ]]; then
    [[ -n "${BACKUP_S3_KMS_KEY_ID:-}" ]] || {
      echo "BACKUP_S3_KMS_KEY_ID is required for aws:kms." >&2
      exit 2
    }
    aws_arguments+=(--sse aws:kms --sse-kms-key-id "$BACKUP_S3_KMS_KEY_ID")
  else
    aws_arguments+=(--sse AES256)
  fi
  aws "${aws_arguments[@]}"
  hmac_destination="$destination.hmac"
  hmac_arguments=(s3 cp "$hmac_file" "$hmac_destination" --only-show-errors)
  [[ -z "$s3_endpoint" ]] || hmac_arguments+=(--endpoint-url "$s3_endpoint")
  if [[ "$s3_sse" == "aws:kms" ]]; then
    hmac_arguments+=(--sse aws:kms --sse-kms-key-id "$BACKUP_S3_KMS_KEY_ID")
  else
    hmac_arguments+=(--sse AES256)
  fi
  aws "${hmac_arguments[@]}"
fi

published=true
audit_result success
printf 'Encrypted application backup complete.\nBackup ID: %s\nDestination: %s\n' \
  "$operation_id" "$destination"
