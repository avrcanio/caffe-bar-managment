from django.contrib.auth import authenticate, get_user_model, login, logout
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework import serializers
from drf_spectacular.utils import extend_schema
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"detail": "CSRF cookie set"})


class LoginView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get("username", "").strip()
        password = request.data.get("password", "")
        user = authenticate(request, username=username, password=password)
        if not user:
            return Response({"detail": "Invalid credentials"}, status=400)
        login(request, user)
        return Response(
            {"id": user.id, "username": user.username, "email": user.email}
        )


class LogoutView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response({"detail": "Logged out"})


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    class OutputSerializer(serializers.Serializer):
        id = serializers.IntegerField()
        username = serializers.CharField()
        email = serializers.EmailField(allow_null=True, allow_blank=True, required=False)
        first_name = serializers.CharField(allow_null=True, allow_blank=True, required=False)
        last_name = serializers.CharField(allow_null=True, allow_blank=True, required=False)

    @extend_schema(
        responses=OutputSerializer,
        description="Returns the currently authenticated user.",
    )
    def get(self, request):
        user = request.user
        return Response(
            {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
            }
        )


class UserDetailView(APIView):
    permission_classes = [IsAuthenticated]

    class OutputSerializer(serializers.Serializer):
        id = serializers.IntegerField()
        username = serializers.CharField()
        email = serializers.EmailField(allow_null=True, allow_blank=True, required=False)
        first_name = serializers.CharField(allow_null=True, allow_blank=True, required=False)
        last_name = serializers.CharField(allow_null=True, allow_blank=True, required=False)
        is_active = serializers.BooleanField()
        is_staff = serializers.BooleanField()
        is_superuser = serializers.BooleanField()

    @extend_schema(
        responses=OutputSerializer,
        description="Returns a user by id (authenticated only).",
    )
    def get(self, request, user_id):
        User = get_user_model()
        user = get_object_or_404(User, id=user_id)
        return Response(
            {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "is_active": user.is_active,
                "is_staff": user.is_staff,
                "is_superuser": user.is_superuser,
            }
        )
