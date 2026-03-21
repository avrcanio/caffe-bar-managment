# Mozzart migration scripts (web + postgis)

## 1) Source: freeze + dump + checksum

```bash
cd /srv/mozzart
ops/migration/prepare_source_artifacts.sh
```

Output daje `tag`, `dump` i `sha256` putanje.

## 2) Priprema env template datoteka (bez tajni)

```bash
cd /srv/mozzart
ops/migration/generate_env_templates.sh
```

Na target hostu popuniti:
- `.env.migration.template` -> `.env`
- `frontend/.env.local.migration.template` -> `frontend/.env.local`

## 3) Target: setup + restore + start + basic validation

```bash
cd /srv/mozzart
TARGET_HOST=root@<NOVI_SERVER_IP> \
TARGET_DIR=/opt/stacks/mozart \
TARGET_BRANCH=main \
DUMP_PATH=/srv/mozzart/backup/mozzart_<timestamp>.dump \
DUMP_SHA_PATH=/srv/mozzart/backup/mozzart_<timestamp>.dump.sha256 \
ops/migration/migrate_web_postgis_target.sh
```

## Napomene

- Skripta ne prenosi stare tajne; koristi nove vrijednosti na targetu.
- Ako `web` ne može samostalno startati, skripta automatski podiže `redis` i `print_bridge` kao fallback.
- DNS cutover radi se ručno nakon smoke testa aplikacije.
