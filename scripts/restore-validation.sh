#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if (($# != 1)); then
  echo "Usage: $0 ENCRYPTED_BACKUP" >&2
  exit 2
fi
encrypted_backup="$(cd "$(dirname "$1")" && pwd -P)/$(basename "$1")"
[[ -f "$encrypted_backup" ]] || {
  echo "Encrypted backup not found." >&2
  exit 2
}
hmac_file="$encrypted_backup.hmac"
[[ -f "$hmac_file" ]] || {
  echo "Authenticated backup checksum not found." >&2
  exit 2
}
[[ -n "${BACKUP_ENCRYPTION_PASSPHRASE:-}" ]] || {
  echo "BACKUP_ENCRYPTION_PASSPHRASE is required." >&2
  exit 2
}

validation_id="restore-$(date -u +%Y%m%dT%H%M%SZ)-$(openssl rand -hex 4)"
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/ai-platform-restore.XXXXXX")"
network_name="ai-restore-$RANDOM-$$"
postgres_name="${network_name}-postgres"
redis_name="${network_name}-redis"
backend_name="${network_name}-backend"
evidence_dir="${RESTORE_EVIDENCE_DIR:-$repo_root/artifacts}"
evidence_file="$evidence_dir/${validation_id}.txt"
volumes=()
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
    python -m app.cli.audit_operation restore.validation_executed "$result" "$validation_id" \
    >/dev/null 2>&1
  set -e
  return 0
}

cleanup() {
  local exit_code=$?
  trap - EXIT
  if ((exit_code != 0)); then
    audit_result failure
  fi
  docker rm -f "$backend_name" "$redis_name" "$postgres_name" >/dev/null 2>&1 || true
  docker network rm "$network_name" >/dev/null 2>&1 || true
  for volume in "${volumes[@]-}"; do
    [[ -z "$volume" ]] || docker volume rm "$volume" >/dev/null 2>&1 || true
  done
  rm -rf -- "$work_dir"
  exit "$exit_code"
}
trap cleanup EXIT

python3 -c 'import hashlib,hmac,os,pathlib,sys
archive=pathlib.Path(sys.argv[1]).read_bytes()
expected=pathlib.Path(sys.argv[2]).read_text().strip()
key=hashlib.sha256(os.environ["BACKUP_ENCRYPTION_PASSPHRASE"].encode()).digest()
actual=hmac.new(key,archive,hashlib.sha256).hexdigest()
assert hmac.compare_digest(actual,expected), "backup authentication failed"' \
  "$encrypted_backup" "$hmac_file"
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
  -in "$encrypted_backup" -out "$work_dir/backup.tar.gz" \
  -pass env:BACKUP_ENCRYPTION_PASSPHRASE
tar -tzf "$work_dir/backup.tar.gz" |
  awk 'substr($0,1,1)=="/" || $0==".." || index($0,"../")==1 ||
       index($0,"/../")>0 || substr($0,length($0)-2)=="/.." {bad=1}
       END {exit bad}'
tar -xzf "$work_dir/backup.tar.gz" -C "$work_dir"
payload_dir="$work_dir/payload"
[[ -f "$payload_dir/checksums.sha256" && -f "$payload_dir/manifest.env" ]] || {
  echo "The backup manifest is incomplete." >&2
  exit 1
}
(
  cd "$payload_dir"
  shasum -a 256 -c checksums.sha256
)

BACKUP_ID="$(awk -F= '$1=="BACKUP_ID" {print substr($0,index($0,"=")+1)}' \
  "$payload_dir/manifest.env")"
DATABASE_MIGRATION_REVISION="$(awk -F= \
  '$1=="DATABASE_MIGRATION_REVISION" {print substr($0,index($0,"=")+1)}' \
  "$payload_dir/manifest.env")"
[[ -n "${BACKUP_ID:-}" && -n "${DATABASE_MIGRATION_REVISION:-}" ]] || {
  echo "The backup manifest is invalid." >&2
  exit 1
}
[[ "$BACKUP_ID" =~ ^[A-Za-z0-9._-]+$ ]] || {
  echo "The backup ID is invalid." >&2
  exit 1
}
[[ "$DATABASE_MIGRATION_REVISION" =~ ^[A-Za-z0-9_]+$ ]] || {
  echo "The migration revision is invalid." >&2
  exit 1
}

postgres_image="$(compose config |
  awk '$0 == "  postgres:" {found=1; next} found && /image:/ {print $2; exit}')"
redis_image="$(compose config |
  awk '$0 == "  redis:" {found=1; next} found && /image:/ {print $2; exit}')"
backend_container="$(compose ps -q backend)"
[[ -n "$backend_container" ]] || {
  echo "The source backend container must be running." >&2
  exit 1
}
backend_image="$(docker inspect --format '{{.Config.Image}}' "$backend_container")"
docker network create "$network_name" >/dev/null
docker run -d --rm --name "$postgres_name" --network "$network_name" \
  -e POSTGRES_DB=restore_validation \
  -e POSTGRES_USER=restore_validation \
  -e POSTGRES_PASSWORD=restore-validation-only \
  "$postgres_image" >/dev/null
for _ in {1..60}; do
  docker exec "$postgres_name" pg_isready -U restore_validation \
    -d restore_validation >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$postgres_name" pg_isready -U restore_validation \
  -d restore_validation >/dev/null
docker run -d --rm --name "$redis_name" --network "$network_name" \
  "$redis_image" >/dev/null
for _ in {1..60}; do
  docker exec "$redis_name" redis-cli ping 2>/dev/null | grep -q PONG && break
  sleep 1
done
docker exec "$redis_name" redis-cli ping 2>/dev/null | grep -q PONG
docker cp "$payload_dir/postgres.dump" "$postgres_name:/tmp/postgres.dump"
docker exec "$postgres_name" pg_restore --exit-on-error --no-owner --no-privileges \
  -U restore_validation -d restore_validation /tmp/postgres.dump >/dev/null

restored_revision="$(docker exec "$postgres_name" psql -At \
  -U restore_validation -d restore_validation \
  -c 'SELECT version_num FROM alembic_version')"
[[ "$restored_revision" == "$DATABASE_MIGRATION_REVISION" ]] || {
  echo "Migration revision mismatch after restore." >&2
  exit 1
}
core_counts="$(docker exec "$postgres_name" psql -At \
  -U restore_validation -d restore_validation \
  -c "SELECT 'companies='||count(*) FROM companies
      UNION ALL SELECT 'users='||count(*) FROM users
      UNION ALL SELECT 'factories='||count(*) FROM factories
      UNION ALL SELECT 'datasets='||count(*) FROM datasets
      UNION ALL SELECT 'training_jobs='||count(*) FROM training_jobs")"

for archive in datasets model-artifacts ai-artifacts mlflow; do
  tar -tzf "$payload_dir/$archive.tar.gz" |
    awk 'substr($0,1,1)=="/" || $0==".." || index($0,"../")==1 ||
         index($0,"/../")>0 || substr($0,length($0)-2)=="/.." {exit 1}'
  volume="${network_name}-${archive}"
  docker volume create "$volume" >/dev/null
  volumes+=("$volume")
  docker run --rm --network none --user 0:0 --cap-drop ALL --cap-add CHOWN \
    --security-opt no-new-privileges:true \
    --mount "type=volume,src=$volume,dst=/target" \
    -v "$payload_dir/$archive.tar.gz:/archive.tar.gz:ro" \
    --entrypoint sh "$backend_image" -ceu \
    'tar --no-same-owner -xzf /archive.tar.gz -C /target
     chown -R 10001:10001 /target'
done

validation_password="RestoreValidation-$(openssl rand -hex 12)!"
database_url="postgresql+psycopg://restore_validation:restore-validation-only@${postgres_name}:5432/restore_validation"
docker run --rm --network "$network_name" \
  -e DATABASE_URL="$database_url" \
  -e SECRET_KEY=restore-validation-secret-key-with-sufficient-entropy \
  -e VALIDATION_PASSWORD="$validation_password" \
  "$backend_image" python -c 'import asyncio,os
from app.db.session import build_session_factory
from app.repositories.users import UserRepository
from app.services.users import UserService
from app.utils.passwords import PasswordHasher
from app.models.user import UserRole
async def run():
    factory=build_session_factory(os.environ["DATABASE_URL"])
    async with factory() as session:
        service=UserService(repository=UserRepository(session),password_hasher=PasswordHasher())
        await service.create_user(email="restore-validation@example.com",password=os.environ["VALIDATION_PASSWORD"],role=UserRole.ADMIN)
asyncio.run(run())'

docker run -d --rm --name "$backend_name" --network "$network_name" \
  -e DATABASE_URL="$database_url" \
  -e REDIS_URL="redis://${redis_name}:6379/0" \
  -e SECRET_KEY=restore-validation-secret-key-with-sufficient-entropy \
  -e ENVIRONMENT=test \
  -e TRACING_ENABLED=false \
  -e AUTH_RATE_LIMIT_ENABLED=false \
  -e WORKER_AVAILABILITY_CHECK_ENABLED=false \
  -e MLFLOW_TRACKING_URI=file:/app/data/mlflow \
  -e MODEL_ARTIFACT_ROOT=/app/data/model-artifacts \
  -e AI_ARTIFACT_ROOT=/app/data/ai-artifacts \
  -e DATASET_STORAGE_ROOT=/app/data/datasets \
  --mount "type=volume,src=${volumes[0]},dst=/app/data/datasets" \
  --mount "type=volume,src=${volumes[1]},dst=/app/data/model-artifacts" \
  --mount "type=volume,src=${volumes[2]},dst=/app/data/ai-artifacts" \
  --mount "type=volume,src=${volumes[3]},dst=/app/data/mlflow" \
  "$backend_image" >/dev/null
ready=false
for _ in {1..60}; do
  if docker run --rm --network "$network_name" "$backend_image" python -c \
    "import urllib.request; urllib.request.urlopen('http://${backend_name}:8000/ready',timeout=2)" \
    >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 1
done
[[ "$ready" == true ]] || {
  echo "The disposable restored backend did not become ready." >&2
  exit 1
}
docker run --rm --network "$network_name" \
  -e VALIDATION_PASSWORD="$validation_password" "$backend_image" python -c \
  'import json,os,urllib.request
base="http://'"$backend_name"':8000"
body=json.dumps({"email":"restore-validation@example.com","password":os.environ["VALIDATION_PASSWORD"]}).encode()
request=urllib.request.Request(base+"/auth/login",data=body,headers={"Content-Type":"application/json"})
tokens=json.load(urllib.request.urlopen(request,timeout=5))
me=urllib.request.Request(base+"/users/me",headers={"Authorization":"Bearer "+tokens["access_token"]})
assert json.load(urllib.request.urlopen(me,timeout=5))["email"]=="restore-validation@example.com"'

mkdir -p -- "$evidence_dir"
{
  printf 'Restore validation: PASS\n'
  printf 'Validation ID: %s\nBackup ID: %s\n' "$validation_id" "$BACKUP_ID"
  printf 'Migration revision: %s\n' "$restored_revision"
  printf '%s\n' "$core_counts"
  printf 'Artifact archives: checksums and safe paths verified\n'
  printf 'Readiness: PASS\nAuthenticated smoke: PASS\n'
} >"$evidence_file"

audit_result success
printf 'Disposable restore validation passed.\nEvidence: %s\n' "$evidence_file"
