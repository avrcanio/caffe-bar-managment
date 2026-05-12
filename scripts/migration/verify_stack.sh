#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HEALTHCHECK_URL="${HEALTHCHECK_URL:-http://127.0.0.1:8003/api/login/}"
DB_CONTAINER="${DB_CONTAINER:-postgis}"

"$ROOT_DIR/scripts/migration/ensure_shared_postgis.sh"

docker compose -f "$ROOT_DIR/docker-compose.yml" config --services
docker compose -f "$ROOT_DIR/docker-compose.yml" ps
docker compose -f "$ROOT_DIR/docker-compose.yml" logs --tail=200 web
docker logs --tail=200 "$DB_CONTAINER"

echo "Running HTTP smoke check against $HEALTHCHECK_URL"
HTTP_CODE="$(
  curl -s -o /dev/null -w '%{http_code}' \
    -X POST "$HEALTHCHECK_URL" \
    -H 'X-Forwarded-Proto: https' \
    -H 'Content-Type: application/json' \
    --data '{"username":"invalid","password":"invalid"}'
)"

if [[ "$HTTP_CODE" != "400" ]]; then
  echo "Unexpected login smoke-check status: $HTTP_CODE"
  exit 1
fi

echo "Stack verification passed"
