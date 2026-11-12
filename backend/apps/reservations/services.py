from datetime import datetime, timedelta, time as d_time
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from zoneinfo import ZoneInfo
from .models import Reservation, ReservationHistory, RestaurantTable

MOSCOW_TZ = ZoneInfo("Asia/Bishkek")


class ReservationBusinessError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _validate_working_hours(date_val, start_time_val, duration_minutes: int):
    opening_time = d_time(12, 0)
    closing_time = d_time(23, 0)

    if start_time_val < opening_time or start_time_val > closing_time:
        raise ReservationBusinessError("working_hours", "Ресторан работает с 12:00 до 23:00.")

    start_dt = datetime.combine(date_val, start_time_val)
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    if end_dt.time() > closing_time or end_dt.date() > date_val:
        raise ReservationBusinessError("working_hours", "Бронирование должно завершаться не позже 23:00.")


def _check_table_conflict(table: RestaurantTable, date_val, start_time_val, end_time_val, exclude_reservation_id=None):
    conflicts = Reservation.objects.filter(
        table=table,
        date=date_val,
        status__in=['pending', 'confirmed', 'arrived']
    ).filter(
        Q(start_time__lt=end_time_val) & Q(end_time__gt=start_time_val)
    )

    if exclude_reservation_id:
        conflicts = conflicts.exclude(id=exclude_reservation_id)

    if conflicts.exists():
        raise ReservationBusinessError("table_conflict", f"Стол {table.code} уже занят в выбранный интервал.")


def create_public_reservation(*, validated_data) -> Reservation:
    with transaction.atomic():
        for field in ['status', 'table', 'created_by', 'responsible_employee', 'source']:
            validated_data.pop(field, None)

        date_val = validated_data.get('date')
        start_time_val = validated_data.get('start_time')

        duration = validated_data.pop('duration_minutes', 120) or 120
        start_dt = datetime.combine(date_val, start_time_val)
        end_time_val = (start_dt + timedelta(minutes=duration)).time()

        now_local = timezone.now().astimezone(MOSCOW_TZ)
        if start_dt.replace(tzinfo=MOSCOW_TZ) <= now_local:
            raise ReservationBusinessError("invalid_time", "Дата и время должны быть в будущем.")

        _validate_working_hours(date_val, start_time_val, duration)

        validated_data['status'] = 'pending'
        validated_data['source'] = 'website'
        validated_data['end_time'] = end_time_val
        validated_data.pop('duration_minutes', None)

        reservation = Reservation.objects.create(**validated_data)

        ReservationHistory.objects.create(
            reservation=reservation,
            actor=None,
            action="created_public",
            old_status="",
            new_status='pending',
            details="Бронь создана клиентом через сайт"
        )
        return reservation


def create_staff_reservation(*, validated_data, actor) -> Reservation:
    with transaction.atomic():
        source = validated_data.get('source', 'phone')
        if source not in ['phone', 'walk_in']:
            raise ReservationBusinessError("invalid_source", "Источник должен быть phone или walk_in.")

        date_val = validated_data.get('date')
        start_time_val = validated_data.get('start_time')

        duration = validated_data.get('duration_minutes', 120) or 120
        if duration < 30 or duration > 360 or duration % 30 != 0:
            raise ReservationBusinessError("invalid_duration", "Длительность от 30 до 360 минут кратно 30.")

        start_dt = datetime.combine(date_val, start_time_val)
        end_time_val = (start_dt + timedelta(minutes=duration)).time()

        now_local = timezone.now().astimezone(MOSCOW_TZ)

        if source == 'walk_in':
            if date_val != now_local.date():
                raise ReservationBusinessError("walk_in_date", "Гость без брони оформляется только на текущую дату.")
            if start_time_val < now_local.time():
                raise ReservationBusinessError("walk_in_time", "Время начала не может быть в прошлом.")

        _validate_working_hours(date_val, start_time_val, duration)

        table = validated_data.pop('table', None)
        if table:
            if not table.is_active:
                raise ReservationBusinessError("table_inactive", "Стол неактивен.")
            if validated_data.get('guests_count', 1) > table.capacity:
                raise ReservationBusinessError("table_capacity", "Превышена вместимость стола.")
            _check_table_conflict(table, date_val, start_time_val, end_time_val)

        validated_data['status'] = 'pending'
        validated_data['source'] = source
        validated_data['end_time'] = end_time_val
        validated_data['created_by'] = actor
        validated_data['responsible_employee'] = actor
        validated_data.pop('duration_minutes', None)
        validated_data['table'] = table

        reservation = Reservation.objects.create(**validated_data)

        action_name = "created_with_table" if table else "created_staff"
        ReservationHistory.objects.create(
            reservation=reservation,
            actor=actor,
            action=action_name,
            old_status="",
            new_status='pending',
            details=f"Создано сотрудником {actor}. Стол: {table.code if table else 'не назначен'}"
        )
        return reservation


def update_reservation(*, reservation: Reservation, validated_data: dict, actor) -> Reservation:
    with transaction.atomic():
        if reservation.status not in ['pending', 'confirmed']:
            raise ReservationBusinessError("invalid_status", "Редактировать можно только pending или confirmed брони.")

        for field in ['status', 'table', 'source', 'responsible_employee', 'created_by']:
            validated_data.pop(field, None)

        date_val = validated_data.get('date', reservation.date)
        start_time_val = validated_data.get('start_time', reservation.start_time)

        duration = validated_data.pop('duration_minutes', None)
        if duration is not None:
            if duration < 30 or duration > 360 or duration % 30 != 0:
                raise ReservationBusinessError("invalid_duration", "Неверная длительность.")
            end_time_val = (datetime.combine(date_val, start_time_val) + timedelta(minutes=duration)).time()
        else:
            old_duration = int((datetime.combine(reservation.date, reservation.end_time) - datetime.combine(
                reservation.date, reservation.start_time)).total_seconds() / 60)
            end_time_val = (datetime.combine(date_val, start_time_val) + timedelta(minutes=old_duration)).time()

        total_dur = int((datetime.combine(date_val, end_time_val) - datetime.combine(date_val,
                                                                                     start_time_val)).total_seconds() / 60)
        _validate_working_hours(date_val, start_time_val, total_dur)

        if reservation.table:
            _check_table_conflict(reservation.table, date_val, start_time_val, end_time_val,
                                  exclude_reservation_id=reservation.id)

        old_status = reservation.status
        for attr, value in validated_data.items():
            setattr(reservation, attr, value)

        reservation.end_time = end_time_val
        reservation.save()

        ReservationHistory.objects.create(
            reservation=reservation,
            actor=actor,
            action="updated",
            old_status=old_status,
            new_status=reservation.status,
            details=f"Бронь обновлена сотрудником {actor}"
        )
        return reservation


def confirm_reservation(*, reservation: Reservation, actor) -> Reservation:
    with transaction.atomic():
        if reservation.status == 'cancelled':
            raise ReservationBusinessError("invalid_status", "Нельзя подтвердить отмененную бронь.")
        if reservation.status == 'confirmed':
            raise ReservationBusinessError("already_confirmed", "Бронь уже подтверждена.")

        if not reservation.table:
            raise ReservationBusinessError("table_required", "Нельзя подтвердить бронирование без назначенного стола.")

        _check_table_conflict(reservation.table, reservation.date, reservation.start_time, reservation.end_time,
                              exclude_reservation_id=reservation.id)

        old_status = reservation.status
        reservation.status = 'confirmed'
        reservation.save()

        ReservationHistory.objects.create(
            reservation=reservation,
            actor=actor,
            action="confirmed",
            old_status=old_status,
            new_status='confirmed',
            details=f"Бронь подтверждена сотрудником {actor}"
        )
        return reservation


def mark_arrived(*, reservation: Reservation, actor) -> Reservation:
    with transaction.atomic():
        if reservation.status != 'confirmed':
            raise ReservationBusinessError("invalid_status", "Отметить прибытие можно только для подтвержденной брони.")

        old_status = reservation.status
        reservation.status = 'arrived'
        reservation.save()

        ReservationHistory.objects.create(
            reservation=reservation,
            actor=actor,
            action="arrived",
            old_status=old_status,
            new_status='arrived',
            details=f"Гость прибыл. Отметил сотрудник {actor}"
        )
        return reservation


def cancel_reservation(*, reservation: Reservation, actor) -> Reservation:
    with transaction.atomic():
        if reservation.status == 'arrived':
            raise ReservationBusinessError("invalid_status", "Нельзя отменить бронь пришедшего гостя.")
        if reservation.status == 'cancelled':
            raise ReservationBusinessError("already_cancelled", "Бронь уже отменена.")

        old_status = reservation.status
        reservation.status = 'cancelled'
        reservation.save()

        ReservationHistory.objects.create(
            reservation=reservation,
            actor=actor,
            action="cancelled",
            old_status=old_status,
            new_status='cancelled',
            details=f"Бронь отменена сотрудником {actor}"
        )
        return reservation


def assign_table(*, reservation: Reservation, table: RestaurantTable, actor) -> Reservation:
    with transaction.atomic():
        if reservation.status not in ['pending', 'confirmed']:
            raise ReservationBusinessError("invalid_status",
                                           "Назначить стол можно только для pending или confirmed броней.")

        if not table.is_active:
            raise ReservationBusinessError("table_inactive", "Стол неактивен.")

        if reservation.guests_count > table.capacity:
            raise ReservationBusinessError("table_capacity", "Вместимость стола меньше количества гостей.")

        _check_table_conflict(table, reservation.date, reservation.start_time, reservation.end_time,
                              exclude_reservation_id=reservation.id)

        reservation.table = table
        reservation.save()

        ReservationHistory.objects.create(
            reservation=reservation,
            actor=actor,
            action="assign_table",
            old_status=reservation.status,
            new_status=reservation.status,
            details=f"Назначен стол {table.code} сотрудником {actor}"
        )
        return reservation


def get_hall_plan(*, date=None, time=None, duration_minutes=None) -> dict:
    if duration_minutes is not None:
        if not isinstance(duration_minutes,
                          int) or duration_minutes < 30 or duration_minutes > 360 or duration_minutes % 30 != 0:
            raise ReservationBusinessError("invalid_duration", "Длительность от 30 до 360 минут кратно 30.")

    duration = duration_minutes if duration_minutes is not None else 120
    query_date = date if date else timezone.now().astimezone(MOSCOW_TZ).date()
    query_time = time if time else timezone.now().astimezone(MOSCOW_TZ).time()

    tables = RestaurantTable.objects.order_by('sort_order')

    hall_plan = {
        "date": str(query_date),
        "time": str(query_time),
        "tables": []
    }

    start_dt = datetime.combine(query_date, query_time)
    end_t = (start_dt + timedelta(minutes=duration)).time()

    for table in tables:
        status_str = "free"

        if table.is_active:
            overlapping_reservations = Reservation.objects.filter(
                table=table,
                date=query_date,
                status__in=['pending', 'confirmed', 'arrived']
            ).filter(
                Q(start_time__lt=end_t) & Q(end_time__gt=query_time)
            )

            if overlapping_reservations.exists():
                if overlapping_reservations.filter(status__in=['confirmed', 'arrived']).exists():
                    status_str = "occupied"
                else:
                    status_str = "reserved"

        hall_plan["tables"].append({
            "id": table.id,
            "code": table.code,
            "capacity": table.capacity,
            "zone": table.zone,
            "is_active": table.is_active,
            "status": status_str
        })

    return hall_plan