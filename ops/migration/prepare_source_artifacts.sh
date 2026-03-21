#!/usr/bin/env bash
set -euo pipefail

REPO_DIR=${REPO_DIR:-/srv/mozzart}
DB_SERVICE=${DB_SERVICE:-postgis}
DB_USER=${DB_USER:-postgis}
DB_NAME=${DB_NAME:-mozzart_db}
BACKUP_DIR=${BACKUP_DIR:-$REPO_DIR/backup}
MIGRATION_TAG_PREFIX=${MIGRATION_TAG_PREFIX:-migration}
COMMIT=${COMMIT:-ea60119}

cd "$REPO_DIR"

if ! git rev-parse --verify "$COMMIT" >/dev/null 2>&1; then
  echo "[error] Commit $COMMIT ne postoji u repozitoriju" >&2
  exit 1
fi

TS=$(date -u +%Y%m%dT%H%M%SZ)
TAG_NAME="${MIGRATION_TAG_PREFIX}-${TS}-${COMMIT}"
DUMP_PATH="$BACKUP_DIR/mozzart_${TS}.dump"
SHA_PATH="${DUMP_PATH}.sha256"

mkdir -p "$BACKUP_DIR"

if git rev-parse -q --verify "refs/tags/$TAG_NAME" >/dev/null; then
  echo "[info] Tag već postoji: $TAG_NAME"
else
  git tag "$TAG_NAME" "$COMMIT"
  echo "[ok] Kreiran tag: $TAG_NAME"
fi

# MVCC snapshot dump (konsistentan bez lockanja svih tablica)
docker compose exec -T "$DB_SERVICE" pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc > "$DUMP_PATH"
sha256sum "$DUMP_PATH" > "$SHA_PATH"

DB_SIZE=$(docker compose exec -T "$DB_SERVICE" psql -U "$DB_USER" -d "$DB_NAME" -Atc "SELECT pg_size_pretty(pg_database_size('$DB_NAME'));" | tr -d '\r')

cat <<OUT
[ok] Artefakti spremni
- tag: $TAG_NAME
- dump: $DUMP_PATH
- sha256: $SHA_PATH
- db_size: $DB_SIZE
OUT
