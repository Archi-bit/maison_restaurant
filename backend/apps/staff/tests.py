from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Permission
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from .models import EmployeeProfile
from .permissions import HasEmployeeProfile, IsAssignedWaiter, IsOwnerOrAdministrator



PASSWORD = "Local-staff-test-84!"
NEW_PASSWORD = "New-local-password-75!"


def create_employee(role):
    user = get_user_model().objects.create_user(username=role, password=PASSWORD)
    return EmployeeProfile.objects.create(
        user=user, work_email=f"{role}@example.com", full_name="Сотрудник", role=role
    )


class EmployeeProfileTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = create_employee(EmployeeProfile.Role.OWNER)

    def test_profile_uses_standard_user_and_unique_work_email(self):
        self.assertEqual(self.owner.user.employee_profile, self.owner)
        self.assertEqual(str(self.owner), self.owner.full_name)
        another_user = get_user_model().objects.create_user(username="another")
        with self.assertRaises(IntegrityError), transaction.atomic():
            EmployeeProfile.objects.create(
                user=another_user,
                work_email=self.owner.work_email,
                full_name="Другой сотрудник",
                role=EmployeeProfile.Role.WAITER,
            )

    def test_employee_admin_requires_owner_role_and_django_permissions(self):
        profile_admin = admin.site.get_model_admin(EmployeeProfile)
        request = RequestFactory().get("/admin/staff/employeeprofile/")
        request.user = self.owner.user
        self.assertFalse(profile_admin.has_change_permission(request))

        change_permission = Permission.objects.get(
            content_type__app_label="staff", codename="change_employeeprofile"
        )
        request.user.user_permissions.add(change_permission)
        request.user = get_user_model().objects.get(pk=request.user.pk)
        self.assertTrue(profile_admin.has_change_permission(request))
        self.assertFalse(profile_admin.has_delete_permission(request))

        administrator = create_employee(EmployeeProfile.Role.ADMINISTRATOR)
        administrator.user.user_permissions.add(change_permission)
        request.user = administrator.user
        self.assertFalse(profile_admin.has_module_permission(request))
        self.assertFalse(profile_admin.has_view_permission(request))
        self.assertFalse(profile_admin.has_add_permission(request))
        self.assertFalse(profile_admin.has_change_permission(request))
        self.assertFalse(profile_admin.has_delete_permission(request))


class StaffPermissionsTests(TestCase):
    def test_role_matrix(self):
        for role in EmployeeProfile.Role:
            with self.subTest(role=role):
                employee = create_employee(role)
                request = SimpleNamespace(user=employee.user, method="GET")
                self.assertTrue(HasEmployeeProfile().has_permission(request, None))
                self.assertEqual(
                    IsOwnerOrAdministrator().has_permission(request, None),
                    role in (EmployeeProfile.Role.OWNER, EmployeeProfile.Role.ADMINISTRATOR),
                )
                self.assertEqual(
                    IsAssignedWaiter().has_permission(request, None),
                    role == EmployeeProfile.Role.WAITER,
                )

    def test_waiter_reads_only_assigned_reservations(self):
        waiter = create_employee(EmployeeProfile.Role.WAITER)
        request = SimpleNamespace(user=waiter.user, method="GET")
        own_reservation = SimpleNamespace(responsible_employee_id=waiter.pk)
        permission = IsAssignedWaiter()
        self.assertTrue(permission.has_object_permission(request, None, own_reservation))
        for employee_id in (None, waiter.pk + 1):
            other_reservation = SimpleNamespace(responsible_employee_id=employee_id)
            self.assertFalse(permission.has_object_permission(request, None, other_reservation))

        request.method = "PATCH"
        self.assertFalse(permission.has_object_permission(request, None, own_reservation))

    def test_permissions_require_an_active_user_with_a_profile(self):
        user_without_profile = get_user_model().objects.create_user(username="guest")
        inactive_owner = create_employee(EmployeeProfile.Role.OWNER)
        inactive_waiter = create_employee(EmployeeProfile.Role.WAITER)
        inactive_owner.user.is_active = False
        inactive_waiter.user.is_active = False
        for user in (AnonymousUser(), user_without_profile, inactive_owner.user, inactive_waiter.user):
            with self.subTest(user=user):
                request = SimpleNamespace(user=user, method="GET")
                for permission in (HasEmployeeProfile, IsOwnerOrAdministrator, IsAssignedWaiter):
                    self.assertFalse(permission().has_permission(request, None))


class StaffAuthTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.employee = create_employee(EmployeeProfile.Role.OWNER)

    def login(self, **fields):
        return self.client.post(
            reverse("staff:login"),
            {"work_email": self.employee.work_email, "password": PASSWORD, **fields},
            format="json",
        )

    def test_all_roles_can_log_in_and_read_their_profile(self):
        self.assertEqual(self.client.get(reverse("staff:me")).status_code, 401)
        for role in EmployeeProfile.Role:
            with self.subTest(role=role):
                employee = self.employee if role == self.employee.role else create_employee(role)
                login = self.login(work_email=employee.work_email)
                self.assertEqual(login.status_code, 200)
                self.assertEqual(set(login.data), {"access", "refresh", "profile"})
                self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
                me = self.client.get(reverse("staff:me"))
                self.assertEqual(me.status_code, 200)
                self.assertEqual(me.data, login.data["profile"])
                self.assertEqual(
                    me.data,
                    {
                        "id": employee.pk,
                        "full_name": employee.full_name,
                        "work_email": employee.work_email,
                        "role": role,
                        "phone": "",
                    },
                )
        self.assertEqual(self.client.post("/api/v1/staff/auth/register/").status_code, 404)

    def test_invalid_credentials_and_disabled_staff_get_the_same_response(self):
        inactive = create_employee(EmployeeProfile.Role.CHEF)
        inactive.user.is_active = False
        inactive.user.save(update_fields=["is_active"])
        get_user_model().objects.create_user(
            username="guest", email="guest@example.com", password=PASSWORD
        )

        wrong_password = self.login(password="Wrong password")
        self.assertEqual(wrong_password.status_code, 401)
        for email in (inactive.work_email, "unknown@example.com", "guest@example.com"):
            with self.subTest(email=email):
                failure = self.login(work_email=email)
                self.assertEqual(failure.status_code, 401)
                self.assertEqual(failure.data, wrong_password.data)

    def test_refresh_lifetimes_and_logout(self):
        for fields, days in (({}, 3), ({"remember_me": True}, 30)):
            with self.subTest(days=days):
                login = self.login(**fields)
                self.assertEqual(login.status_code, 200)
                refresh = RefreshToken(login.data["refresh"])
                self.assertEqual(refresh["exp"] - refresh["iat"], days * 86400)
                self.assertEqual(OutstandingToken.objects.get(jti=refresh["jti"]).token, str(refresh))

                near_expiry = datetime.fromtimestamp(refresh["exp"] - 60, tz=timezone.now().tzinfo)
                with patch("rest_framework_simplejwt.tokens.aware_utcnow", return_value=near_expiry):
                    renewed = self.client.post(
                        reverse("staff:refresh"), {"refresh": str(refresh)}, format="json"
                    )
                self.assertEqual(renewed.status_code, 200)
                self.assertEqual(set(renewed.data), {"access"})
                access = AccessToken(renewed.data["access"], verify=False)
                self.assertEqual(access["exp"], refresh["exp"])
                self.assertEqual(access["exp"] - access["iat"], 60)

                with patch(
                    "rest_framework_simplejwt.tokens.aware_utcnow",
                    return_value=near_expiry + timedelta(seconds=60),
                ):
                    self.assertEqual(self.client.post(
                        reverse("staff:refresh"), {"refresh": str(refresh)}
                    ).status_code, 401)

                self.assertEqual(self.client.post(
                    reverse("staff:logout"), {"refresh": str(refresh)}
                ).status_code, 200)
                self.assertEqual(self.client.post(
                    reverse("staff:refresh"), {"refresh": str(refresh)}
                ).status_code, 401)

    def test_access_is_short_and_refresh_checks_current_employee_status(self):
        login = self.login()
        access = AccessToken(login.data["access"])
        self.assertEqual(access["exp"] - access["iat"], 900)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

        self.employee.user.is_active = False
        self.employee.user.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(reverse("staff:me")).status_code, 401)
        self.assertEqual(self.client.post(
            reverse("staff:refresh"), {"refresh": login.data["refresh"]}
        ).status_code, 401)

        self.employee.user.is_active = True
        self.employee.user.save(update_fields=["is_active"])
        self.employee.delete()
        self.assertEqual(self.client.get(reverse("staff:me")).status_code, 403)
        self.assertEqual(self.client.post(
            reverse("staff:refresh"), {"refresh": login.data["refresh"]}
        ).status_code, 401)


@override_settings(STAFF_PASSWORD_RESET_ENABLED=True)
class PasswordResetTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.employee = create_employee(EmployeeProfile.Role.WAITER)

    def request_reset(self, email):
        return self.client.post(reverse("staff:password-reset"), {"work_email": email})

    def confirmation_fields(self):
        self.assertEqual(self.request_reset(self.employee.work_email).status_code, 200)
        url = mail.outbox[-1].body.splitlines()[-1]
        query = parse_qs(urlsplit(url).query)
        return {
            "uid": query["uid"][0],
            "token": query["token"][0],
            "new_password": NEW_PASSWORD,
            "new_password_confirm": NEW_PASSWORD,
        }

    def confirm(self, fields):
        return self.client.post(reverse("staff:password-reset-confirm"), fields)

    def test_reset_does_not_disclose_accounts_and_sends_to_work_email(self):
        existing = self.request_reset(self.employee.work_email)
        missing = self.request_reset("unknown@example.com")
        self.assertEqual(existing.status_code, 200)
        self.assertEqual(missing.status_code, 200)
        self.assertEqual(existing.data, missing.data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.employee.work_email])

    def test_password_reset_rejects_invalid_weak_and_expired_requests(self):
        now = datetime(2026, 11, 11, 12)
        with patch.object(default_token_generator, "_now", return_value=now):
            fields = self.confirmation_fields()
            for invalid in (
                {"uid": "!"},
                {"token": "invalid"},
                {"new_password_confirm": "different"},
                {"new_password": "123", "new_password_confirm": "123"},
            ):
                with self.subTest(invalid=invalid):
                    self.assertEqual(self.confirm({**fields, **invalid}).status_code, 400)

        with patch.object(
            default_token_generator, "_now", return_value=now + timedelta(seconds=1801)
        ):
            self.assertEqual(self.confirm(fields).status_code, 400)
        self.employee.user.refresh_from_db()
        self.assertTrue(self.employee.user.check_password(PASSWORD))

    def test_password_reset_changes_password_and_token_is_single_use(self):
        fields = self.confirmation_fields()
        self.assertEqual(self.confirm(fields).status_code, 200)
        self.assertEqual(self.confirm(fields).status_code, 400)
        self.employee.user.refresh_from_db()
        self.assertTrue(self.employee.user.check_password(NEW_PASSWORD))
        self.assertFalse(self.employee.user.check_password(PASSWORD))

    @override_settings(STAFF_PASSWORD_RESET_ENABLED=False)
    def test_reset_is_unavailable_when_disabled(self):
        self.assertEqual(self.request_reset(self.employee.work_email).status_code, 404)
        self.assertEqual(self.confirm({}).status_code, 404)
        self.assertEqual(len(mail.outbox), 0)


class StaffIntegrationTests(APITestCase):
    @override_settings(CORS_ALLOWED_ORIGINS=["http://localhost:5173"])
    def test_local_react_origin_can_send_bearer_and_cart_headers(self):
        response = self.client.options(
            reverse("staff:me"),
            HTTP_ORIGIN="http://localhost:5173",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,x-cart-token",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Access-Control-Allow-Origin"], "http://localhost:5173")
        allowed_headers = response["Access-Control-Allow-Headers"].split(", ")
        self.assertIn("authorization", allowed_headers)
        self.assertIn("x-cart-token", allowed_headers)

    def test_swagger_and_openapi_include_staff_and_stage_one(self):
        self.assertEqual(self.client.get(reverse("swagger-ui")).status_code, 200)
        response = self.client.get(
            reverse("schema"), HTTP_ACCEPT="application/vnd.oai.openapi+json"
        )
        self.assertEqual(response.status_code, 200)
        paths = response.json()["paths"]
        for route in ("login", "refresh", "logout", "me", "password-reset", "password-reset-confirm"):
            self.assertIn(reverse(f"staff:{route}"), paths)
        for route in ("/api/v1/categories/", "/api/v1/dishes/", "/api/v1/cart/"):
            self.assertIn(route, paths)
