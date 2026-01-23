from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="MailboxState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("mailbox", models.CharField(default="INBOX", max_length=255, unique=True)),
                ("last_uid", models.PositiveBigIntegerField(default=0)),
                ("uid_validity", models.PositiveBigIntegerField(blank=True, null=True)),
                ("last_sync_at", models.DateTimeField(blank=True, null=True)),
                ("error", models.TextField(blank=True, default="")),
            ],
        ),
        migrations.CreateModel(
            name="MailMessage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("mailbox", models.CharField(default="INBOX", max_length=255)),
                ("uid", models.PositiveBigIntegerField()),
                ("message_id", models.CharField(blank=True, max_length=255)),
                ("subject", models.CharField(blank=True, max_length=255)),
                ("from_email", models.CharField(blank=True, max_length=255)),
                ("to_emails", models.TextField(blank=True)),
                ("cc_emails", models.TextField(blank=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("body_text", models.TextField(blank=True)),
                ("body_html", models.TextField(blank=True)),
                ("raw_headers", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "unique_together": {("mailbox", "uid")},
                "indexes": [
                    models.Index(fields=["mailbox", "uid"], name="mailbox_app_mailbox_uid_idx"),
                    models.Index(fields=["sent_at"], name="mailbox_app_sent_at_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="MailAttachment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("filename", models.CharField(blank=True, max_length=255)),
                ("content_type", models.CharField(blank=True, max_length=255)),
                ("size", models.PositiveIntegerField(default=0)),
                ("file", models.FileField(upload_to="mail_attachments/%Y/%m/%d")),
                ("message", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="attachments", to="mailbox_app.mailmessage")),
            ],
        ),
    ]
