from django.contrib import admin, messages
from django.http import HttpRequest, HttpResponseRedirect
from django.urls import path, reverse

from .models import MailAttachment, MailboxState, MailMessage
from .tasks import sync_imap_mailbox


@admin.action(description="Sync mailbox now")
def sync_mailbox_now(modeladmin, request, queryset):
    sync_imap_mailbox.delay()
    messages.success(request, "IMAP sync queued.")


@admin.register(MailboxState)
class MailboxStateAdmin(admin.ModelAdmin):
    list_display = ("mailbox", "last_uid", "uid_validity", "last_sync_at")
    search_fields = ("mailbox",)
    actions = [sync_mailbox_now]
    change_list_template = "admin/mailbox_app/mailboxstate/change_list.html"

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path("sync-now/", self.admin_site.admin_view(self.sync_now_view), name="mailbox_sync_now"),
        ]
        return custom + urls

    def sync_now_view(self, request: HttpRequest):
        sync_imap_mailbox.delay()
        messages.success(request, "IMAP sync queued.")
        changelist_url = reverse("admin:mailbox_app_mailboxstate_changelist")
        return HttpResponseRedirect(changelist_url)


@admin.register(MailMessage)
class MailMessageAdmin(admin.ModelAdmin):
    list_display = ("subject", "from_email", "sent_at", "mailbox", "uid")
    search_fields = ("subject", "from_email", "to_emails", "cc_emails")
    list_filter = ("mailbox",)


@admin.register(MailAttachment)
class MailAttachmentAdmin(admin.ModelAdmin):
    list_display = ("filename", "content_type", "size", "message")
    search_fields = ("filename",)
