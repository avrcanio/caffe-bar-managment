# Mozzart

## Development notes

- Always check running services with `docker compose ps` before doing anything else.
- Run commands inside the Docker containers (e.g., the `web` service) instead of installing dependencies locally.

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
