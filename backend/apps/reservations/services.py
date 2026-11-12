from datetime import datetime, time as d_time, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from .models import Reservation, ReservationHistory, RestaurantTable

RESTAURANT_TZ = ZoneInfo("Asia/Bishkek")
DEFAULT_DURATION_MINUTES = 120
ACTIVE_STATUSES = ("pending", "confirmed", "arrived")
EDITABLE_STATUSES = ("pending", "confirmed")
REQUIRED_FIELDS = ("guest_name", "phone", "date", "start_time", "guests_count")
PUBLIC_FIELDS = set(REQUIRED_FIELDS) | {"guest_note"}
EDITABLE_FIELDS = PUBLIC_FIELDS | {"duration_minutes"}
SCHEDULE_FIELDS = {"date", "start_time", "duration_minutes"}


class ReservationBusinessError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _validate_required_fields(validated_data):
    missing = [field for field in REQUIRED_FIELDS if validated_data.get(field) in (None, "")]
    if missing:
        raise ReservationBusinessError(
            "missing_fields", f"Не заполнены обязательные поля: {', '.join(missing)}."
        )


def _validate_duration(duration_minutes):
    if (
        not isinstance(duration_minutes, int)
        or not 30 <= duration_minutes <= 360
        or duration_minutes % 30 != 0
    ):
        raise ReservationBusinessError(
            "invalid_duration", "Длительность должна быть от 30 до 360 минут с шагом 30."
        )


def _validate_guests_count(guests_count):
    if type(guests_count) is not int or not 1 <= guests_count <= 6:
        raise ReservationBusinessError(
            "invalid_guests_count", "Количество гостей должно быть от 1 до 6."
        )


def _validate_future(date_val, start_time_val, now_local):
    start_dt = datetime.combine(date_val, start_time_val, tzinfo=RESTAURANT_TZ)
    if start_dt <= now_local:
        raise ReservationBusinessError(
            "invalid_time", "Дата и время должны быть в будущем."
        )


def _visit_end_time(date_val, start_time_val, duration_minutes):
    opening_time = d_time(12)
    closing_time = d_time(23)
    if start_time_val < opening_time or start_time_val >= closing_time:
        raise ReservationBusinessError(
            "working_hours", "Ресторан работает с 12:00 до 23:00."
        )

    start_dt = datetime.combine(date_val, start_time_val)
    duration = timedelta(minutes=duration_minutes)
    if duration > datetime.combine(date_val, closing_time) - start_dt:
        raise ReservationBusinessError(
            "working_hours", "Бронирование должно завершаться не позже 23:00."
        )
    return (start_dt + duration).time()


def _overlapping_reservations(table, date_val, start_time_val, end_time_val):
    return Reservation.objects.filter(
        table=table,
        date=date_val,
        status__in=ACTIVE_STATUSES,
        start_time__lt=end_time_val,
        end_time__gt=start_time_val,
    )


def _check_table_conflict(
    table, date_val, start_time_val, end_time_val, exclude_reservation_id=None
):
    conflicts = _overlapping_reservations(table, date_val, start_time_val, end_time_val)
    if exclude_reservation_id is not None:
        conflicts = conflicts.exclude(pk=exclude_reservation_id)

    if conflicts.exists():
        raise ReservationBusinessError(
            "table_conflict", f"Стол {table.code} уже занят в выбранный интервал."
        )


def _lock_available_table(
    table_id, date_val, start_time_val, end_time_val, guests_count,
    exclude_reservation_id=None,
):
    try:
        table = RestaurantTable.objects.select_for_update().get(pk=table_id)
    except RestaurantTable.DoesNotExist:
        raise ReservationBusinessError("table_not_found", "Стол не найден.") from None

    if not table.is_active:
        raise ReservationBusinessError("table_inactive", "Стол неактивен.")
    if guests_count > table.capacity:
        raise ReservationBusinessError("table_capacity", "Превышена вместимость стола.")
    _check_table_conflict(
        table, date_val, start_time_val, end_time_val, exclude_reservation_id
    )
    return table


@transaction.atomic
def create_public_reservation(*, validated_data) -> Reservation:
    forbidden_fields = validated_data.keys() - PUBLIC_FIELDS
    if forbidden_fields:
        raise ReservationBusinessError(
            "field_not_allowed",
            f"Недопустимые поля публичной заявки: {', '.join(sorted(forbidden_fields))}.",
        )
    _validate_required_fields(validated_data)
    date_val = validated_data["date"]
    start_time_val = validated_data["start_time"]
    _validate_guests_count(validated_data["guests_count"])
    _validate_future(date_val, start_time_val, timezone.now().astimezone(RESTAURANT_TZ))
    end_time_val = _visit_end_time(date_val, start_time_val, DEFAULT_DURATION_MINUTES)

    reservation = Reservation.objects.create(
        **validated_data, status="pending", source="website", end_time=end_time_val
    )
    ReservationHistory.objects.create(
        reservation=reservation,
        actor=None,
        action="created",
        old_status="",
        new_status="pending",
        details="Бронь создана клиентом через сайт",
    )
    return reservation


@transaction.atomic
def create_staff_reservation(*, validated_data, actor) -> Reservation:
    source = validated_data.get("source", "phone")
    if source not in ("phone", "walk_in"):
        raise ReservationBusinessError(
            "invalid_source", "Источник должен быть phone или walk_in."
        )

    _validate_required_fields(validated_data)
    date_val = validated_data["date"]
    start_time_val = validated_data["start_time"]
    guests_count = validated_data["guests_count"]
    duration = validated_data.get("duration_minutes", DEFAULT_DURATION_MINUTES)
    _validate_guests_count(guests_count)
    _validate_duration(duration)

    now_local = timezone.now().astimezone(RESTAURANT_TZ)
    if source == "walk_in":
        if date_val != now_local.date():
            raise ReservationBusinessError(
                "walk_in_date", "Гость без брони оформляется только на текущую дату."
            )
        current_minute = now_local.time().replace(second=0, microsecond=0)
        if start_time_val < current_minute:
            raise ReservationBusinessError(
                "walk_in_time", "Время начала не может быть раньше текущей минуты."
            )
    else:
        _validate_future(date_val, start_time_val, now_local)
    end_time_val = _visit_end_time(date_val, start_time_val, duration)

    table = validated_data.get("table")
    if table is not None:
        table = _lock_available_table(
            table.pk, date_val, start_time_val, end_time_val, guests_count
        )

    reservation = Reservation.objects.create(
        **{field: validated_data[field] for field in PUBLIC_FIELDS if field in validated_data},
        status="pending",
        source=source,
        end_time=end_time_val,
        created_by=actor,
        responsible_employee=actor,
        table=table,
    )
    table_label = table.code if table is not None else "не назначен"
    ReservationHistory.objects.create(
        reservation=reservation,
        actor=actor,
        action="created",
        old_status="",
        new_status="pending",
        details=f"Создано сотрудником {actor}. Стол: {table_label}",
    )
    return reservation


@transaction.atomic
def update_reservation(*, reservation: Reservation, validated_data: dict, actor) -> Reservation:
    reservation = Reservation.objects.select_for_update().get(pk=reservation.pk)
    if reservation.status not in EDITABLE_STATUSES:
        raise ReservationBusinessError(
            "invalid_status", "Редактировать можно только pending или confirmed брони."
        )

    forbidden_fields = validated_data.keys() - EDITABLE_FIELDS
    if forbidden_fields:
        raise ReservationBusinessError(
            "field_not_allowed",
            f"Эти поля нельзя изменить: {', '.join(sorted(forbidden_fields))}.",
        )

    date_val = validated_data.get("date", reservation.date)
    start_time_val = validated_data.get("start_time", reservation.start_time)
    end_time_val = reservation.end_time
    guests_count = validated_data.get("guests_count", reservation.guests_count)
    _validate_guests_count(guests_count)

    if SCHEDULE_FIELDS.intersection(validated_data):
        if "duration_minutes" in validated_data:
            duration = validated_data["duration_minutes"]
        else:
            old_duration = (
                datetime.combine(reservation.date, reservation.end_time)
                - datetime.combine(reservation.date, reservation.start_time)
            ).total_seconds()
            if old_duration % 60:
                raise ReservationBusinessError(
                    "invalid_duration", "Укажите длительность в целых минутах."
                )
            duration = int(old_duration // 60)
        _validate_duration(duration)
        end_time_val = _visit_end_time(date_val, start_time_val, duration)

    schedule_changed = (date_val, start_time_val, end_time_val) != (
        reservation.date, reservation.start_time, reservation.end_time
    )
    if schedule_changed:
        _validate_future(date_val, start_time_val, timezone.now().astimezone(RESTAURANT_TZ))

    if reservation.table_id is not None and (
        schedule_changed or guests_count != reservation.guests_count
    ):
        _lock_available_table(
            reservation.table_id, date_val, start_time_val, end_time_val, guests_count,
            exclude_reservation_id=reservation.pk,
        )

    for field, value in validated_data.items():
        if field != "duration_minutes":
            setattr(reservation, field, value)
    reservation.end_time = end_time_val
    reservation.save()

    ReservationHistory.objects.create(
        reservation=reservation,
        actor=actor,
        action="updated",
        old_status=reservation.status,
        new_status=reservation.status,
        details=f"Бронь обновлена сотрудником {actor}",
    )
    return reservation


def _save_status(reservation, actor, new_status, details):
    old_status = reservation.status
    reservation.status = new_status
    reservation.save(update_fields=["status", "updated_at"])
    ReservationHistory.objects.create(
        reservation=reservation,
        actor=actor,
        action=new_status,
        old_status=old_status,
        new_status=new_status,
        details=details,
    )
    return reservation


@transaction.atomic
def confirm_reservation(*, reservation: Reservation, actor) -> Reservation:
    reservation = Reservation.objects.select_for_update().get(pk=reservation.pk)
    if reservation.status == "confirmed":
        raise ReservationBusinessError("already_confirmed", "Бронь уже подтверждена.")
    if reservation.status != "pending":
        raise ReservationBusinessError(
            "invalid_status", "Подтвердить можно только бронь со статусом pending."
        )
    if reservation.table_id is None:
        raise ReservationBusinessError(
            "table_required", "Нельзя подтвердить бронирование без назначенного стола."
        )

    _lock_available_table(
        reservation.table_id, reservation.date, reservation.start_time,
        reservation.end_time, reservation.guests_count,
        exclude_reservation_id=reservation.pk,
    )
    return _save_status(reservation, actor, "confirmed", f"Бронь подтверждена сотрудником {actor}")


@transaction.atomic
def mark_arrived(*, reservation: Reservation, actor) -> Reservation:
    reservation = Reservation.objects.select_for_update().get(pk=reservation.pk)
    if reservation.status != "confirmed":
        raise ReservationBusinessError(
            "invalid_status", "Отметить прибытие можно только для подтвержденной брони."
        )
    return _save_status(reservation, actor, "arrived", f"Гость прибыл. Отметил сотрудник {actor}")


@transaction.atomic
def cancel_reservation(*, reservation: Reservation, actor) -> Reservation:
    reservation = Reservation.objects.select_for_update().get(pk=reservation.pk)
    if reservation.status == "cancelled":
        raise ReservationBusinessError("already_cancelled", "Бронь уже отменена.")
    if reservation.status not in EDITABLE_STATUSES:
        raise ReservationBusinessError(
            "invalid_status", "Отменить можно только pending или confirmed брони."
        )
    return _save_status(reservation, actor, "cancelled", f"Бронь отменена сотрудником {actor}")


@transaction.atomic
def assign_table(*, reservation: Reservation, table: RestaurantTable, actor) -> Reservation:
    reservation = Reservation.objects.select_for_update().get(pk=reservation.pk)
    if reservation.status not in EDITABLE_STATUSES:
        raise ReservationBusinessError(
            "invalid_status", "Назначить стол можно только для pending или confirmed броней."
        )
    if table is None:
        raise ReservationBusinessError("table_not_found", "Стол не найден.")

    table = _lock_available_table(
        table.pk, reservation.date, reservation.start_time, reservation.end_time,
        reservation.guests_count, exclude_reservation_id=reservation.pk,
    )
    reservation.table = table
    reservation.save(update_fields=["table", "updated_at"])
    ReservationHistory.objects.create(
        reservation=reservation,
        actor=actor,
        action="table_assigned",
        old_status=reservation.status,
        new_status=reservation.status,
        details=f"Назначен стол {table.code} сотрудником {actor}",
    )
    return reservation


def get_hall_plan(*, date=None, time=None, duration_minutes=None) -> dict:
    duration = DEFAULT_DURATION_MINUTES if duration_minutes is None else duration_minutes
    _validate_duration(duration)
    now_local = timezone.now().astimezone(RESTAURANT_TZ)
    query_date = date if date is not None else now_local.date()
    query_time = time if time is not None else now_local.time()

    if time is not None or duration_minutes is not None:
        end_time = _visit_end_time(query_date, query_time, duration)
    else:
        start_dt = datetime.combine(query_date, query_time)
        day_end = datetime.combine(query_date, d_time.max)
        window = min(timedelta(minutes=duration), day_end - start_dt)
        end_time = (start_dt + window).time()

    hall_plan = {
        "date": str(query_date),
        "time": str(query_time),
        "duration_minutes": duration,
        "tables": [],
    }
    for table in RestaurantTable.objects.order_by("sort_order", "code"):
        statuses = list(
            _overlapping_reservations(table, query_date, query_time, end_time)
            .values_list("status", flat=True)
        )
        if "arrived" in statuses:
            status = "occupied"
        elif statuses:
            status = "reserved"
        else:
            status = "free"

        hall_plan["tables"].append({
            "id": table.id,
            "code": table.code,
            "capacity": table.capacity,
            "zone": table.zone,
            "is_active": table.is_active,
            "status": status,
        })
    return hall_plan
