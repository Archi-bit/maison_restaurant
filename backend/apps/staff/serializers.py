from urllib.parse import urlencode
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import EmailMessage
from django.db import transaction
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.settings import api_settings

from .models import EmployeeProfile
from .tokens import RememberedStaffRefreshToken, StaffRefreshToken



class EmployeeProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeProfile
        fields = ("id", "full_name", "work_email", "role", "phone")
        read_only_fields = fields


class LoginSerializer(serializers.Serializer):
    work_email = serializers.EmailField(max_length=254, write_only=True)
    password = serializers.CharField(
        write_only=True, trim_whitespace=False, style={"input_type": "password"}
    )
    remember_me = serializers.BooleanField(default=False, write_only=True)
    profile = EmployeeProfileSerializer(read_only=True)
    access = serializers.CharField(read_only=True)
    refresh = serializers.CharField(read_only=True)

    def validate(self, attrs):
        employee = EmployeeProfile.objects.select_related("user").filter(
            work_email=attrs["work_email"]
        ).first()

        if employee is None:
            get_user_model()().set_password(attrs["password"])
        else:
            user = employee.user
            if user.check_password(attrs["password"]) and user.is_active:
                token_class = (
                    RememberedStaffRefreshToken
                    if attrs["remember_me"]
                    else StaffRefreshToken
                )
                refresh = token_class.for_user(user)
                return {
                    "access": str(refresh.access_token),
                    "refresh": str(refresh),
                    "profile": EmployeeProfileSerializer(employee).data,
                }

        raise AuthenticationFailed("Неверная рабочая почта или пароль.")


class RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField(write_only=True)
    access = serializers.CharField(read_only=True)

    def validate(self, attrs):
        refresh = StaffRefreshToken(attrs["refresh"])
        if not EmployeeProfile.objects.filter(
            user_id=refresh.get(api_settings.USER_ID_CLAIM), user__is_active=True
        ).exists():
            raise AuthenticationFailed("Учётная запись сотрудника недоступна.")
        return {"access": str(refresh.access_token)}


class PasswordResetSerializer(serializers.Serializer):
    work_email = serializers.EmailField(max_length=254)

    def save(self):
        employee = EmployeeProfile.objects.select_related("user").filter(
            work_email=self.validated_data["work_email"], user__is_active=True
        ).first()
        if employee is None:
            return

        uid = urlsafe_base64_encode(force_bytes(employee.user_id))
        token = default_token_generator.make_token(employee.user)
        query = urlencode({"uid": uid, "token": token})
        link = f"{settings.STAFF_PASSWORD_RESET_URL}?{query}"
        EmailMessage(
            subject="Восстановление пароля MAISON",
            body=f"Password reset link (valid for 30 minutes):\n{link}",
            to=[employee.work_email],
        ).send(using="staff_password_reset")


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(
        write_only=True, trim_whitespace=False, style={"input_type": "password"}
    )
    new_password_confirm = serializers.CharField(
        write_only=True, trim_whitespace=False, style={"input_type": "password"}
    )

    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError(
                {"new_password_confirm": "Пароли не совпадают."}
            )
        return attrs

    @transaction.atomic
    def save(self):
        user_model = get_user_model()
        invalid_link = serializers.ValidationError(
            {"token": "Ссылка для сброса недействительна или просрочена."}
        )
        try:
            user_id = user_model._meta.pk.to_python(
                urlsafe_base64_decode(self.validated_data["uid"]).decode()
            )
            user = user_model.objects.select_for_update(of=("self",)).get(
                pk=user_id, is_active=True, employee_profile__isnull=False
            )
        except (ValueError, OverflowError, UnicodeDecodeError, DjangoValidationError, user_model.DoesNotExist):
            raise invalid_link from None

        if not default_token_generator.check_token(user, self.validated_data["token"]):
            raise invalid_link

        new_password = self.validated_data["new_password"]
        try:
            validate_password(new_password, user)
        except DjangoValidationError as error:
            raise serializers.ValidationError({"new_password": error.messages}) from error

        user.set_password(new_password)
        user.save(update_fields=["password"])
