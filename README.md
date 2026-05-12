# Mozzart

## Dev vs prod reverse proxy

- Dev (WSL/local): Caddy is layered via `docker-compose.dev.yml` (see start commands below).
- Prod (main server): Nginx outside Docker; Traefik in `docker-compose.yml` routes HTTPS to `web` and `frontend`.

### Start commands

Dev (WSL/local):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

Prod (this server / typical deploy):

```bash
docker compose up -d
```

See [AGENTS.md](AGENTS.md) for production pull, migrate, and restart steps.

## Development notes

- Always check running services with `docker compose ps` before doing anything else.
- Run commands inside the Docker containers (e.g., the `web` service) instead of installing dependencies locally.
- Deployment root on the target server is `/opt/stacks/mozart`.

## Where Django Lives (Backend)

The Django project runs in Docker service `web` (container name `mozzart`) and is exposed on `http://localhost:8003` (host) -> `:8000` (container).

Key paths:

- Django entrypoint: `app/manage.py`
- Django project package: `app/config/` (settings/urls/celery live here)
- Apps: `app/*` (e.g. `app/pos`, `app/sales`, `app/stock`, ...)

Typical commands (run inside container, not on the host shell):

```bash
docker compose exec web python manage.py check
docker compose exec web python manage.py migrate
docker compose exec web python manage.py makemigrations
docker compose exec web python manage.py shell
```

## Migration helpers

- DB dump: `./scripts/migration/create_db_dump.sh`
- DB restore: `./scripts/migration/restore_db_dump.sh /path/to/mozzart_<timestamp>.dump`
- Shared DB prep: `./scripts/migration/ensure_shared_postgis.sh`
- Stack verification: `./scripts/migration/verify_stack.sh`
- Runbook: `documents/technical/server-migration.md`

## POS Docs

- Endpoint mapping: `docs/pos/ANDROID_ENDPOINT_MAPPING.md`
- Catalog sync + FCM contract: `docs/pos/BARION_CATALOG_SYNC.md`
