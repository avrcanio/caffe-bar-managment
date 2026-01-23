from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from .tasks import sync_imap_mailbox


class MailboxSyncView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        result = sync_imap_mailbox.delay()
        return Response({"detail": "Sync queued", "task_id": result.id})
