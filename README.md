# Caffe Bar Management

## Dev vs Prod reverse proxy

- Dev (WSL/local): uses Caddy from `docker-compose.dev.yml`.
- Prod (main server): uses Nginx outside Docker; Caddy is disabled in `docker-compose.yml`.

### Start commands

Dev (WSL/local):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

Prod (main server with Nginx):

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```
