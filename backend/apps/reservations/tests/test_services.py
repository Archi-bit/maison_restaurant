from datetime import time, timedelta
from unittest import mock


from apps.reservations.models import Reservation, ReservationHistory, RestaurantTable
from apps.reservations.services import (
    ReservationBusinessError,
    cancel_reservation,
    confirm_reservation,
    create_public_reservation,
    create_staff_reservation,
    mark_arrived,
    assign_table,
    update_reservation,
)
from apps.reservations.services.availability import now_local

from . import ActorTestCase, future_date, make_actor, public_data


class ServiceTestCase(ActorTestCase):
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

    def test_blank_required_field(self):
        self.assertCode(
            "missing_fields", create_public_reservation,
            validated_data=public_data(guest_name="   "),
        )

    def test_missing_required_field(self):
        data = public_data()
        del data["phone"]
        self.assertCode("missing_fields", create_public_reservation, validated_data=data)


class StaffReservationTests(ServiceTestCase):
    def test_create_by_phone(self):
        r = create_staff_reservation(
            validated_data=public_data(source="phone"), actor=self.actor
        )
        self.assertEqual(r.source, Reservation.Source.PHONE)
        self.assertEqual(r.status, Reservation.Status.PENDING)
        self.assertEqual(r.created_by, self.actor)
        self.assertEqual(r.responsible_employee, self.actor)

    def test_website_source_rejected(self):
        self.assertCode(
            "invalid_source", create_staff_reservation,
            validated_data=public_data(source="website"), actor=self.actor,
        )

    def test_create_with_table(self):
        table = RestaurantTable.objects.create(code="T02", capacity=4)
        r = create_staff_reservation(
            validated_data=public_data(source="phone", table=table, guests_count=3),
            actor=self.actor,
        )
        self.assertEqual(r.table, table)
        self.assertEqual(self.history_actions(r), ["created", "table_assigned"])

    def test_create_with_too_small_table(self):
        table = RestaurantTable.objects.create(code="T01", capacity=2)
        self.assertCode(
            "table_too_small", create_staff_reservation,
            validated_data=public_data(source="phone", table=table, guests_count=4),
            actor=self.actor,
        )


class StatusTransitionTests(ServiceTestCase):
    def setUp(self):
        self.r = create_public_reservation(validated_data=public_data())

    def test_full_happy_path_and_history(self):
        r = confirm_reservation(reservation=self.r, actor=self.actor)
        self.assertEqual(r.status, "confirmed")
        r = mark_arrived(reservation=r, actor=self.actor)
        self.assertEqual(r.status, "arrived")
        self.assertEqual(self.history_actions(r), ["created", "confirmed", "arrived"])

    def test_cancel_from_pending_and_confirmed(self):
        r = cancel_reservation(reservation=self.r, actor=self.actor)
        self.assertEqual(r.status, "cancelled")
        other = create_public_reservation(validated_data=public_data())
        other = confirm_reservation(reservation=other, actor=self.actor)
        other = cancel_reservation(reservation=other, actor=self.actor)
        self.assertEqual(other.status, "cancelled")
        self.assertIn("cancelled", self.history_actions(other))

    def test_pending_cannot_arrive(self):
        self.assertCode("invalid_transition", mark_arrived, reservation=self.r, actor=self.actor)

    def test_cancelled_is_final(self):
        r = cancel_reservation(reservation=self.r, actor=self.actor)
        self.assertCode("invalid_transition", confirm_reservation, reservation=r, actor=self.actor)
        self.assertCode("invalid_transition", mark_arrived, reservation=r, actor=self.actor)

    def test_arrived_is_final(self):
        r = confirm_reservation(reservation=self.r, actor=self.actor)
        r = mark_arrived(reservation=r, actor=self.actor)
        self.assertCode("invalid_transition", cancel_reservation, reservation=r, actor=self.actor)


class UpdateReservationTests(ServiceTestCase):
    def setUp(self):
        self.r = create_public_reservation(validated_data=public_data())

    def test_update_allowed_field_writes_history(self):
        r = update_reservation(
            reservation=self.r, validated_data={"guest_name": "Нурлан"}, actor=self.actor
        )
        self.assertEqual(r.guest_name, "Нурлан")
        self.assertEqual(self.history_actions(r), ["created", "updated"])

    def test_status_change_forbidden(self):
        self.assertCode(
            "status_change_forbidden", update_reservation,
            reservation=self.r, validated_data={"status": "confirmed"}, actor=self.actor,
        )

    def test_unknown_field_forbidden(self):
        self.assertCode(
            "field_not_allowed", update_reservation,
            reservation=self.r, validated_data={"source": "phone"}, actor=self.actor,
        )

    def test_cancelled_not_editable(self):
        r = cancel_reservation(reservation=self.r, actor=self.actor)
        self.assertCode(
            "reservation_not_editable", update_reservation,
            reservation=r, validated_data={"guest_name": "X"}, actor=self.actor,
        )

    def test_move_time_keeps_duration(self):
        r = update_reservation(
            reservation=self.r, validated_data={"start_time": time(18, 0)}, actor=self.actor
        )
        self.assertEqual((r.start_time, r.end_time), (time(18, 0), time(20, 0)))

    def test_move_to_past_rejected(self):
        self.assertCode(
            "past_datetime", update_reservation,
            reservation=self.r, validated_data={"date": future_date(-1)}, actor=self.actor,
        )

    def test_more_guests_rechecks_table_capacity(self):
        table = RestaurantTable.objects.create(code="T01", capacity=2)
        r = create_staff_reservation(
            validated_data=public_data(source="phone", table=table), actor=self.actor
        )
        self.assertCode(
            "table_too_small", update_reservation,
            reservation=r, validated_data={"guests_count": 4}, actor=self.actor,
        )

    def test_move_time_rechecks_conflicts(self):
        table = RestaurantTable.objects.create(code="T02", capacity=4)
        create_staff_reservation(
            validated_data=public_data(source="phone", table=table, start_time=time(14, 0)),
            actor=self.actor,
        )
        r2 = create_staff_reservation(
            validated_data=public_data(source="phone", table=table, start_time=time(16, 0)),
            actor=self.actor,
        )
        self.assertCode(
            "table_conflict", update_reservation,
            reservation=r2, validated_data={"start_time": time(15, 0)}, actor=self.actor,
        )


class RealEmployeeProfileTests(ServiceTestCase):
    def test_actor_is_real_profile(self):
        self.assertIsNotNone(self.actor)
        self.assertIsNotNone(self.actor.pk)

    def test_history_stores_actor(self):
        r = create_staff_reservation(validated_data=public_data(source="phone"), actor=self.actor)
        r = confirm_reservation(reservation=r, actor=self.actor)
        self.assertEqual(
            set(ReservationHistory.objects.filter(reservation=r).values_list("actor_id", flat=True)),
            {self.actor.pk},
        )

    def test_staff_can_choose_other_responsible(self):
        other = make_actor("manager")
        r = create_staff_reservation(
            validated_data=public_data(source="phone", responsible_employee=other),
            actor=self.actor,
        )
        self.assertEqual(r.created_by, self.actor)
        self.assertEqual(r.responsible_employee, other)


class GuestIsolationTests(ServiceTestCase):
    def test_public_ignores_privileged_fields(self):
        table = RestaurantTable.objects.create(code="T01", capacity=4)
        r = create_public_reservation(
            validated_data=public_data(
                status="confirmed", source="phone", table=table,
                created_by=self.actor, responsible_employee=self.actor,
            )
        )
        self.assertEqual(r.status, Reservation.Status.PENDING)
        self.assertEqual(r.source, Reservation.Source.WEBSITE)
        self.assertIsNone(r.table)
        self.assertIsNone(r.created_by)
        self.assertIsNone(r.responsible_employee)


class TransactionTests(ServiceTestCase):
    def test_public_create_rolls_back_if_history_fails(self):
        with mock.patch(
            "apps.reservations.services.reservation_service.add_history",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                create_public_reservation(validated_data=public_data())
        self.assertEqual(Reservation.objects.count(), 0)

    def test_status_change_rolls_back_if_history_fails(self):
        r = create_public_reservation(validated_data=public_data())
        with mock.patch(
            "apps.reservations.services.reservation_service.add_history",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                confirm_reservation(reservation=r, actor=self.actor)
        r.refresh_from_db()
        self.assertEqual(r.status, Reservation.Status.PENDING)

    def test_failed_assign_keeps_old_table(self):
        t1 = RestaurantTable.objects.create(code="T01", capacity=4)
        t2 = RestaurantTable.objects.create(code="T02", capacity=4)
        r = assign_table(
            reservation=create_public_reservation(validated_data=public_data()),
            table=t1, actor=self.actor,
        )
        with mock.patch(
            "apps.reservations.services.table_service.add_history",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                assign_table(reservation=r, table=t2, actor=self.actor)
        r.refresh_from_db()
        self.assertEqual(r.table, t1)


class StaffCreateRulesTests(ServiceTestCase):
    def test_walk_in_today_in_the_past_allowed(self):
        now = now_local()
        start = max(time(12, 0), time(now.hour, 0))
        if start >= time(21, 0):
            self.skipTest("слишком поздно для проверки walk_in в рабочем окне")
        r = create_staff_reservation(
            validated_data=public_data(source="walk_in", date=now.date(), start_time=start),
            actor=self.actor,
        )
        self.assertEqual(r.source, Reservation.Source.WALK_IN)

    def test_walk_in_other_date_rejected(self):
        self.assertCode(
            "invalid_walk_in_date", create_staff_reservation,
            validated_data=public_data(source="walk_in", date=future_date(1)), actor=self.actor,
        )

    def test_phone_in_the_past_rejected(self):
        self.assertCode(
            "past_datetime", create_staff_reservation,
            validated_data=public_data(source="phone", date=future_date(-1)), actor=self.actor,
        )

    def test_duration_minutes_sets_end_time(self):
        r = create_staff_reservation(
            validated_data=public_data(source="phone", duration_minutes=90), actor=self.actor
        )
        self.assertEqual(r.end_time, time(15, 30))
        self.assertEqual(r.duration_minutes, 90)

    def test_invalid_duration_rejected(self):
        for bad in (0, -30, "90"):
            self.assertCode(
                "invalid_duration", create_staff_reservation,
                validated_data=public_data(source="phone", duration_minutes=bad), actor=self.actor,
            )

    def test_duration_mismatch_rejected(self):
        self.assertCode(
            "invalid_duration", create_staff_reservation,
            validated_data=public_data(
                source="phone", end_time=time(16, 0), duration_minutes=60
            ),
            actor=self.actor,
        )

    def test_duration_past_closing_rejected(self):
        self.assertCode(
            "outside_working_hours", create_staff_reservation,
            validated_data=public_data(source="phone", start_time=time(22, 0), duration_minutes=120),
            actor=self.actor,
        )

    def test_table_conflict_on_create(self):
        table = RestaurantTable.objects.create(code="T02", capacity=4)
        create_staff_reservation(
            validated_data=public_data(source="phone", table=table), actor=self.actor
        )
        self.assertCode(
            "table_conflict", create_staff_reservation,
            validated_data=public_data(source="phone", table=table, start_time=time(15, 0)),
            actor=self.actor,
        )


class UpdateEdgeCasesTests(ServiceTestCase):
    def setUp(self):
        self.r = create_public_reservation(validated_data=public_data())

    def test_blank_name_rejected(self):
        self.assertCode(
            "missing_fields", update_reservation,
            reservation=self.r, validated_data={"guest_name": "  "}, actor=self.actor,
        )

    def test_arrived_not_editable(self):
        r = mark_arrived(
            reservation=confirm_reservation(reservation=self.r, actor=self.actor), actor=self.actor
        )
        self.assertCode(
            "reservation_not_editable", update_reservation,
            reservation=r, validated_data={"guest_name": "X"}, actor=self.actor,
        )

    def test_noop_update_writes_no_history(self):
        update_reservation(
            reservation=self.r, validated_data={"guest_name": self.r.guest_name}, actor=self.actor
        )
        self.assertEqual(self.history_actions(self.r), ["created"])

    def test_change_table_writes_history_with_codes(self):
        t1 = RestaurantTable.objects.create(code="T01", capacity=4)
        t2 = RestaurantTable.objects.create(code="T02", capacity=4)
        assign_table(reservation=self.r, table=t1, actor=self.actor)
        update_reservation(reservation=self.r, validated_data={"table": t2}, actor=self.actor)
        last = self.r.history.last()
        self.assertEqual(last.action, "table_assigned")
        self.assertIn("T01", last.details)
        self.assertIn("T02", last.details)

    def test_cancelled_reservation_frees_slot_for_update(self):
        table = RestaurantTable.objects.create(code="T02", capacity=4)
        first = create_staff_reservation(
            validated_data=public_data(source="phone", table=table), actor=self.actor
        )
        second = create_staff_reservation(
            validated_data=public_data(source="phone", table=table, start_time=time(16, 0)),
            actor=self.actor,
        )
        cancel_reservation(reservation=first, actor=self.actor)
        r = update_reservation(
            reservation=second, validated_data={"start_time": time(15, 0)}, actor=self.actor
        )
        self.assertEqual(r.start_time, time(15, 0))
