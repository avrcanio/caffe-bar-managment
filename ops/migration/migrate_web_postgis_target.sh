#!/usr/bin/env bash
set -euo pipefail

TARGET_HOST=${TARGET_HOST:-}
TARGET_DIR=${TARGET_DIR:-/opt/stacks/mozart}
TARGET_BRANCH=${TARGET_BRANCH:-main}
REPO_URL=${REPO_URL:-git@github.com:avrcanio/caffe-bar-managment.git}
DUMP_PATH=${DUMP_PATH:-}
DUMP_SHA_PATH=${DUMP_SHA_PATH:-}
TARGET_DUMP_DIR=${TARGET_DUMP_DIR:-/opt/stacks/backups/mozzart}
DB_SERVICE=${DB_SERVICE:-postgis}
DB_USER=${DB_USER:-postgis}
DB_NAME=${DB_NAME:-mozzart_db}

if [[ -z "$TARGET_HOST" ]]; then
  echo "[error] Postavi TARGET_HOST (npr. root@<IP>)" >&2
  exit 1
fi
if [[ -z "$DUMP_PATH" || ! -f "$DUMP_PATH" ]]; then
  echo "[error] DUMP_PATH nije postavljen ili datoteka ne postoji" >&2
  exit 1
fi
if [[ -z "$DUMP_SHA_PATH" || ! -f "$DUMP_SHA_PATH" ]]; then
  echo "[error] DUMP_SHA_PATH nije postavljen ili datoteka ne postoji" >&2
  exit 1
fi

SSH_OPTS=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new)
DUMP_FILE=$(basename "$DUMP_PATH")
SHA_FILE=$(basename "$DUMP_SHA_PATH")

echo "[step] Provjera SSH veze"
ssh "${SSH_OPTS[@]}" "$TARGET_HOST" "hostname && whoami"

echo "[step] Priprema target direktorija i docker mreže"
ssh "${SSH_OPTS[@]}" "$TARGET_HOST" \
  TARGET_DIR="$TARGET_DIR" TARGET_DUMP_DIR="$TARGET_DUMP_DIR" \
  'bash -se' <<'REMOTE_PREP'
set -euo pipefail
command -v docker >/dev/null
docker compose version >/dev/null
mkdir -p "$TARGET_DIR" "$TARGET_DUMP_DIR"
docker network inspect hetzner_net >/dev/null 2>&1 || docker network create hetzner_net
REMOTE_PREP

echo "[step] Git clone / update na targetu"
ssh "${SSH_OPTS[@]}" "$TARGET_HOST" \
  TARGET_DIR="$TARGET_DIR" TARGET_BRANCH="$TARGET_BRANCH" REPO_URL="$REPO_URL" \
  'bash -se' <<'REMOTE_GIT'
set -euo pipefail
if [ -d "$TARGET_DIR/.git" ]; then
  git -C "$TARGET_DIR" fetch --all --tags
  git -C "$TARGET_DIR" checkout "$TARGET_BRANCH"
  git -C "$TARGET_DIR" pull --ff-only origin "$TARGET_BRANCH"
else
  rm -rf "$TARGET_DIR"
  git clone --branch "$TARGET_BRANCH" --single-branch "$REPO_URL" "$TARGET_DIR"
fi
REMOTE_GIT

echo "[step] Upload dump + checksum"
scp "${SSH_OPTS[@]}" "$DUMP_PATH" "$DUMP_SHA_PATH" "$TARGET_HOST:$TARGET_DUMP_DIR/"

echo "[step] Verifikacija checksum-a + restore"
ssh "${SSH_OPTS[@]}" "$TARGET_HOST" \
  TARGET_DIR="$TARGET_DIR" TARGET_DUMP_DIR="$TARGET_DUMP_DIR" \
  DUMP_FILE="$DUMP_FILE" SHA_FILE="$SHA_FILE" \
  DB_SERVICE="$DB_SERVICE" DB_USER="$DB_USER" DB_NAME="$DB_NAME" \
  'bash -se' <<'REMOTE_RESTORE'
set -euo pipefail
cd "$TARGET_DUMP_DIR"
sha256sum -c "$SHA_FILE"

cd "$TARGET_DIR"
docker compose up -d "$DB_SERVICE"
cat "$TARGET_DUMP_DIR/$DUMP_FILE" | docker compose exec -T "$DB_SERVICE" pg_restore -U "$DB_USER" -d "$DB_NAME" --clean --if-exists --no-owner --no-privileges

docker compose up -d --no-deps web || true
sleep 5
if ! docker compose ps --status running web | grep -q web; then
  docker compose up -d redis print_bridge web
fi
REMOTE_RESTORE

echo "[step] Validacija target stacka"
ssh "${SSH_OPTS[@]}" "$TARGET_HOST" \
  TARGET_DIR="$TARGET_DIR" DB_SERVICE="$DB_SERVICE" DB_USER="$DB_USER" DB_NAME="$DB_NAME" \
  'bash -se' <<'REMOTE_VALIDATE'
set -euo pipefail
cd "$TARGET_DIR"
docker compose config --services
docker compose ps
docker compose logs --tail=200 web "$DB_SERVICE"
docker compose exec -T "$DB_SERVICE" psql -U "$DB_USER" -d "$DB_NAME" -Atc "SELECT pg_size_pretty(pg_database_size('$DB_NAME'));"
REMOTE_VALIDATE

cat <<OUT
[ok] Migracija web+postgis pripremljena na target hostu.
Sljedeći korak: smoke test endpointa i DNS cutover.
OUT
