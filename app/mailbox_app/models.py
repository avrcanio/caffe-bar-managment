from django.db import models


class MailboxState(models.Model):
    mailbox = models.CharField(max_length=255, default="INBOX", unique=True)
    last_uid = models.PositiveBigIntegerField(default=0)
    uid_validity = models.PositiveBigIntegerField(null=True, blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True, default="")

    def __str__(self) -> str:
        return f"{self.mailbox} (UID {self.last_uid})"


class MailMessage(models.Model):
    mailbox = models.CharField(max_length=255, default="INBOX")
    uid = models.PositiveBigIntegerField()
    message_id = models.CharField(max_length=255, blank=True)
    subject = models.CharField(max_length=255, blank=True)
    from_email = models.CharField(max_length=255, blank=True)
    to_emails = models.TextField(blank=True)
    cc_emails = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    body_text = models.TextField(blank=True)
    body_html = models.TextField(blank=True)
    raw_headers = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("mailbox", "uid")
        indexes = [
            models.Index(fields=["mailbox", "uid"]),
            models.Index(fields=["sent_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.subject or '(no subject)'}"


class MailAttachment(models.Model):
    message = models.ForeignKey(
        MailMessage, related_name="attachments", on_delete=models.CASCADE
    )
    filename = models.CharField(max_length=255, blank=True)
    content_type = models.CharField(max_length=255, blank=True)
    size = models.PositiveIntegerField(default=0)
    file = models.FileField(upload_to="mail_attachments/%Y/%m/%d")

    def __str__(self) -> str:
        return self.filename or "attachment"
