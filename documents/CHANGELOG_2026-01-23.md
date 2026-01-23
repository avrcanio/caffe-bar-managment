# Mozzart – Changes (2026-01-23)

This document summarizes the changes implemented during the session.

## Backend (Django)

### OpenAPI / Docs
- Added `drf-spectacular` to `INSTALLED_APPS` and `DEFAULT_SCHEMA_CLASS`.
- Added `SPECTACULAR_SETTINGS` (title + version).
- Added schema and docs routes:
  - `GET /api/schema/`
  - `GET /api/docs/` (Swagger UI, staff-only)
  - `GET /api/redoc/` (Redoc, staff-only)
- Added OpenAPI response schema for `GET /api/me/`.

### Artikl Images (On‑the‑fly 46x75)
- Added `image_46x75` field to `/api/artikli/` and `/api/artikli/<rm_id>/` responses.
- Added image resize endpoint (no changes to stored images):
  - `GET /api/artikli/<rm_id>/image-46x75/`

### Supplier Artikli Endpoint
- `/api/suppliers/<id>/artikli/` now returns `image_46x75` in addition to `image`.

### Warehouse Sync API
- New endpoint for Remaris warehouse stock sync:
  - `POST /api/warehouses/sync/`
  - Requires authentication.
  - Returns: `detail`, `created`, `updated`, `skipped`.

### Admin action
- `WarehouseId` admin now supports running `import_warehouse_stock_for_warehouses` for **all** warehouses without manual selection.

## Frontend (Next.js)

### Supplier Artikli Image Mapping
- Mapper updated to use `image_46x75` (no fallback when requested):
  - `frontend/src/lib/mappers/suppliers.ts`

### Purchase Orders Pages
- Image rendering switched to `image_46x75` in:
  - `frontend/src/app/purchase-orders/new/page.tsx`
  - `frontend/src/app/purchase-orders/[id]/edit/page.tsx`

### Home Dashboard Sync Button
- "Sync podatke" button now calls `POST /api/warehouses/sync/`.
- Displays success/error toast.
- Button shows "Sync..." while running.

### PWA / Cache Tweaks
- Added PWA config improvements:
  - `cleanupOutdatedCaches: true`
  - `clientsClaim: true`
  - `skipWaiting: true`
  - `/_next/*` cached with short NetworkFirst policy
  - `frontend/next.config.mjs`

## Infrastructure / Nginx

### Reverse Proxy Fix
- The vhost for `mozart.sibenik1983.hr` was listening on `8443` while the container exposed `443`.
- Updated to:
  - `listen 443 ssl;`
  - File: `/srv/nginx/conf.d/mozart.sibenik1983.hr.conf`
- Reloaded nginx.

## Notes

- Frontend build logs reported npm vulnerabilities; no changes made.
- Backend logs still show a warning: `orders` has model changes without migrations.

## API Usage Examples

### Current User
```
curl -X GET 'https://mozart.sibenik1983.hr/api/me/' -H 'accept: application/json'
```

### Artikli list (includes `image_46x75`)
```
curl -X GET 'https://mozart.sibenik1983.hr/api/artikli/' -H 'accept: application/json'
```

### 46x75 image for a single artikl
```
curl -X GET 'https://mozart.sibenik1983.hr/api/artikli/<RM_ID>/image-46x75/'
```

### Supplier artikli list (includes `image_46x75`)
```
curl -X GET 'https://mozart.sibenik1983.hr/api/suppliers/<ID>/artikli/' -H 'accept: application/json'
```

### Warehouse sync
```
curl -X POST 'https://mozart.sibenik1983.hr/api/warehouses/sync/' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  --cookie "csrftoken=..." \
  -H "X-CSRFToken: ..."
```

## Frontend Behavior Details

- `image_46x75` is used on purchase order pages for thumbnails.
- No image resizing is done on save; only GET uses the resized endpoint.
- `Sync podatke` uses API call + toast; page remains usable.

## Troubleshooting

- **502 Bad Gateway on main domain**: verify nginx vhost listens on 443 and points to `mozzart-frontend:3000`.
- **Old JS bundle / cache issues**: clear browser cache or hard reload; PWA settings updated to reduce stale assets.
- **Swagger shows no response body**: ensure `drf-spectacular` is installed and `MeView` has schema response.
- **Sync button does nothing**: confirm `POST /api/warehouses/sync/` returns 200 and frontend rebuild is deployed.

## Security / Auth Notes

- `POST /api/warehouses/sync/` uses session auth; CSRF is required from the browser.
- Swagger UI for docs is staff-only; schema endpoint is public.

## Common Commands

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

## Files Modified

Backend:
- `app/config/settings.py`
- `app/config/urls.py`
- `app/config/api_views.py`
- `app/artikli/api.py`
- `app/orders/api.py`
- `app/stock/api.py`
- `app/stock/admin.py`
- `requirements.txt`

Frontend:
- `frontend/src/lib/mappers/suppliers.ts`
- `frontend/src/app/purchase-orders/new/page.tsx`
- `frontend/src/app/purchase-orders/[id]/edit/page.tsx`
- `frontend/src/app/page.tsx`
- `frontend/next.config.mjs`

Infra:
- `/srv/nginx/conf.d/mozart.sibenik1983.hr.conf`
