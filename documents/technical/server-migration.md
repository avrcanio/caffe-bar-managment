# Migracija Mozzart na novi server

Ovaj runbook priprema deployment u `/opt/stacks/mozart` za migraciju aplikacije i baze prema issue-u #5.

## 1. Zaključavanje koda

```bash
cd /opt/stacks/mozart
git fetch origin
git checkout ea60119
```

- `origin` mora pokazivati na `https://github.com/avrcanio/caffe-bar-managment.git`
- lokalni `AGENTS.md` ostaje autoritativan za ovaj deployment folder

## 2. Finalni DB dump na source serveru

```bash
cd /opt/stacks/mozart
./scripts/migration/create_db_dump.sh
```

Output:

- dump se sprema u `backup/mozzart_<timestamp>.dump`
- checksum se sprema u `backup/mozzart_<timestamp>.dump.sha256`

Prije dumpa:

- otvoriti kratki maintenance prozor
- zaustaviti write promet prema starom `web`

## 3. Prijenos na target server

- klonirati ili syncati kod u `/opt/stacks/mozart`
- prenijeti dump i checksum u `backup/`
- pripremiti `.env` i ostale tajne na targetu

GitHub/Cloudflare operativa:

- `gh` CLI API koristi tokene iz `/opt/stacks/hosts.yml`
- Cloudflare DNS edit koristi `/opt/stacks/.cloudflare`

## 4. Restore i podizanje servisa

```bash
cd /opt/stacks/mozart
./scripts/migration/ensure_shared_postgis.sh
docker compose up -d redis print_bridge
./scripts/migration/restore_db_dump.sh backup/mozzart_<timestamp>.dump
docker compose up -d web celery_worker celery_beat frontend webterm
```

## 5. Verifikacija prije DNS cutovera

```bash
cd /opt/stacks/mozart
./scripts/migration/verify_stack.sh
```

Obavezno dodatno provjeriti:

- login/session
- ključne read pathove
- broj zapisa na kritičnim tablicama source vs target

## 6. DNS cutover i rollback

- DNS mijenjati tek nakon pune validacije
- rollback ide vraćanjem DNS-a na stari IP i vraćanjem prometa na stari `web`
- stari server ostaviti netaknut do isteka stabilizacijskog prozora
