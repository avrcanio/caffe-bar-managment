# Dnevnik promjena (2026-01-23)

## Sadržaj
- [Pozadina (Django)](#pozadina-django)
- [OpenAPI / dokumentacija](#openapi-dokumentacija)
- [Slike artikla (u hodu 46x75)](#slike-artikla-u-hodu-46x75)
- [Endpoint artikala dobavljača](#endpoint-artikala-dobavljaca)
- [API sinkronizacije skladišta](#api-sinkronizacije-skladista)
- [Admin akcija](#admin-akcija)
- [IMAP sinkronizacija sandučića (novo)](#imap-sinkronizacija-sanducica-novo)
- [Sučelje (Next.js)](#sucelje-nextjs)
- [Mapiranje slika artikala dobavljača](#mapiranje-slika-artikala-dobavljaca)
- [Stranice narudžbi](#stranice-narudzbi)
- [Gumb sinkronizacije na dashboardu](#gumb-sinkronizacije-na-dashboardu)
- [PWA / cache dorade](#pwa-cache-dorade)
- [Infrastruktura / Nginx](#infrastruktura-nginx)
- [Ispravak reverse proxyja](#ispravak-reverse-proxyja)
- [Celery / Redis](#celery-redis)
- [Novi servisi](#novi-servisi)
- [Napomene](#napomene)
- [Primjeri API korištenja](#primjeri-api-koristenja)
- [Trenutni korisnik](#trenutni-korisnik)
- [Popis artikala (sadrži `image_46x75`)](#popis-artikala-sadrzi-`image_46x75`)
- [Slika 46x75 za jedan artikl](#slika-46x75-za-jedan-artikl)
- [Popis artikala dobavljača (sadrži `image_46x75`)](#popis-artikala-dobavljaca-sadrzi-`image_46x75`)
- [Sinkronizacija skladišta](#sinkronizacija-skladista)
- [Detalji ponašanja sučelja](#detalji-ponasanja-sucelja)
- [Rješavanje problema](#rjesavanje-problema)
- [Sigurnost / autentikacija](#sigurnost-autentikacija)
- [Dodatna ažuriranja (kasno 2026-01-23)](#dodatna-azuriranja-kasno-2026-01-23)
- [Pozadina (Django)](#pozadina-django)
- [Sučelje (Next.js)](#sucelje-nextjs)
- [PWA / build sučelja](#pwa-build-sucelja)
- [Docker / Nginx](#docker-nginx)
- [Remaris konfiguracija](#remaris-konfiguracija)
- [IMAP konfiguracija](#imap-konfiguracija)
- [Ručna sinkronizacija](#rucna-sinkronizacija)
- [Upute za rollback](#upute-za-rollback)
- [Pozadina (Django)](#pozadina-django)
- [Sučelje (Next.js)](#sucelje-nextjs)
- [Nginx reverse proxy](#nginx-reverse-proxy)
- [Uobičajene naredbe](#uobicajene-naredbe)
- [Promijenjene datoteke](#promijenjene-datoteke)


This document summarizes the changes implemented during the session.

## Pozadina (Django)

## OpenAPI / dokumentacija
- Added `drf-spectacular` to `INSTALLED_APPS` and `DEFAULT_SCHEMA_CLASS`.
- Added `SPECTACULAR_SETTINGS` (title + version).
- Added schema and docs routes:
  - `GET /api/schema/`
  - `GET /api/docs/` (Swagger UI, staff-only)
  - `GET /api/redoc/` (Redoc, staff-only)
- Added OpenAPI response schema for `GET /api/me/`.

## Slike artikla (u hodu 46x75)
- Added `image_46x75` field to `/api/artikli/` and `/api/artikli/<rm_id>/` responses.
- Added image resize endpoint (no changes to stored images):
  - `GET /api/artikli/<rm_id>/image-46x75/`

## Endpoint artikala dobavljača
- `/api/suppliers/<id>/artikli/` now returns `image_46x75` in addition to `image`.

## API sinkronizacije skladišta
- New endpoint for Remaris warehouse stock sync:
  - `POST /api/warehouses/sync/`
  - Requires authentication.
  - Returns: `detail`, `created`, `updated`, `skipped`.

## Admin akcija
- `WarehouseId` admin now supports running `import_warehouse_stock_for_warehouses` for **all** warehouses without manual selection.

## IMAP sinkronizacija sandučića (novo)
- Added `mailbox_app` Django app with models:
  - `MailboxState` (last UID, UIDVALIDITY, last sync time, error)
  - `MailMessage` (headers, bodies, sent time)
  - `MailAttachment` (stored files)
- Added Celery task `mailbox_app.tasks.sync_imap_mailbox` and periodic schedule (every minute).
- Added admin action + toolbar button to trigger sync manually.
- Added API endpoint:
  - `POST /api/mailbox/sync/` (admin-only)
- Added IMAP settings in `app/config/settings.py`.
- Added `mozzart` to `ALLOWED_HOSTS` for nginx/Docker upstream calls.

## Sučelje (Next.js)

## Mapiranje slika artikala dobavljača
- Mapper updated to use `image_46x75` (no fallback when requested):
  - `frontend/src/lib/mappers/suppliers.ts`

## Stranice narudžbi
- Image rendering switched to `image_46x75` in:
  - `frontend/src/app/purchase-orders/new/page.tsx`
  - `frontend/src/app/purchase-orders/[id]/edit/page.tsx`

## Gumb sinkronizacije na dashboardu
- "Sync podatke" button now calls `POST /api/warehouses/sync/`.
- Displays success/error toast.
- Button shows "Sync..." while running.

## PWA / cache dorade
- Added PWA config improvements:
  - `cleanupOutdatedCaches: true`
  - `clientsClaim: true`
  - `skipWaiting: true`
  - `/_next/*` cached with short NetworkFirst policy
  - `frontend/next.config.mjs`

## Infrastruktura / Nginx

## Ispravak reverse proxyja
- The vhost for `mozart.sibenik1983.hr` was listening on `8443` while the container exposed `443`.
- Updated to:
  - `listen 443 ssl;`
  - File: `/srv/nginx/conf.d/mozart.sibenik1983.hr.conf`
- Reloaded nginx.

## Celery / Redis

## Novi servisi
- Added `redis`, `celery_worker`, `celery_beat` to `docker-compose.yml`.
- Added `celery` and `redis` to `requirements.txt`.

## Napomene

- Frontend build logs reported npm vulnerabilities; no changes made.
- Backend logs still show a warning: `orders` has model changes without migrations.

## Primjeri API korištenja

## Trenutni korisnik
```
curl -X GET 'https://mozart.sibenik1983.hr/api/me/' -H 'accept: application/json'
```

## Popis artikala (sadrži `image_46x75`)
```
curl -X GET 'https://mozart.sibenik1983.hr/api/artikli/' -H 'accept: application/json'
```

## Slika 46x75 za jedan artikl
```
curl -X GET 'https://mozart.sibenik1983.hr/api/artikli/<RM_ID>/image-46x75/'
```

## Popis artikala dobavljača (sadrži `image_46x75`)
```
curl -X GET 'https://mozart.sibenik1983.hr/api/suppliers/<ID>/artikli/' -H 'accept: application/json'
```

## Sinkronizacija skladišta
```
curl -X POST 'https://mozart.sibenik1983.hr/api/warehouses/sync/' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  --cookie "csrftoken=..." \
  -H "X-CSRFToken: ..."
```

## Detalji ponašanja sučelja

- `image_46x75` is used on purchase order pages for thumbnails.
- No image resizing is done on save; only GET uses the resized endpoint.
- `Sync podatke` uses API call + toast; page remains usable.

## Rješavanje problema

- **502 Bad Gateway on main domain**: verify nginx vhost listens on 443 and points to `mozzart-frontend:3000`.
- **Old JS bundle / cache issues**: clear browser cache or hard reload; PWA settings updated to reduce stale assets.
- **Swagger shows no response body**: ensure `drf-spectacular` is installed and `MeView` has schema response.
- **Sync button does nothing**: confirm `POST /api/warehouses/sync/` returns 200 and frontend rebuild is deployed.

## Sigurnost / autentikacija

- `POST /api/warehouses/sync/` uses session auth; CSRF is required from the browser.
- Swagger UI for docs is staff-only; schema endpoint is public.

## Dodatna ažuriranja (kasno 2026-01-23)

## Pozadina (Django)
- `PurchaseOrderItemSerializer` now returns `base_group` (from `artikl.detail.base_group.name`).
- Added proxy-aware HTTPS settings:
  - `SECURE_PROXY_SSL_HEADER`
  - `USE_X_FORWARDED_HOST`
- Optimized PO queries with `prefetch_related("items__artikl__detail__base_group")`.

## Sučelje (Next.js)
- Added API helpers (`apiRequest`, `apiGetJson`, `apiPostJson`, `apiPutJson`, `apiPatchJson`, `apiDelete`).
- Added format helpers (`formatEuro`, `formatDate`, `formatDateTime`).
- Added UI helpers (`EmptyState`, `LoadingCard`, `FilterSelect`).
- Introduced mappers + domain models under `frontend/src/lib/mappers/` with barrel export.
- New PO edit screen: `/purchase-orders/[id]/edit` (prefill, update items, save).
- PO detail: grouped items by `base_group` + navigation; status card opens modal with **Edit / Send** when status is `created`.
- PO new/edit: grouped artikli by `baseGroup`, navigation, scroll-to-item from cart.
- Dashboard links to `/purchase-orders`, list view uses card click to open details.

## PWA / build sučelja
- Added PWA via `next-pwa`, manifest, service worker, and icons generated from `mozER Lunchwe.png`.
- Runtime cache for `/api/**` GET (NetworkFirst, short TTL).
- Added type stubs for `minimatch` and `prop-types` to fix build.

## Docker / Nginx
- Frontend container runs production build (`npm run build && npm run start -- -p 3000`).
- Nginx updated with cache headers for PWA assets:
  - `/_next/*` long immutable cache
  - `/icons/*` long immutable cache
  - `/manifest.json` short cache
  - `/sw.js` no-cache
  - `/` no-store
- Fixed nginx health: upstream `mozzart-frontend` now running.

## Remaris konfiguracija

Environment variables (stored in `.env` or your secrets store):
- `REMARIS_BASE_URL` (e.g. `https://mozart.remaris.hr`)
- `REMARIS_USERNAME`
- `REMARIS_PASSWORD`

Used by:
- `artikli.remaris_connector.RemarisConnector`
- Warehouse sync endpoints and admin import actions.

Notes:
- Ensure the Remaris account has access to Warehouse/Stock endpoints.
- If sync returns 502 from API, check Remaris reachability and credentials.

## IMAP konfiguracija

Environment variables (stored in `.env` or your secrets store):
- `IMAP_HOST` (e.g. `imap.hostinger.com`)
- `IMAP_PORT` (e.g. `993`)
- `IMAP_USER`
- `IMAP_PASSWORD`
- `IMAP_USE_SSL` (`True`/`False`)
- `IMAP_MAILBOX` (default: `INBOX`)
- `CELERY_BROKER_URL` (default: `redis://redis:6379/0`)
- `CELERY_RESULT_BACKEND` (default: `redis://redis:6379/0`)

Notes:
- IMAP sync is skipped if `IMAP_HOST/USER/PASSWORD` are missing.
- Attachments are stored under `media/mail_attachments/YYYY/MM/DD/`.

## Ručna sinkronizacija
Admin button:
- Go to **Mailbox states** in admin and click **Sync mailbox now**.

API:
```
curl -X POST 'https://mozart.sibenik1983.hr/api/mailbox/sync/' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  --cookie "csrftoken=..." \
  -H "X-CSRFToken: ..."
```

## Upute za rollback

## Pozadina (Django)
1) Revert code changes:
```
cd /srv/mozzart
git checkout -- app/stock/api.py app/orders/api.py app/artikli/api.py app/config/api_views.py app/config/urls.py app/config/settings.py requirements.txt
```
2) Rebuild + restart:
```
docker compose build web
docker compose up -d web
```

## Sučelje (Next.js)
1) Revert code changes:
```
cd /srv/mozzart
git checkout -- frontend/src/lib/mappers/suppliers.ts frontend/src/app/purchase-orders/new/page.tsx frontend/src/app/purchase-orders/[id]/edit/page.tsx frontend/src/app/page.tsx frontend/next.config.mjs
```
2) Rebuild:
```
docker compose up -d --build frontend
```

## Nginx reverse proxy
1) Restore config:
```
cd /srv/nginx
git checkout -- conf.d/mozart.sibenik1983.hr.conf
```
2) Reload:
```
docker exec nginx_reverse_proxy sh -lc "nginx -t && nginx -s reload"
```

## Uobičajene naredbe

Rebuild backend:
```
docker compose build web
docker compose up -d web
```

Rebuild frontend:
```
docker compose up -d --build frontend
```

Nginx reload (inside container):
```
docker exec nginx_reverse_proxy sh -lc "nginx -t && nginx -s reload"
```

## Promijenjene datoteke

Backend:
- `app/config/settings.py`
- `app/config/urls.py`
- `app/config/api_views.py`
- `app/config/celery.py`
- `app/mailbox_app/api_views.py`
- `app/mailbox_app/admin.py`
- `app/mailbox_app/apps.py`
- `app/mailbox_app/models.py`
- `app/mailbox_app/tasks.py`
- `app/mailbox_app/migrations/0001_initial.py`
- `app/artikli/api.py`
- `app/orders/api.py`
- `app/stock/api.py`
- `app/stock/admin.py`
- `requirements.txt`
 - `docker-compose.yml`
 - `.env`

Frontend:
- `frontend/src/lib/mappers/suppliers.ts`
- `frontend/src/app/purchase-orders/new/page.tsx`
- `frontend/src/app/purchase-orders/[id]/edit/page.tsx`
- `frontend/src/app/page.tsx`
- `frontend/next.config.mjs`

Infra:
- `/srv/nginx/conf.d/mozart.sibenik1983.hr.conf`

[← Back to index](index.md)