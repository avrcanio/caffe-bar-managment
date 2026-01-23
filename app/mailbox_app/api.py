from django.db.models import Count, Q
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import generics, serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated

from .models import MailAttachment, MailMessage


class MailAttachmentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = MailAttachment
        fields = ["id", "filename", "content_type", "size", "file_url"]

    def get_file_url(self, obj):
        if not obj.file:
            return None
        request = self.context.get("request")
        url = obj.file.url
        return request.build_absolute_uri(url) if request else url


class MailMessageListSerializer(serializers.ModelSerializer):
    attachments_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = MailMessage
        fields = [
            "id",
            "mailbox",
            "subject",
            "from_email",
            "to_emails",
            "sent_at",
            "attachments_count",
        ]


class MailMessageDetailSerializer(serializers.ModelSerializer):
    attachments = MailAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = MailMessage
        fields = [
            "id",
            "mailbox",
            "subject",
            "from_email",
            "to_emails",
            "cc_emails",
            "sent_at",
            "body_text",
            "body_html",
            "attachments",
        ]


class MailboxPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class MailMessageListView(generics.ListAPIView):
    serializer_class = MailMessageListSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = MailboxPagination

    def get_queryset(self):
        qs = MailMessage.objects.annotate(
            attachments_count=Count("attachments")
        ).order_by("-sent_at", "-created_at")

        mailbox = self.request.query_params.get("mailbox")
        query = self.request.query_params.get("q")
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")
        has_attachments = self.request.query_params.get("has_attachments")

        if mailbox:
            qs = qs.filter(mailbox=mailbox)
        if query:
            qs = qs.filter(
                Q(subject__icontains=query)
                | Q(from_email__icontains=query)
                | Q(to_emails__icontains=query)
            )
        if date_from:
            dt = parse_datetime(date_from)
            if dt:
                qs = qs.filter(sent_at__gte=dt)
            else:
                d = parse_date(date_from)
                if d:
                    qs = qs.filter(sent_at__date__gte=d)
        if date_to:
            dt = parse_datetime(date_to)
            if dt:
                qs = qs.filter(sent_at__lte=dt)
            else:
                d = parse_date(date_to)
                if d:
                    qs = qs.filter(sent_at__date__lte=d)
        if has_attachments == "true":
            qs = qs.filter(attachments_count__gt=0)
        if has_attachments == "false":
            qs = qs.filter(attachments_count=0)

        return qs


class MailMessageDetailView(generics.RetrieveAPIView):
    queryset = MailMessage.objects.prefetch_related("attachments")
    serializer_class = MailMessageDetailSerializer
    permission_classes = [IsAuthenticated]
