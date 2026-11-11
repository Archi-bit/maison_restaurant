from datetime import time, timedelta

from django.test import TestCase

from apps.reservations.models import Reservation, ReservationHistory, RestaurantTable
from apps.reservations.services import (
    ReservationBusinessError,
    cancel_reservation,
    confirm_reservation,
    create_public_reservation,
    create_staff_reservation,
    mark_arrived,
    update_reservation,
)

from . import ACTOR, future_date, public_data


class ServiceTestCase(TestCase):
    def assertCode(self, code, func, **kwargs):
        with self.assertRaises(ReservationBusinessError) as ctx:
            func(**kwargs)
        self.assertEqual(ctx.exception.code, code)

    def history_actions(self, reservation):
        return list(reservation.history.values_list("action", flat=True))


class PublicReservationTests(ServiceTestCase):
    def test_create_public_defaults(self):
        r = create_public_reservation(validated_data=public_data())
        self.assertEqual(r.status, Reservation.Status.PENDING)
        self.assertEqual(r.source, Reservation.Source.WEBSITE)
        self.assertIsNone(r.table)
        self.assertIsNone(r.created_by)
        self.assertIsNone(r.responsible_employee)
        self.assertEqual(r.end_time, time(16, 0))  # 120 минут
        self.assertEqual(self.history_actions(r), ["created"])

    def test_past_date_rejected(self):
        self.assertCode(
            "past_datetime", create_public_reservation,
            validated_data=public_data(date=future_date(-1)),
        )

    def test_before_opening_rejected(self):
        self.assertCode(
            "outside_working_hours", create_public_reservation,
            validated_data=public_data(start_time=time(11, 0)),
        )

    def test_end_after_23_rejected(self):
        self.assertCode(
            "outside_working_hours", create_public_reservation,
            validated_data=public_data(start_time=time(21, 30)),
        )

    def test_end_exactly_23_allowed(self):
        r = create_public_reservation(validated_data=public_data(start_time=time(21, 0)))
        self.assertEqual(r.end_time, time(23, 0))

    def test_guests_out_of_range(self):
        for guests in (0, 7):
            self.assertCode(
                "invalid_guests_count", create_public_reservation,
                validated_data=public_data(guests_count=guests),
            )

    def test_missing_required_field(self):
        data = public_data()
        del data["phone"]
        self.assertCode("missing_fields", create_public_reservation, validated_data=data)


class StaffReservationTests(ServiceTestCase):
    def test_create_by_phone(self):
        r = create_staff_reservation(
            validated_data=public_data(source="phone"), actor=ACTOR
        )
        self.assertEqual(r.source, Reservation.Source.PHONE)
        self.assertEqual(r.status, Reservation.Status.PENDING)
        self.assertEqual(r.created_by, ACTOR)
        self.assertEqual(r.responsible_employee, ACTOR)

    def test_website_source_rejected(self):
        self.assertCode(
            "invalid_source", create_staff_reservation,
            validated_data=public_data(source="website"), actor=ACTOR,
        )

    def test_create_with_table(self):
        table = RestaurantTable.objects.create(code="T02", capacity=4)
        r = create_staff_reservation(
            validated_data=public_data(source="phone", table=table, guests_count=3),
            actor=ACTOR,
        )
        self.assertEqual(r.table, table)
        self.assertEqual(self.history_actions(r), ["created", "table_assigned"])

    def test_create_with_too_small_table(self):
        table = RestaurantTable.objects.create(code="T01", capacity=2)
        self.assertCode(
            "table_too_small", create_staff_reservation,
            validated_data=public_data(source="phone", table=table, guests_count=4),
            actor=ACTOR,
        )


class StatusTransitionTests(ServiceTestCase):
    def setUp(self):
        self.r = create_public_reservation(validated_data=public_data())

    def test_full_happy_path_and_history(self):
        r = confirm_reservation(reservation=self.r, actor=ACTOR)
        self.assertEqual(r.status, "confirmed")
        r = mark_arrived(reservation=r, actor=ACTOR)
        self.assertEqual(r.status, "arrived")
        self.assertEqual(self.history_actions(r), ["created", "confirmed", "arrived"])

    def test_cancel_from_pending_and_confirmed(self):
        r = cancel_reservation(reservation=self.r, actor=ACTOR)
        self.assertEqual(r.status, "cancelled")
        other = create_public_reservation(validated_data=public_data())
        other = confirm_reservation(reservation=other, actor=ACTOR)
        other = cancel_reservation(reservation=other, actor=ACTOR)
        self.assertEqual(other.status, "cancelled")
        self.assertIn("cancelled", self.history_actions(other))

    def test_pending_cannot_arrive(self):
        self.assertCode("invalid_transition", mark_arrived, reservation=self.r, actor=ACTOR)

    def test_cancelled_is_final(self):
        r = cancel_reservation(reservation=self.r, actor=ACTOR)
        self.assertCode("invalid_transition", confirm_reservation, reservation=r, actor=ACTOR)
        self.assertCode("invalid_transition", mark_arrived, reservation=r, actor=ACTOR)

    def test_arrived_is_final(self):
        r = confirm_reservation(reservation=self.r, actor=ACTOR)
        r = mark_arrived(reservation=r, actor=ACTOR)
        self.assertCode("invalid_transition", cancel_reservation, reservation=r, actor=ACTOR)


class UpdateReservationTests(ServiceTestCase):
    def setUp(self):
        self.r = create_public_reservation(validated_data=public_data())

    def test_update_allowed_field_writes_history(self):
        r = update_reservation(
            reservation=self.r, validated_data={"guest_name": "Нурлан"}, actor=ACTOR
        )
        self.assertEqual(r.guest_name, "Нурлан")
        self.assertEqual(self.history_actions(r), ["created", "updated"])

    def test_status_change_forbidden(self):
        self.assertCode(
            "status_change_forbidden", update_reservation,
            reservation=self.r, validated_data={"status": "confirmed"}, actor=ACTOR,
        )

    def test_unknown_field_forbidden(self):
        self.assertCode(
            "field_not_allowed", update_reservation,
            reservation=self.r, validated_data={"source": "phone"}, actor=ACTOR,
        )

    def test_cancelled_not_editable(self):
        r = cancel_reservation(reservation=self.r, actor=ACTOR)
        self.assertCode(
            "reservation_not_editable", update_reservation,
            reservation=r, validated_data={"guest_name": "X"}, actor=ACTOR,
        )

    def test_move_time_keeps_duration(self):
        r = update_reservation(
            reservation=self.r, validated_data={"start_time": time(18, 0)}, actor=ACTOR
        )
        self.assertEqual((r.start_time, r.end_time), (time(18, 0), time(20, 0)))

    def test_move_to_past_rejected(self):
        self.assertCode(
            "past_datetime", update_reservation,
            reservation=self.r, validated_data={"date": future_date(-1)}, actor=ACTOR,
        )

    def test_more_guests_rechecks_table_capacity(self):
        table = RestaurantTable.objects.create(code="T01", capacity=2)
        r = create_staff_reservation(
            validated_data=public_data(source="phone", table=table), actor=ACTOR
        )
        self.assertCode(
            "table_too_small", update_reservation,
            reservation=r, validated_data={"guests_count": 4}, actor=ACTOR,
        )

    def test_move_time_rechecks_conflicts(self):
        table = RestaurantTable.objects.create(code="T02", capacity=4)
        create_staff_reservation(
            validated_data=public_data(source="phone", table=table, start_time=time(14, 0)),
            actor=ACTOR,
        )
        r2 = create_staff_reservation(
            validated_data=public_data(source="phone", table=table, start_time=time(16, 0)),
            actor=ACTOR,
        )
        self.assertCode(
            "table_conflict", update_reservation,
            reservation=r2, validated_data={"start_time": time(15, 0)}, actor=ACTOR,
        )
