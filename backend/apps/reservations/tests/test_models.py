from datetime import time

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.reservations.models import Reservation, RestaurantTable
from apps.reservations.services import create_public_reservation, create_staff_reservation

from . import ActorTestCase, future_date, public_data


def make_reservation(**overrides):
    data = {
        "guest_name": "Айбек",
        "phone": "+996700123456",
        "date": future_date(),
        "start_time": time(14, 0),
        "end_time": time(16, 0),
        "guests_count": 2,
    }
    data.update(overrides)
    return Reservation.objects.create(**data)


class ModelTests(TestCase):
    def test_reservation_defaults(self):
        r = make_reservation()
        self.assertEqual(r.status, Reservation.Status.PENDING)
        self.assertEqual(r.source, Reservation.Source.WEBSITE)
        self.assertIsNone(r.table)
        self.assertIsNone(r.created_by)
        self.assertIsNone(r.responsible_employee)

    def test_number_format(self):
        r = make_reservation()
        self.assertEqual(r.number, f"B-{r.pk:03d}")

    def test_table_code_unique(self):
        RestaurantTable.objects.create(code="T01", capacity=2)
        with self.assertRaises(IntegrityError), transaction.atomic():
            RestaurantTable.objects.create(code="T01", capacity=4)

    def test_table_default_zone(self):
        t = RestaurantTable.objects.create(code="T01", capacity=2)
        self.assertEqual(t.zone, "Основной зал")
        self.assertTrue(t.is_active)

    def test_guests_count_constraint(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_reservation(guests_count=7)

    def test_end_after_start_constraint(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_reservation(start_time=time(16, 0), end_time=time(14, 0))

    def test_working_hours_constraint(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_reservation(start_time=time(11, 0), end_time=time(13, 0))
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_reservation(start_time=time(22, 0), end_time=time(23, 30))

    def test_status_and_source_constraints(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_reservation(status="done")
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_reservation(source="telegram")

    def test_duration_minutes_property(self):
        self.assertEqual(make_reservation().duration_minutes, 120)


class AdminTestCase(ActorTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin_user = get_user_model().objects.create_superuser(
            username="root", password="pass12345", email="root@example.com"
        )

    def setUp(self):
        self.client.force_login(self.admin_user)

    def form_data(self, **overrides):
        data = {
            "guest_name": "Айбек",
            "phone": "+996700123456",
            "guest_note": "",
            "date": future_date().isoformat(),
            "start_time": "14:00:00",
            "end_time": "16:00:00",
            "guests_count": 2,
            "source": "phone",
            "table": "",
            "responsible_employee": "",
        }
        data.update(overrides)
        return data


class ReservationAdminTests(AdminTestCase):
    def test_status_is_not_an_editable_field(self):
        r = create_public_reservation(validated_data=public_data())
        resp = self.client.get(reverse("admin:reservations_reservation_change", args=[r.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'name="status"')

    def test_posting_status_does_not_change_it(self):
        r = create_public_reservation(validated_data=public_data())
        data = self.form_data(guest_name="Нурлан", status="confirmed", source="phone")
        self.client.post(reverse("admin:reservations_reservation_change", args=[r.pk]), data)
        r.refresh_from_db()
        self.assertEqual(r.status, Reservation.Status.PENDING)
        self.assertEqual(r.source, Reservation.Source.WEBSITE)

    def test_conflicting_time_is_rejected(self):
        table = RestaurantTable.objects.create(code="T01", capacity=4)
        create_staff_reservation(
            validated_data=public_data(source="phone", table=table), actor=self.actor
        )
        other = create_staff_reservation(
            validated_data=public_data(source="phone", table=table, start_time=time(17, 0)),
            actor=self.actor,
        )
        data = self.form_data(
            start_time="15:00:00", end_time="17:00:00", table=str(table.pk)
        )
        resp = self.client.post(
            reverse("admin:reservations_reservation_change", args=[other.pk]), data
        )
        self.assertEqual(resp.status_code, 200)  # форма с ошибкой, без редиректа
        other.refresh_from_db()
        self.assertEqual(other.start_time, time(17, 0))

    def test_cannot_add_website_reservation(self):
        resp = self.client.post(
            reverse("admin:reservations_reservation_add"), self.form_data(source="website")
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Reservation.objects.count(), 0)

    def test_cannot_add_outside_working_hours(self):
        resp = self.client.post(
            reverse("admin:reservations_reservation_add"),
            self.form_data(start_time="10:00:00", end_time="12:00:00"),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Reservation.objects.count(), 0)

    def test_add_goes_through_service_and_writes_history(self):
        self.client.post(reverse("admin:reservations_reservation_add"), self.form_data())
        r = Reservation.objects.get()
        self.assertEqual(r.status, Reservation.Status.PENDING)
        self.assertEqual(list(r.history.values_list("action", flat=True)), ["created"])

    def test_delete_is_forbidden(self):
        r = create_public_reservation(validated_data=public_data())
        resp = self.client.post(
            reverse("admin:reservations_reservation_delete", args=[r.pk]), {"post": "yes"}
        )
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Reservation.objects.filter(pk=r.pk).exists())

    def test_status_actions_use_services_and_history(self):
        r = create_public_reservation(validated_data=public_data())
        url = reverse("admin:reservations_reservation_changelist")
        self.client.post(url, {"action": "action_confirm", "_selected_action": [r.pk]})
        r.refresh_from_db()
        self.assertEqual(r.status, Reservation.Status.CONFIRMED)
        # повторное подтверждение — недопустимый переход, статус не меняется
        self.client.post(url, {"action": "action_confirm", "_selected_action": [r.pk]})
        r.refresh_from_db()
        self.assertEqual(r.status, Reservation.Status.CONFIRMED)
        self.assertEqual(list(r.history.values_list("action", flat=True)), ["created", "confirmed"])

    def test_cancelled_reservation_is_read_only(self):
        r = create_public_reservation(validated_data=public_data())
        url = reverse("admin:reservations_reservation_changelist")
        self.client.post(url, {"action": "action_cancel", "_selected_action": [r.pk]})
        change = reverse("admin:reservations_reservation_change", args=[r.pk])
        self.client.post(change, self.form_data(guest_name="Новое имя"))
        r.refresh_from_db()
        self.assertNotEqual(r.guest_name, "Новое имя")


class TableAdminTests(AdminTestCase):
    def test_table_delete_forbidden(self):
        t = RestaurantTable.objects.create(code="T01", capacity=4)
        resp = self.client.post(
            reverse("admin:reservations_restauranttable_delete", args=[t.pk]), {"post": "yes"}
        )
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(RestaurantTable.objects.filter(pk=t.pk).exists())

    def test_cannot_deactivate_table_with_upcoming_reservation(self):
        t = RestaurantTable.objects.create(code="T01", capacity=4, sort_order=1)
        create_staff_reservation(
            validated_data=public_data(source="phone", table=t), actor=self.actor
        )
        resp = self.client.post(
            reverse("admin:reservations_restauranttable_change", args=[t.pk]),
            {"code": "T01", "capacity": 4, "zone": "Основной зал", "sort_order": 1},  # is_active снят
        )
        self.assertEqual(resp.status_code, 200)
        t.refresh_from_db()
        self.assertTrue(t.is_active)

    def test_cannot_shrink_capacity_below_existing_guests(self):
        t = RestaurantTable.objects.create(code="T01", capacity=4, sort_order=1)
        create_staff_reservation(
            validated_data=public_data(source="phone", table=t, guests_count=4), actor=self.actor
        )
        resp = self.client.post(
            reverse("admin:reservations_restauranttable_change", args=[t.pk]),
            {"code": "T01", "capacity": 2, "zone": "Основной зал", "sort_order": 1, "is_active": "on"},
        )
        self.assertEqual(resp.status_code, 200)
        t.refresh_from_db()
        self.assertEqual(t.capacity, 4)
