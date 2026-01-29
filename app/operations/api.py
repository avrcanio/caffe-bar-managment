from decimal import Decimal, InvalidOperation

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounting.services import account_balance_as_of, get_default_cash_account
from .models import Shift, ShiftCashCount


class ShiftSerializer(serializers.ModelSerializer):
    class Meta:
        model = Shift
        fields = [
            "id",
            "status",
            "location",
            "opened_at",
            "closed_at",
            "opened_by",
            "closed_by",
        ]
        read_only_fields = ["status", "opened_at", "closed_at", "opened_by", "closed_by"]


class ShiftListCreateView(generics.ListCreateAPIView):
    queryset = Shift.objects.all().order_by("-opened_at")
    serializer_class = ShiftSerializer

    def perform_create(self, serializer):
        serializer.save(opened_by=self.request.user, status=Shift.Status.OPEN)


def _parse_decimal(value, field_name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise serializers.ValidationError({field_name: "Neispravan decimalni iznos."})


def _serialize_count(count: ShiftCashCount | None):
    if not count:
        return None
    return {
        "id": count.id,
        "kind": count.kind,
        "expected_amount": count.expected_amount,
        "counted_amount": count.counted_amount,
        "difference_amount": count.difference_amount,
        "note": count.note,
        "created_by": count.created_by_id,
        "created_at": count.created_at,
    }


class ShiftCashCountCreateView(APIView):
    def post(self, request, shift_id: int):
        shift = get_object_or_404(Shift, pk=shift_id)
        kind = request.data.get("kind")
        counted_amount = _parse_decimal(request.data.get("counted_amount"), "counted_amount")
        note = (request.data.get("note") or "").strip()

        if kind not in (ShiftCashCount.Kind.OPENING, ShiftCashCount.Kind.CLOSING):
            return Response({"kind": "Neispravan tip (OPENING/CLOSING)."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            cash_account = get_default_cash_account()
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        as_of_date = timezone.localdate()
        expected_amount = account_balance_as_of(cash_account, as_of_date)
        difference_amount = counted_amount - expected_amount

        if difference_amount != Decimal("0.00") and not note:
            return Response({"note": "Napomena je obavezna kada postoji razlika."}, status=status.HTTP_400_BAD_REQUEST)

        count = ShiftCashCount.objects.create(
            shift=shift,
            kind=kind,
            expected_amount=expected_amount,
            counted_amount=counted_amount,
            difference_amount=difference_amount,
            note=note,
            created_by=request.user,
        )

        if kind == ShiftCashCount.Kind.CLOSING:
            shift.status = Shift.Status.CLOSED
            shift.closed_at = timezone.now()
            shift.closed_by = request.user
            shift.save(update_fields=["status", "closed_at", "closed_by"])

        return Response(_serialize_count(count), status=status.HTTP_201_CREATED)


class ShiftCashSummaryView(APIView):
    def get(self, request, shift_id: int):
        shift = get_object_or_404(Shift, pk=shift_id)
        try:
            cash_account = get_default_cash_account()
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        as_of_date = shift.closed_at.date() if shift.closed_at else timezone.localdate()
        expected_amount = account_balance_as_of(cash_account, as_of_date)

        opening = (
            shift.cash_counts.filter(kind=ShiftCashCount.Kind.OPENING)
            .order_by("-created_at")
            .first()
        )
        closing = (
            shift.cash_counts.filter(kind=ShiftCashCount.Kind.CLOSING)
            .order_by("-created_at")
            .first()
        )

        counted_amount = closing.counted_amount if closing else None
        difference_amount = counted_amount - expected_amount if counted_amount is not None else None

        return Response(
            {
                "shift": ShiftSerializer(shift).data,
                "expected_amount": expected_amount,
                "counted_amount": counted_amount,
                "difference_amount": difference_amount,
                "opening_count": _serialize_count(opening),
                "closing_count": _serialize_count(closing),
            }
        )
