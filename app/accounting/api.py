from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounting.services import account_ledger, get_default_cash_account
from accounting.models import Account


class CashLedgerView(APIView):
    def get(self, request):
        date_from = parse_date(request.query_params.get("date_from", ""))
        date_to = parse_date(request.query_params.get("date_to", ""))
        if not date_from or not date_to:
            return Response(
                {"detail": "Parametri date_from i date_to su obavezni (YYYY-MM-DD)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if date_from > date_to:
            return Response(
                {"detail": "date_from ne smije biti veći od date_to."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        account_code = request.query_params.get("account_code")
        if account_code:
            cash_account = Account.objects.filter(code=str(account_code).strip()).first()
            if not cash_account:
                return Response({"detail": "Konto nije pronađen."}, status=status.HTTP_404_NOT_FOUND)
        else:
            try:
                cash_account = get_default_cash_account()
            except RuntimeError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        result = account_ledger(cash_account, date_from, date_to)

        rows = [
            {
                "entry_id": r.entry_id,
                "entry_number": r.entry_number,
                "entry_date": r.entry_date.isoformat(),
                "description": r.description,
                "debit": r.debit,
                "credit": r.credit,
            }
            for r in result["rows"]
        ]

        return Response(
            {
                "account": {
                    "id": cash_account.id,
                    "code": cash_account.code,
                    "name": cash_account.name,
                },
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "opening_balance": result["opening_balance"],
                "period_debit": result["period_debit"],
                "period_credit": result["period_credit"],
                "closing_balance": result["closing_balance"],
                "rows": rows,
            }
        )
