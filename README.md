# Mozzart

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
