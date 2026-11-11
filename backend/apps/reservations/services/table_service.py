"""Назначение стола. Всё внутри transaction.atomic() + select_for_update() на столе."""
from django.db import transaction

from ..models import Reservation, ReservationHistory
from .availability import (
    ReservationBusinessError,
    add_history,
    ensure_table_available,
    lock_table,
)

ASSIGNABLE_STATUSES = (Reservation.Status.PENDING, Reservation.Status.CONFIRMED)


@transaction.atomic
def assign_table(*, reservation, table, actor):
    # Порядок блокировок всегда один: сначала бронь, потом стол (против deadlock).
    reservation = Reservation.objects.select_for_update().get(pk=reservation.pk)
    if reservation.status not in ASSIGNABLE_STATUSES:
        raise ReservationBusinessError(
            "reservation_not_editable",
            "Стол можно назначать только для pending или confirmed брони",
        )

    old_code = reservation.table.code if reservation.table_id else None
    table = lock_table(table)
    ensure_table_available(
        table=table,
        date=reservation.date,
        start_time=reservation.start_time,
        end_time=reservation.end_time,
        guests_count=reservation.guests_count,
        exclude_reservation_id=reservation.pk,
    )

    reservation.table = table
    reservation.save(update_fields=["table", "updated_at"])
    add_history(
        reservation, actor, ReservationHistory.Action.TABLE_ASSIGNED,
        details=f"Стол: {old_code or '—'} → {table.code}",
    )
    return reservation
