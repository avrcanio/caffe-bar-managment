#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backup}"
TIMESTAMP="${TIMESTAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
DUMP_PATH="${1:-$BACKUP_DIR/mozzart_${TIMESTAMP}.dump}"
CHECKSUM_PATH="${DUMP_PATH}.sha256"

mkdir -p "$BACKUP_DIR"

echo "Creating dump at $DUMP_PATH"
docker compose -f "$ROOT_DIR/docker-compose.yml" exec -T postgis \
  pg_dump -U postgis -d mozzart_db -Fc > "$DUMP_PATH"

sha256sum "$DUMP_PATH" > "$CHECKSUM_PATH"

echo "Dump created: $DUMP_PATH"
echo "Checksum written: $CHECKSUM_PATH"
