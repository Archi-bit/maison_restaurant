"""Создание, редактирование и смена статусов броней. Каждое ключевое изменение пишется в историю."""
from datetime import datetime

from django.db import transaction

from ..models import Reservation, ReservationHistory
from .availability import (
    DEFAULT_DURATION_MINUTES,
    ReservationBusinessError,
    add_history,
    calc_end_time,
    ensure_table_available,
    lock_table,
    validate_visit_window,
)

Status = Reservation.Status
Source = Reservation.Source
Action = ReservationHistory.Action

REQUIRED_FIELDS = ("guest_name", "phone", "date", "start_time", "guests_count")
EDITABLE_FIELDS = {
    "guest_name",
    "phone",
    "guest_note",
    "date",
    "start_time",
    "end_time",
    "guests_count",
    "table",
    "responsible_employee",
}
EDITABLE_STATUSES = (Status.PENDING, Status.CONFIRMED)


def _require(data, fields):
    missing = [f for f in fields if data.get(f) in (None, "")]
    if missing:
        raise ReservationBusinessError(
            "missing_fields", f"Не заполнены обязательные поля: {', '.join(missing)}"
        )


# ---------- создание ----------

@transaction.atomic
def create_public_reservation(*, validated_data):
    """Заявка с сайта: 120 минут, pending, website, без стола и сотрудников."""
    _require(validated_data, REQUIRED_FIELDS)

    date = validated_data["date"]
    start_time = validated_data["start_time"]
    guests_count = validated_data["guests_count"]
    end_time = calc_end_time(start_time, DEFAULT_DURATION_MINUTES)

    validate_visit_window(
        date=date, start_time=start_time, end_time=end_time, guests_count=guests_count
    )

    reservation = Reservation.objects.create(
        guest_name=validated_data["guest_name"],
        phone=validated_data["phone"],
        guest_note=validated_data.get("guest_note") or "",
        date=date,
        start_time=start_time,
        end_time=end_time,
        guests_count=guests_count,
        status=Status.PENDING,
        source=Source.WEBSITE,
        table=None,
        created_by=None,
        responsible_employee=None,
    )
    add_history(
        reservation, None, Action.CREATED, new_status=Status.PENDING,
        details="Публичная заявка с сайта",
    )
    return reservation


@transaction.atomic
def create_staff_reservation(*, validated_data, actor):
    """Бронь от сотрудника: phone или walk_in. Статус сначала pending."""
    _require(validated_data, REQUIRED_FIELDS + ("source",))

    source = validated_data["source"]
    if source not in (Source.PHONE, Source.WALK_IN):
        raise ReservationBusinessError(
            "invalid_source", "Сотрудник может создавать только брони phone или walk_in"
        )

    date = validated_data["date"]
    start_time = validated_data["start_time"]
    guests_count = validated_data["guests_count"]
    end_time = validated_data.get("end_time") or calc_end_time(
        start_time, validated_data.get("duration_minutes") or DEFAULT_DURATION_MINUTES
    )

    # walk_in — гость уже пришёл, его время начала может быть «прямо сейчас»,
    # поэтому проверку «в будущем» для него пропускаем (согласовать с Team Lead).
    validate_visit_window(
        date=date,
        start_time=start_time,
        end_time=end_time,
        guests_count=guests_count,
        check_future=(source != Source.WALK_IN),
    )

    table = validated_data.get("table")
    if table is not None:
        table = lock_table(table)
        ensure_table_available(
            table=table, date=date, start_time=start_time,
            end_time=end_time, guests_count=guests_count,
        )

    reservation = Reservation.objects.create(
        guest_name=validated_data["guest_name"],
        phone=validated_data["phone"],
        guest_note=validated_data.get("guest_note") or "",
        date=date,
        start_time=start_time,
        end_time=end_time,
        guests_count=guests_count,
        status=Status.PENDING,
        source=source,
        table=table,
        created_by=actor,
        responsible_employee=validated_data.get("responsible_employee") or actor,
    )
    add_history(
        reservation, actor, Action.CREATED, new_status=Status.PENDING,
        details=f"Создана сотрудником, источник: {source}",
    )
    if table is not None:
        add_history(
            reservation, actor, Action.TABLE_ASSIGNED, details=f"Назначен стол {table.code}"
        )
    return reservation


# ---------- редактирование ----------

@transaction.atomic
def update_reservation(*, reservation, validated_data, actor):
    """Меняет только разрешённые поля. Статус через обычное редактирование менять нельзя."""
    data = dict(validated_data)

    if "status" in data:
        raise ReservationBusinessError(
            "status_change_forbidden",
            "Статус меняется только через confirm / arrived / cancel",
        )
    unknown = set(data) - EDITABLE_FIELDS
    if unknown:
        raise ReservationBusinessError(
            "field_not_allowed", f"Эти поля менять нельзя: {', '.join(sorted(unknown))}"
        )

    reservation = Reservation.objects.select_for_update().get(pk=reservation.pk)
    if reservation.status not in EDITABLE_STATUSES:
        raise ReservationBusinessError(
            "reservation_not_editable",
            "Бронь в статусе arrived или cancelled изменять нельзя",
        )

    new_date = data.get("date", reservation.date)
    new_start = data.get("start_time", reservation.start_time)
    if "end_time" in data:
        new_end = data["end_time"]
    elif "start_time" in data or "date" in data:
        # длительность сохраняем прежней
        old_duration = datetime.combine(reservation.date, reservation.end_time) - datetime.combine(
            reservation.date, reservation.start_time
        )
        end_dt = datetime.combine(new_date, new_start) + old_duration
        if end_dt.date() != new_date:
            raise ReservationBusinessError(
                "outside_working_hours", "Посещение должно закончиться не позже 23:00"
            )
        new_end = end_dt.time()
    else:
        new_end = reservation.end_time

    new_guests = data.get("guests_count", reservation.guests_count)
    new_table = data["table"] if "table" in data else reservation.table
    new_table_id = new_table.pk if new_table is not None else None

    time_changed = (new_date, new_start, new_end) != (
        reservation.date, reservation.start_time, reservation.end_time,
    )
    guests_changed = new_guests != reservation.guests_count
    table_changed = new_table_id != reservation.table_id

    validate_visit_window(
        date=new_date, start_time=new_start, end_time=new_end,
        guests_count=new_guests, check_future=time_changed,
    )

    old_table_code = reservation.table.code if reservation.table_id else None
    if new_table is not None and (time_changed or guests_changed or table_changed):
        new_table = lock_table(new_table)
        ensure_table_available(
            table=new_table, date=new_date, start_time=new_start, end_time=new_end,
            guests_count=new_guests, exclude_reservation_id=reservation.pk,
        )

    changed = []
    for field in ("guest_name", "phone", "guest_note", "guests_count", "responsible_employee"):
        if field in data and getattr(reservation, field) != data[field]:
            setattr(reservation, field, data[field])
            changed.append(field)
    for field, value in (("date", new_date), ("start_time", new_start), ("end_time", new_end)):
        if getattr(reservation, field) != value:
            setattr(reservation, field, value)
            changed.append(field)
    if table_changed:
        reservation.table = new_table

    reservation.save()

    if changed:
        add_history(
            reservation, actor, Action.UPDATED,
            old_status=reservation.status, new_status=reservation.status,
            details=f"Изменены поля: {', '.join(changed)}",
        )
    if table_changed:
        add_history(
            reservation, actor, Action.TABLE_ASSIGNED,
            details=f"Стол: {old_table_code or '—'} → {new_table.code if new_table else '—'}",
        )
    return reservation


# ---------- смена статусов ----------

def _change_status(*, reservation, actor, allowed_from, new_status, action, details=""):
    with transaction.atomic():
        reservation = Reservation.objects.select_for_update().get(pk=reservation.pk)
        if reservation.status not in allowed_from:
            raise ReservationBusinessError(
                "invalid_transition",
                f"Нельзя перевести бронь из «{reservation.status}» в «{new_status}»",
            )
        old_status = reservation.status
        reservation.status = new_status
        reservation.save(update_fields=["status", "updated_at"])
        add_history(
            reservation, actor, action,
            old_status=old_status, new_status=new_status, details=details,
        )
    return reservation


def confirm_reservation(*, reservation, actor):
    return _change_status(
        reservation=reservation, actor=actor,
        allowed_from=(Status.PENDING,), new_status=Status.CONFIRMED, action=Action.CONFIRMED,
    )


def mark_arrived(*, reservation, actor):
    return _change_status(
        reservation=reservation, actor=actor,
        allowed_from=(Status.CONFIRMED,), new_status=Status.ARRIVED, action=Action.ARRIVED,
    )


def cancel_reservation(*, reservation, actor):
    return _change_status(
        reservation=reservation, actor=actor,
        allowed_from=(Status.PENDING, Status.CONFIRMED),
        new_status=Status.CANCELLED, action=Action.CANCELLED,
    )
