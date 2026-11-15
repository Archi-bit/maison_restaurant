from django.conf import settings
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.generics import GenericAPIView, RetrieveAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.views import TokenBlacklistView, TokenRefreshView, TokenViewBase

from .permissions import HasEmployeeProfile
from .serializers import (EmployeeProfileSerializer, LoginSerializer, PasswordResetConfirmSerializer, PasswordResetSerializer, RefreshSerializer)

detail_response = inline_serializer(
    name="StaffDetail", fields={"detail": serializers.CharField()}
)


class LoginView(TokenViewBase):
    serializer_class = LoginSerializer

    @extend_schema(
        description="Фиксированный срок сессии от входа: 3 дня или 30 дней с remember_me.",
        responses={200: LoginSerializer, 400: OpenApiTypes.OBJECT, 401: detail_response},
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class RefreshView(TokenRefreshView):
    serializer_class = RefreshSerializer

    @extend_schema(
        description="Новый access в пределах исходного срока сессии.",
        responses={200: RefreshSerializer, 400: OpenApiTypes.OBJECT, 401: detail_response},
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class LogoutView(TokenBlacklistView):
    @extend_schema(
        description="Отзывает refresh. Выданный access действует до истечения своего срока.",
        responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT, 401: detail_response},
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class MeView(RetrieveAPIView):
    authentication_classes = (JWTAuthentication,)
    permission_classes = (HasEmployeeProfile,)
    serializer_class = EmployeeProfileSerializer

    @extend_schema(
        responses={200: EmployeeProfileSerializer, 401: detail_response, 403: detail_response}
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_object(self):
        return self.request.user.employee_profile


class PasswordResetView(GenericAPIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)
    serializer_class = PasswordResetSerializer

    @extend_schema(
        description="В локальной среде выводит письмо в консоль.",
        responses={200: detail_response, 400: OpenApiTypes.OBJECT, 404: detail_response},
    )
    def post(self, request):
        if not settings.STAFF_PASSWORD_RESET_ENABLED:
            raise NotFound()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"detail": "Если рабочая почта существует, письмо сформировано."})


class PasswordResetConfirmView(GenericAPIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)
    serializer_class = PasswordResetConfirmSerializer

    @extend_schema(
        responses={200: detail_response, 400: OpenApiTypes.OBJECT, 404: detail_response}
    )
    def post(self, request):
        if not settings.STAFF_PASSWORD_RESET_ENABLED:
            raise NotFound()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"detail": "Пароль изменён."})
