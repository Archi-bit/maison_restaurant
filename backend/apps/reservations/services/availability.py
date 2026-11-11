"""Базовые правила: время работы, пересечения, блокировка столов, история, план зала.

Здесь нет HTTP, DRF Response и serializers — только бизнес-логика.
"""
from collections import defaultdict
from datetime import date as date_cls
from datetime import datetime, timedelta
from datetime import time as dtime
from zoneinfo import ZoneInfo

from django.utils import timezone

from ..models import Reservation, ReservationHistory, RestaurantTable

TZ = ZoneInfo("Asia/Bishkek")
OPEN_TIME = dtime(12, 0)
CLOSE_TIME = dtime(23, 0)
DEFAULT_DURATION_MINUTES = 120
MIN_GUESTS = 1
MAX_GUESTS = 6

# Эти статусы занимают стол. cancelled стол освобождает.
ACTIVE_STATUSES = (
    Reservation.Status.PENDING,
    Reservation.Status.CONFIRMED,
    Reservation.Status.ARRIVED,
)


class ReservationBusinessError(Exception):
    """Бизнес-ошибка. API превращает её в HTTP 400 с полем code."""

    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


# ---------- время ----------

def now_local():
    return timezone.now().astimezone(TZ)


def calc_end_time(start_time, duration_minutes=DEFAULT_DURATION_MINUTES):
    dummy_day = date_cls(2000, 1, 1)
    start_dt = datetime.combine(dummy_day, start_time)
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    if end_dt.date() != dummy_day:  # перешли через полночь
        raise ReservationBusinessError(
            "outside_working_hours", "Посещение должно закончиться не позже 23:00"
        )
    return end_dt.time()


def validate_visit_window(*, date, start_time, end_time, guests_count, check_future=True):
    if guests_count is None or not (MIN_GUESTS <= guests_count <= MAX_GUESTS):
        raise ReservationBusinessError(
            "invalid_guests_count", "Количество гостей должно быть от 1 до 6"
        )
    if end_time <= start_time:
        raise ReservationBusinessError(
            "invalid_interval", "Время окончания должно быть позже времени начала"
        )
    if start_time < OPEN_TIME or end_time > CLOSE_TIME:
        raise ReservationBusinessError(
            "outside_working_hours",
            "Ресторан работает с 12:00 до 23:00, посещение должно уложиться в это время",
        )
    if check_future:
        start_dt = datetime.combine(date, start_time, tzinfo=TZ)
        if start_dt <= now_local():
            raise ReservationBusinessError(
                "past_datetime", "Дата и время должны быть в будущем"
            )


# ---------- столы и пересечения ----------

def get_conflicting_reservations(*, table, date, start_time, end_time, exclude_reservation_id=None):
    """existing_start < new_end AND existing_end > new_start. Соседние интервалы допустимы."""
    qs = Reservation.objects.filter(
        table=table,
        date=date,
        status__in=ACTIVE_STATUSES,
        start_time__lt=end_time,
        end_time__gt=start_time,
    )
    if exclude_reservation_id is not None:
        qs = qs.exclude(pk=exclude_reservation_id)
    return qs


def lock_table(table):
    """select_for_update на столе. Вызывать ТОЛЬКО внутри transaction.atomic()."""
    try:
        return RestaurantTable.objects.select_for_update().get(pk=getattr(table, "pk", table))
    except RestaurantTable.DoesNotExist:
        raise ReservationBusinessError("table_not_found", "Стол не найден")


def ensure_table_available(
    *, table, date, start_time, end_time, guests_count, exclude_reservation_id=None
):
    """Проверки назначения стола. Стол должен быть уже заблокирован через lock_table."""
    if not table.is_active:
        raise ReservationBusinessError("table_inactive", f"Стол {table.code} не активен")
    if table.capacity < guests_count:
        raise ReservationBusinessError(
            "table_too_small",
            f"За стол {table.code} помещается {table.capacity}, а гостей {guests_count}",
        )
    conflicts = get_conflicting_reservations(
        table=table,
        date=date,
        start_time=start_time,
        end_time=end_time,
        exclude_reservation_id=exclude_reservation_id,
    )
    if conflicts.exists():
        raise ReservationBusinessError(
            "table_conflict", f"Стол {table.code} уже занят в это время"
        )


# ---------- история ----------

def add_history(reservation, actor, action, old_status="", new_status="", details=""):
    return ReservationHistory.objects.create(
        reservation=reservation,
        actor=actor,
        action=action,
        old_status=old_status,
        new_status=new_status,
        details=details,
    )


# ---------- план зала ----------

def get_hall_plan(*, date=None, time=None, duration_minutes=None):
    """Статусы столов вычисляются на лету, в БД не хранятся.

    free     — нет активных броней в окне
    reserved — есть pending/confirmed
    occupied — есть arrived
    """
    now = now_local()
    date = date or now.date()
    if time is None:
        time = now.time().replace(second=0, microsecond=0) if date == now.date() else OPEN_TIME
    duration = duration_minutes or DEFAULT_DURATION_MINUTES

    end_dt = datetime.combine(date, time) + timedelta(minutes=duration)
    window_end = dtime.max if end_dt.date() != date else end_dt.time()

    tables = list(RestaurantTable.objects.filter(is_active=True).order_by("sort_order", "code"))
    reservations = Reservation.objects.filter(
        table__in=tables,
        date=date,
        status__in=ACTIVE_STATUSES,
        start_time__lt=window_end,
        end_time__gt=time,
    ).order_by("start_time")

    by_table = defaultdict(list)
    for r in reservations:
        by_table[r.table_id].append(r)

    result_tables = []
    counts = {"free": 0, "reserved": 0, "occupied": 0}
    for t in tables:
        items = by_table.get(t.id, [])
        if any(r.status == Reservation.Status.ARRIVED for r in items):
            status = "occupied"
        elif items:
            status = "reserved"
        else:
            status = "free"
        counts[status] += 1
        result_tables.append(
            {
                "id": t.id,
                "code": t.code,
                "capacity": t.capacity,
                "zone": t.zone,
                "status": status,
                "reservations": [
                    {
                        "id": r.id,
                        "number": r.number,
                        "guest_name": r.guest_name,
                        "guests_count": r.guests_count,
                        "start_time": r.start_time,
                        "end_time": r.end_time,
                        "status": r.status,
                    }
                    for r in items
                ],
            }
        )

    return {
        "date": date,
        "time": time,
        "duration_minutes": duration,
        "summary": {**counts, "total": len(tables), "total_seats": sum(t.capacity for t in tables)},
        "tables": result_tables,
    }
