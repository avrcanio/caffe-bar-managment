# Barion Catalog Sync and FCM Trigger

Ovaj dokument opisuje trenutni backend contract za Barion POS katalog sync u `mozart` backendu.

Source of truth:
- `app/barion/api.py`
- `app/barion/catalog_sync.py`
- `app/barion/signals.py`
- `app/barion/tasks.py`
- `app/barion/models.py`
- `app/config/urls.py`

## Scope

Sync domena pokriva:
- layouts
- categories
- products
- modifiers

Live operativno stanje nije dio catalog synca:
- otvoreni racuni
- payment state
- live occupancy/status stolova

Za to Android i dalje koristi postojece live endpointove.

## Full Snapshot

Initial snapshot endpoint:

- `GET /api/pos/bootstrap/?include_products=1`

Bootstrap vraca:
- `catalog_version`
- trenutni `active_mode`
- categories snapshot
- pocetni products snapshot

Product payload sadrzi i nova polja:
- `thumbnail_url`
- `image_url`
- `image_version`
- `modifier_version`

Bootstrap je full snapshot i recovery path.

Android treba raditi bootstrap:
- na cold startu bez lokalnog stanja
- kad backend vrati `requiresFullSync=true`

## Canonical Delta Endpoint

Jedini canonical delta source je:

- `GET /api/pos/catalog/changes/?afterVersion={n}&limit={m}[&targetVersion={t}]`

Response shape:

```json
{
  "requiresFullSync": false,
  "baseVersion": 18,
  "appliedThroughVersion": 19,
  "targetVersion": 19,
  "catalogVersion": 19,
  "layouts": {
    "updated": [],
    "deleted": []
  },
  "categories": {
    "updated": [],
    "deleted": []
  },
  "products": {
    "updated": [],
    "deleted": []
  },
  "hasMore": false
}
```

Pravila:
- `requiresFullSync=true` znaci da Android mora napustiti delta flow i ponovo raditi bootstrap
- `targetVersion` zakljucava stabilni paging window
- `appliedThroughVersion` je cursor za sljedecu stranicu unutar istog `targetVersion`
- `deleted[]` su tombstone ID-evi

Ako vise promjena pogodi isti entitet unutar istog sync prozora, backend vraca samo finalno stanje na `targetVersion`.

## Modifier Sync Pravilo

Modifiers nisu poseban top-level delta collection.

Pravilo je:
- promjena modifiera oznaci owning product kao updated
- owning product dobije novi `modifier_version`
- Android invalidira local modifier cache za taj product
- detalje onda cita preko:
  - `GET /api/pos/products/{artikl_id}/modifiers/`

Modifier endpoint vraca:
- `artikl_id`
- `modifier_version`
- `modifier_groups`

## Image Versioning

Backend product payload vraca:
- `thumbnail_url`
- `image_url`
- `image_version`

Android treba graditi cache key s `image_version`, npr.:

```text
thumbnail_url + "?v=" + image_version
image_url + "?v=" + image_version
```

Time promjena slike ne vraca stari cache hit.

## FCM Trigger

FCM je trigger, ne data transport.

Backend nakon relevantne catalog promjene:
1. bumpa `catalog_version`
2. enqueuea Celery task `barion.tasks.send_catalog_changed_notification`
3. task zove interni `gcloud-api /fcm/send`
4. FCM salje data poruku na topic `barion_catalog`

Payload:

```json
{
  "type": "catalog_changed",
  "catalogVersion": "19"
}
```

Runtime config:
- `BARION_FCM_ENABLED=true`
- `BARION_FCM_PROJECT_ALIAS=fcm_barion`
- `BARION_FCM_TOPIC=barion_catalog`

## Runtime Mode Change

Promjena `BarionRuntimeMode` (`day` / `night`) ide kroz isti catalog sync lanac.

Kad admin promijeni mode u Django adminu:
- backend napravi jedan catalog event batch
- digne `catalog_version`
- posalje standardni `catalog_changed` FCM trigger

Android zatim treba:
1. pokrenuti delta sync
2. procitati `GET /api/pos/runtime-mode/`
3. ako se `active_mode` promijenio, odmah promijeniti UI bez `forceBootstrap`

## Android Requirements

Za near real-time ponasanje Android mora imati:
- FCM wiring u buildu
- topic subscribe na `barion_catalog`
- receiver za `data.type == "catalog_changed"`
- delta sync flow koji koristi `catalog/changes`
- `runtime-mode` fetch nakon uspjesnog catalog synca

Ako FCM nije aktivan, app i dalje moze raditi preko:
- app start synca
- foreground synca
- periodickog fallback synca

## Current Backend Status

Implementirano i verificirano na backendu:
- `catalog_version`
- sync event log
- `image_version`
- `modifier_version`
- bootstrap additive fields
- `catalog/changes`
- `requiresFullSync`
- `baseVersion`, `targetVersion`, `appliedThroughVersion`
- tombstones / `deleted[]`
- FCM trigger kroz `gcloud-api`
- runtime mode promjena salje standardni `catalog_changed`

Nije dio backend implementacije:
- Android FCM subscription wiring
- Android Firebase setup (`google-services.json`, Firebase Messaging service)
- Android category fallback issue fix
