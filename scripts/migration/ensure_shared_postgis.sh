#!/usr/bin/env bash

set -euo pipefail

NETWORK_NAME="${NETWORK_NAME:-hetzner_net}"
DB_CONTAINER="${DB_CONTAINER:-postgis}"
DB_ALIAS="${DB_ALIAS:-postgis}"

if ! docker network inspect "$NETWORK_NAME" >/dev/null 2>&1; then
  echo "Docker network not found: $NETWORK_NAME"
  exit 1
fi

if ! docker inspect "$DB_CONTAINER" >/dev/null 2>&1; then
  echo "Docker container not found: $DB_CONTAINER"
  exit 1
fi

if docker network inspect "$NETWORK_NAME" --format '{{json .Containers}}' | grep -q "\"Name\":\"$DB_CONTAINER\""; then
  echo "Container $DB_CONTAINER already connected to $NETWORK_NAME"
  exit 0
fi

docker network connect --alias "$DB_ALIAS" "$NETWORK_NAME" "$DB_CONTAINER"
echo "Connected $DB_CONTAINER to $NETWORK_NAME with alias $DB_ALIAS"
