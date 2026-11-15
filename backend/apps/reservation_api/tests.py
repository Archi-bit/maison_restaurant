from datetime import time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.reservations.models import Reservation, ReservationHistory, RestaurantTable
from apps.reservations.services import ReservationBusinessError
from apps.staff.models import EmployeeProfile


@override_settings(ROOT_URLCONF="apps.reservation_api.urls")
class ReservationApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = cls.create_employee("owner", "owner")
        cls.waiter = cls.create_employee("waiter", "waiter")
        cls.other_waiter = cls.create_employee("other-waiter", "waiter")
        cls.chef = cls.create_employee("chef", "chef")
        cls.table = RestaurantTable.objects.create(
            code="T01", capacity=4, zone="Основной зал"
        )

    @classmethod
    def create_employee(cls, username, role):
        user = get_user_model().objects.create_user(username=username)
        return EmployeeProfile.objects.create(
            user=user,
            work_email=f"{username}@example.com",
            full_name=username,
            role=role,
        )

    def create_reservation(self, *, waiter=None, name="Гость", status="pending"):
        return Reservation.objects.create(
            guest_name=name,
            phone="+996555010027",
            date=timezone.localdate() + timedelta(days=1),
            start_time=time(20, 0),
            end_time=time(22, 0),
            guests_count=2,
            status=status,
            source="phone",
            table=self.table,
            responsible_employee=waiter,
            created_by=self.owner,
        )

    def test_public_post_creates_pending_reservation_and_rejects_extra_fields(self):
        response = self.client.post(
            "/reservations/",
            {
                "guest_name": "Тимур Беков",
                "phone": "+996555010027",
                "date": (timezone.localdate() + timedelta(days=1)).isoformat(),
                "start_time": "20:30",
                "guests_count": 2,
                "guest_note": "Тихий стол",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        reservation = Reservation.objects.get(pk=response.data["id"])
        self.assertEqual(reservation.status, "pending")
        self.assertEqual(reservation.source, "website")
        self.assertIsNone(reservation.table_id)
        self.assertIsNone(reservation.responsible_employee_id)
        self.assertEqual(response.data["reservation_number"], reservation.number)
        self.assertEqual(ReservationHistory.objects.filter(reservation=reservation).count(), 1)

        invalid_response = self.client.post(
            "/reservations/",
            {
                "guest_name": "Гость",
                "phone": "+996555010028",
                "date": (timezone.localdate() + timedelta(days=1)).isoformat(),
                "start_time": "20:30",
                "guests_count": 2,
                "status": "confirmed",
            },
            format="json",
        )
        self.assertEqual(invalid_response.status_code, 400)
        self.assertFalse(Reservation.objects.filter(phone="+996555010028").exists())

    def test_public_get_and_invalid_staff_auth_are_not_available(self):
        self.assertEqual(self.client.get("/reservations/").status_code, 405)
        self.assertEqual(self.client.get("/staff/reservations/").status_code, 401)
        self.client.credentials(HTTP_AUTHORIZATION="Bearer invalid")
        self.assertEqual(self.client.get("/staff/reservations/").status_code, 401)

    def test_staff_create_uses_employee_profile_and_domain_service(self):
        self.client.force_authenticate(user=self.owner.user)
        response = self.client.post(
            "/staff/reservations/",
            {
                "guest_name": "Телефонная бронь",
                "phone": "+996555010031",
                "date": (timezone.localdate() + timedelta(days=1)).isoformat(),
                "start_time": "20:30",
                "guests_count": 2,
                "source": "phone",
                "duration_minutes": 120,
                "table_id": self.table.pk,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        reservation = Reservation.objects.get(pk=response.data["id"])
        self.assertEqual(reservation.status, "pending")
        self.assertEqual(reservation.source, "phone")
        self.assertEqual(reservation.created_by, self.owner)
        self.assertEqual(reservation.responsible_employee, self.owner)
        self.assertEqual(reservation.table, self.table)

        invalid_response = self.client.post(
            "/staff/reservations/",
            {
                "guest_name": "Не должно создаться",
                "phone": "+996555010032",
                "date": (timezone.localdate() + timedelta(days=1)).isoformat(),
                "start_time": "20:30",
                "guests_count": 2,
                "responsible_employee": self.waiter.pk,
            },
            format="json",
        )
        self.assertEqual(invalid_response.status_code, 400)
        self.assertFalse(Reservation.objects.filter(phone="+996555010032").exists())

    def test_waiter_sees_only_assigned_reservations_and_cannot_write(self):
        own = self.create_reservation(waiter=self.waiter, name="Своя бронь")
        other = self.create_reservation(
            waiter=self.other_waiter, name="Чужая бронь"
        )
        self.client.force_authenticate(user=self.waiter.user)

        response = self.client.get("/staff/reservations/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], own.pk)
        self.assertEqual(
            response.data["results"][0]["date"],
            (timezone.localdate() + timedelta(days=1)).isoformat(),
        )
        self.assertEqual(response.data["results"][0]["start_time"], "20:00")
        self.assertEqual(response.data["results"][0]["end_time"], "22:00")
        self.assertNotContains(response, "Чужая бронь")

        self.assertEqual(
            self.client.get(f"/staff/reservations/{other.pk}/").status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                f"/staff/reservations/{other.pk}/history/"
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.patch(
                f"/staff/reservations/{own.pk}/",
                {"guest_name": "Изменено"},
                format="json",
            ).status_code,
            403,
        )

    def test_chef_is_forbidden_and_owner_can_run_reservation_actions(self):
        reservation = self.create_reservation()
        self.client.force_authenticate(user=self.chef.user)
        self.assertEqual(self.client.get("/staff/reservations/").status_code, 403)

        self.client.force_authenticate(user=self.owner.user)
        invalid_patch = self.client.patch(
            f"/staff/reservations/{reservation.pk}/",
            {"status": "arrived"},
            format="json",
        )
        self.assertEqual(invalid_patch.status_code, 400)
        update_response = self.client.patch(
            f"/staff/reservations/{reservation.pk}/",
            {"guest_name": "Имя обновлено"},
            format="json",
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.data["guest_name"], "Имя обновлено")

        missing_table_reservation = self.create_reservation(waiter=self.waiter)
        missing_table_reservation.table = None
        missing_table_reservation.save(update_fields=["table"])
        error_response = self.client.post(
            f"/staff/reservations/{missing_table_reservation.pk}/confirm/",
            {},
            format="json",
        )
        self.assertEqual(error_response.status_code, 400)
        self.assertEqual(error_response.data["code"], "table_required")

        assign_response = self.client.post(
            f"/staff/reservations/{reservation.pk}/assign-table/",
            {"table_id": self.table.pk},
            format="json",
        )
        self.assertEqual(assign_response.status_code, 200)
        self.assertEqual(assign_response.data["table"]["id"], self.table.pk)

        confirm_response = self.client.post(
            f"/staff/reservations/{reservation.pk}/confirm/",
            {},
            format="json",
        )
        self.assertEqual(confirm_response.status_code, 200)
        self.assertEqual(confirm_response.data["status"], "confirmed")

        arrive_response = self.client.post(
            f"/staff/reservations/{reservation.pk}/arrive/",
            {},
            format="json",
        )
        self.assertEqual(arrive_response.status_code, 200)
        self.assertEqual(arrive_response.data["status"], "arrived")
        history_response = self.client.get(
            f"/staff/reservations/{reservation.pk}/history/"
        )
        self.assertEqual(history_response.status_code, 200)
        self.assertEqual(history_response.data[-1]["new_status"], "arrived")

        pending = self.create_reservation(waiter=self.waiter)
        cancel_response = self.client.post(
            f"/staff/reservations/{pending.pk}/cancel/",
            {},
            format="json",
        )
        self.assertEqual(cancel_response.status_code, 200)
        self.assertEqual(cancel_response.data["status"], "cancelled")

    def test_hall_plan_never_returns_another_waiters_guest_details(self):
        self.client.force_authenticate(user=self.waiter.user)
        plan = {
            "date": "2026-11-15",
            "time": "20:00:00",
            "duration_minutes": 120,
            "tables": [
                {
                    "id": 1,
                    "code": "T01",
                    "capacity": 4,
                    "zone": "Основной зал",
                    "is_active": True,
                    "status": "reserved",
                    "reservations": [
                        {
                            "guest_name": "Чужой гость",
                            "phone": "+996555010000",
                            "guest_note": "секретная заметка",
                            "responsible_employee_id": self.other_waiter.pk,
                        }
                    ],
                },
                {
                    "id": 2,
                    "code": "T02",
                    "capacity": 4,
                    "zone": "Основной зал",
                    "is_active": False,
                    "status": "free",
                    "reservations": [
                        {
                            "reservation_number": "B-002",
                            "guest_name": "Своя бронь",
                            "guests_count": 2,
                            "start_time": "20:00",
                            "end_time": "22:00",
                            "responsible_employee_id": self.waiter.pk,
                            "phone": "+996555010001",
                            "guest_note": "не возвращать",
                        }
                    ],
                },
            ],
        }
        with patch("apps.reservation_api.views.get_hall_plan", return_value=plan):
            response = self.client.get("/staff/tables/")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["tables"][0]["reservation"])
        self.assertEqual(
            response.data["tables"][1]["reservation"]["guest_name"],
            "Своя бронь",
        )
        self.assertFalse(response.data["tables"][1]["is_active"])
        self.assertNotContains(response, "Чужой гость")
        self.assertNotContains(response, "+996555010000")
        self.assertNotContains(response, "секретная заметка")
        self.assertNotContains(response, "+996555010001")
        self.assertNotContains(response, "не возвращать")

    def test_hall_plan_validates_duration_and_business_errors_are_client_errors(self):
        self.client.force_authenticate(user=self.owner.user)
        invalid_response = self.client.get(
            "/staff/tables/", {"duration_minutes": 45}
        )
        self.assertEqual(invalid_response.status_code, 400)

        with patch(
            "apps.reservation_api.views.get_hall_plan",
            side_effect=ReservationBusinessError(
                "invalid_duration", "Неверная длительность."
            ),
        ):
            error_response = self.client.get("/staff/tables/")
        self.assertEqual(error_response.status_code, 400)
        self.assertEqual(error_response.data["code"], "invalid_duration")
