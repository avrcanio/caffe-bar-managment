from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


class PosPinVerifyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        pin = str(request.data.get("pin", "")).strip()
        if not pin:
            return Response({"detail": "PIN je obavezan."}, status=status.HTTP_400_BAD_REQUEST)

        profile = getattr(request.user, "pos_profile", None)
        if not profile or not profile.pin_hash:
            return Response({"detail": "PIN nije postavljen."}, status=status.HTTP_400_BAD_REQUEST)

        if not profile.check_pin(pin):
            return Response({"detail": "Neispravan PIN."}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"ok": True})
