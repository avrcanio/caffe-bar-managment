# Agent Instructions (mozzart)

These instructions apply when working in this repository (`/srv/mozzart`).

## Operating Principles

- Prefer small, safe, incremental changes over large rewrites.
- Preserve existing behavior unless the task explicitly requests a change.
- Keep changes production-minded: least privilege, no public exposure, and clear rollback.

## Docker / Deploy Conventions

- Backend work/services must run inside the `mozzart` Docker environment.
- Frontend work/services must run inside the `mozzart-frontend` Docker environment.
- Do not expose internal services publicly.
  - Use `expose:` (internal) instead of `ports:` unless explicitly requested.
- Keep services on the existing Docker network.
  - This repo uses an external network `hetzner_net`.
- When adding internal tooling containers (e.g., `webterm`):
  - Make container root filesystem read-only where possible (`read_only: true`).
  - Use `tmpfs` for `/tmp` and `/run`.
  - Drop Linux capabilities (`cap_drop: ["ALL"]`) and enable `no-new-privileges`.

## Web Terminal (ttyd) + Next.js Integration

- `webterm` runs internally on the Docker network and is reverse-proxied via nginx.
- Use base path `/api/webterm` for ttyd.
- WebSocket must be supported end-to-end.
  - Nginx should proxy `/api/webterm` directly to `mozzart-webterm:7681` with Upgrade headers.
- Access control:
  - Require an authenticated session cookie (`sessionid`) for `/api/webterm`.
  - Do not mount host directories other than the repo (`/srv/mozzart -> /workspace`) unless requested.

## Nginx Reverse Proxy

- Mozart vhost config is managed in `/srv/nginx/conf.d/mozart.sibenik1983.hr.conf` (host-mounted into `nginx_reverse_proxy`).
- When adding new routes:
  - Place more-specific `location` blocks above broader ones.
  - Ensure websocket locations set:
    - `proxy_http_version 1.1`
    - `proxy_set_header Upgrade $http_upgrade;`
    - `proxy_set_header Connection $connection_upgrade;`

## Next.js Frontend

- Next version is 14.x using the App Router.
- Avoid breaking the existing middleware auth model.
- For internal tools like webterm:
  - Prefer a simple page under `/webterm` that embeds the tool.

## Verification Checklist

After changes, run as relevant:

- `docker compose config --services`
- `docker compose up -d <service>`
- `docker compose ps`
- Internal connectivity test (from a container on the same network):
  - `docker compose exec frontend sh -lc "apk add --no-cache curl >/dev/null 2>&1 || true; curl -I http://webterm:7681"`

## Safety

- Never print secrets (API keys, auth keys, private certs).
- Don’t broaden network access or relax auth unless explicitly requested.
