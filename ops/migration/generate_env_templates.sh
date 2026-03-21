#!/usr/bin/env bash
set -euo pipefail

REPO_DIR=${REPO_DIR:-/srv/mozzart}
SOURCE_ENV=${SOURCE_ENV:-$REPO_DIR/.env}
TARGET_ENV_TEMPLATE=${TARGET_ENV_TEMPLATE:-$REPO_DIR/.env.migration.template}
SOURCE_FE_ENV=${SOURCE_FE_ENV:-$REPO_DIR/frontend/.env.local}
TARGET_FE_ENV_TEMPLATE=${TARGET_FE_ENV_TEMPLATE:-$REPO_DIR/frontend/.env.local.migration.template}

if [[ ! -f "$SOURCE_ENV" ]]; then
  echo "[error] Missing $SOURCE_ENV" >&2
  exit 1
fi

awk -F= '/^[A-Za-z_][A-Za-z0-9_]*=/{print $1"=<SET_ON_TARGET>"}' "$SOURCE_ENV" > "$TARGET_ENV_TEMPLATE"

if [[ -f "$SOURCE_FE_ENV" ]]; then
  awk -F= '/^[A-Za-z_][A-Za-z0-9_]*=/{print $1"=<SET_ON_TARGET>"}' "$SOURCE_FE_ENV" > "$TARGET_FE_ENV_TEMPLATE"
fi

cat <<OUT
[ok] Env template datoteke:
- $TARGET_ENV_TEMPLATE
- $TARGET_FE_ENV_TEMPLATE
OUT
