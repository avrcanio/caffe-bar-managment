import email
import imaplib
import logging
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

from celery import shared_task
from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone

from .models import MailAttachment, MailboxState, MailMessage

logger = logging.getLogger(__name__)


def _decode_header_value(value: str) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _parse_email_date(value: str):
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except Exception:
        return None
    if not parsed:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone=timezone.get_default_timezone())
    return parsed


def _extract_bodies(message: email.message.Message) -> tuple[str, str]:
    text_parts = []
    html_parts = []
    for part in message.walk():
        if part.is_multipart():
            continue
        content_type = part.get_content_type()
        content_disposition = (part.get("Content-Disposition") or "").lower()
        if "attachment" in content_disposition:
            continue
        payload = part.get_payload(decode=True) or b""
        charset = part.get_content_charset() or "utf-8"
        try:
            content = payload.decode(charset, errors="replace")
        except LookupError:
            content = payload.decode("utf-8", errors="replace")
        if content_type == "text/plain":
            text_parts.append(content)
        elif content_type == "text/html":
            html_parts.append(content)
    return "\n".join(text_parts).strip(), "\n".join(html_parts).strip()


def _extract_headers(message: email.message.Message) -> str:
    return "\n".join(f"{key}: {value}" for key, value in message.items())


@shared_task
def sync_imap_mailbox() -> int:
    host = settings.IMAP_HOST
    username = settings.IMAP_USER
    password = settings.IMAP_PASSWORD
    if not host or not username or not password:
        logger.warning("IMAP settings not configured; skipping sync.")
        return 0

    mailbox = settings.IMAP_MAILBOX or "INBOX"
    state, _ = MailboxState.objects.get_or_create(mailbox=mailbox)

    try:
        if settings.IMAP_USE_SSL:
            imap = imaplib.IMAP4_SSL(host, settings.IMAP_PORT)
        else:
            imap = imaplib.IMAP4(host, settings.IMAP_PORT)
        imap.login(username, password)

        status, _ = imap.select(mailbox)
        if status != "OK":
            raise RuntimeError(f"IMAP select failed for {mailbox}")

        uid_validity = None
        uid_status, uid_data = imap.response("UIDVALIDITY")
        if uid_status == "OK" and uid_data and uid_data[0]:
            try:
                uid_validity = int(uid_data[0])
            except (TypeError, ValueError):
                uid_validity = None

        if uid_validity and state.uid_validity and uid_validity != state.uid_validity:
            state.last_uid = 0
        if uid_validity:
            state.uid_validity = uid_validity

        search_criteria = "ALL" if state.last_uid == 0 else f"UID {state.last_uid + 1}:*"
        status, data = imap.uid("search", None, search_criteria)
        if status != "OK":
            raise RuntimeError("IMAP UID search failed")

        uid_list = data[0].split() if data and data[0] else []
        created_count = 0

        for uid_bytes in uid_list:
            uid = int(uid_bytes)
            if MailMessage.objects.filter(mailbox=mailbox, uid=uid).exists():
                state.last_uid = max(state.last_uid, uid)
                continue

            fetch_status, msg_data = imap.uid("fetch", str(uid), "(RFC822)")
            if fetch_status != "OK" or not msg_data or not msg_data[0]:
                continue

            raw_message = msg_data[0][1]
            message = email.message_from_bytes(raw_message)

            subject = _decode_header_value(message.get("Subject", ""))
            from_email = _decode_header_value(message.get("From", ""))
            to_emails = _decode_header_value(message.get("To", ""))
            cc_emails = _decode_header_value(message.get("Cc", ""))
            message_id = message.get("Message-Id", "") or message.get("Message-ID", "")
            sent_at = _parse_email_date(message.get("Date", ""))
            body_text, body_html = _extract_bodies(message)

            mail_message = MailMessage.objects.create(
                mailbox=mailbox,
                uid=uid,
                message_id=message_id,
                subject=subject,
                from_email=from_email,
                to_emails=to_emails,
                cc_emails=cc_emails,
                sent_at=sent_at,
                body_text=body_text,
                body_html=body_html,
                raw_headers=_extract_headers(message),
            )

            for part in message.walk():
                if part.is_multipart():
                    continue
                filename = part.get_filename()
                content_disposition = (part.get("Content-Disposition") or "").lower()
                if not filename and "attachment" not in content_disposition:
                    continue

                payload = part.get_payload(decode=True)
                if not payload:
                    continue

                decoded_filename = _decode_header_value(filename or "")
                attachment = MailAttachment(
                    message=mail_message,
                    filename=decoded_filename,
                    content_type=part.get_content_type() or "",
                    size=len(payload),
                )
                attachment.file.save(
                    decoded_filename or f"attachment-{uid}",
                    ContentFile(payload),
                    save=True,
                )

            created_count += 1
            state.last_uid = max(state.last_uid, uid)

        state.last_sync_at = timezone.now()
        state.error = ""
        state.save(update_fields=["last_uid", "uid_validity", "last_sync_at", "error"])

        imap.logout()
        return created_count
    except Exception as exc:
        logger.exception("IMAP sync failed")
        state.error = str(exc)
        state.last_sync_at = timezone.now()
        state.save(update_fields=["error", "last_sync_at"])
        raise
