#!/usr/bin/env bash

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 /path/to/mozzart_<timestamp>.dump"
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DUMP_PATH="$1"
CHECKSUM_PATH="${DUMP_PATH}.sha256"
DB_CONTAINER="${DB_CONTAINER:-postgis}"
DB_ADMIN_USER="${DB_ADMIN_USER:-postgres}"
DB_APP_USER="${DB_APP_USER:-postgis}"
DB_APP_PASSWORD="${DB_APP_PASSWORD:-postgis}"
DB_NAME="${DB_NAME:-mozzart_db}"

if [[ ! -f "$DUMP_PATH" ]]; then
  echo "Dump file not found: $DUMP_PATH"
  exit 1
fi

if [[ -f "$CHECKSUM_PATH" ]]; then
  echo "Verifying checksum: $CHECKSUM_PATH"
  sha256sum -c "$CHECKSUM_PATH"
else
  echo "Checksum file not found, continuing without checksum verification"
fi

echo "Ensuring shared postgis network access"
"$ROOT_DIR/scripts/migration/ensure_shared_postgis.sh"

echo "Preparing role and database on shared postgis server"
docker exec -i "$DB_CONTAINER" psql -U "$DB_ADMIN_USER" -d postgres -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${DB_APP_USER}') THEN
        EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', '${DB_APP_USER}', '${DB_APP_PASSWORD}');
    ELSE
        EXECUTE format('ALTER ROLE %I WITH LOGIN PASSWORD %L', '${DB_APP_USER}', '${DB_APP_PASSWORD}');
    END IF;
END
\$\$;
SQL

docker exec "$DB_CONTAINER" psql -U "$DB_ADMIN_USER" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1 || \
  docker exec "$DB_CONTAINER" psql -U "$DB_ADMIN_USER" -d postgres -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_APP_USER};"

docker exec -i "$DB_CONTAINER" psql -U "$DB_ADMIN_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 <<SQL
ALTER DATABASE ${DB_NAME} OWNER TO ${DB_APP_USER};
GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_APP_USER};
CREATE EXTENSION IF NOT EXISTS postgis;
SQL

echo "Restoring dump into ${DB_NAME}"
cat "$DUMP_PATH" | docker exec -i "$DB_CONTAINER" \
  pg_restore --clean --if-exists --no-owner --no-privileges -U "$DB_ADMIN_USER" -d "$DB_NAME"

echo "Aligning ownership and grants for ${DB_APP_USER}"
docker exec -i "$DB_CONTAINER" psql -U "$DB_ADMIN_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 <<SQL
ALTER DATABASE ${DB_NAME} OWNER TO ${DB_APP_USER};
ALTER SCHEMA public OWNER TO ${DB_APP_USER};
GRANT USAGE, CREATE ON SCHEMA public TO ${DB_APP_USER};
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO ${DB_APP_USER};
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO ${DB_APP_USER};
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO ${DB_APP_USER};
SELECT format('ALTER TABLE public.%I OWNER TO ${DB_APP_USER};', tablename)
FROM pg_tables
WHERE schemaname = 'public'
\gexec
SELECT format('ALTER VIEW public.%I OWNER TO ${DB_APP_USER};', viewname)
FROM pg_views
WHERE schemaname = 'public'
\gexec
SELECT format('ALTER MATERIALIZED VIEW public.%I OWNER TO ${DB_APP_USER};', matviewname)
FROM pg_matviews
WHERE schemaname = 'public'
\gexec
ALTER DEFAULT PRIVILEGES FOR ROLE ${DB_APP_USER} IN SCHEMA public GRANT ALL ON TABLES TO ${DB_APP_USER};
ALTER DEFAULT PRIVILEGES FOR ROLE ${DB_APP_USER} IN SCHEMA public GRANT ALL ON SEQUENCES TO ${DB_APP_USER};
ALTER DEFAULT PRIVILEGES FOR ROLE ${DB_APP_USER} IN SCHEMA public GRANT ALL ON FUNCTIONS TO ${DB_APP_USER};
SQL

echo "Restore complete"
