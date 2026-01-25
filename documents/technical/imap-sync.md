# IMAP sinkronizacija

> Modul: Tehnički
> Ovisi o: —
> Koriste ga: Razvoj, DevOps

## Sadržaj
- [Pregled](#pregled)
- [Komponente](#komponente)
- [Varijable okruženja](#varijable-okruzenja)
- [Docker servisi](#docker-servisi)
- [Ručna sinkronizacija](#rucna-sinkronizacija)
- [Admin gumb](#admin-gumb)
- [API](#api)
- [Logs / Rješavanje problema](#logs-rjesavanje-problema)
- [Lokacije podataka](#lokacije-podataka)


Ovaj dokument opisuje kako je IMAP sinkronizacija podešena i kako je pokrenuti.

## Pregled

The IMAP sync runs as a Celery task (`mailbox_app.tasks.sync_imap_mailbox`) and is scheduled every minute via Celery Beat. It stores messages and attachments in the database and media storage.

## Komponente

- **Django app**: `mailbox_app`
- **Models**:
  - `MailboxState` – tracks UID/UIDVALIDITY, last sync time, errors
  - `MailMessage` – saved email headers, body, sent date
  - `MailAttachment` – saved file attachments
- **Task**: `mailbox_app.tasks.sync_imap_mailbox`
- **Schedule**: every 1 minute
- **Storage**: attachments saved under `media/mail_attachments/YYYY/MM/DD/`

## Varijable okruženja

Set these in `.env` (or your secrets store):

```
IMAP_HOST=imap.hostinger.com
IMAP_PORT=993
IMAP_USER=...
IMAP_PASSWORD=...
IMAP_USE_SSL=True
IMAP_MAILBOX=INBOX
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0
```

## Docker servisi

Required services in `docker-compose.yml`:

- `redis`
- `celery_worker`
- `celery_beat`
- `web`

Start everything:

```
docker compose up -d --build
```

## Ručna sinkronizacija

## Admin gumb

In Django admin:
- Open **Mailbox states**
- Click **Sync mailbox now** (top-right button)

## API

```
curl -X POST 'https://mozart.sibenik1983.hr/api/mailbox/sync/' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  --cookie "csrftoken=..." \
  -H "X-CSRFToken: ..."
```

## Logs / Rješavanje problema

Check Celery worker logs:

```
docker logs -f mozzart-celery-worker
```

Common issues:

- **“IMAP settings not configured; skipping sync.”**  
  `IMAP_HOST`, `IMAP_USER`, or `IMAP_PASSWORD` are empty in the container env.

- **502 from /admin or /api**  
  nginx → backend connectivity; ensure `mozzart` is in `ALLOWED_HOSTS` and nginx container is on the same Docker network.

## Lokacije podataka

- Email metadata stored in `mailbox_app_mailmessage`.
- Attachments stored in `media/mail_attachments/`.

[← Back to index](../index.md)