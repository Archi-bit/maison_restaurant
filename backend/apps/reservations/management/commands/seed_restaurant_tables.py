from django.core.management.base import BaseCommand
from django.db import transaction

from apps.reservations.models import RestaurantTable

ZONE = "Основной зал"
TABLES = [
    ("T01", 2), ("T02", 4), ("T03", 2), ("T04", 4),
    ("T05", 4), ("T06", 2), ("T07", 4), ("T08", 4),
    ("T09", 2), ("T10", 4), ("T11", 2), ("T12", 6),
]  # 12 столов, 40 мест


class Command(BaseCommand):
    help = "Создаёт 12 начальных столов ресторана (идемпотентно, брони не трогает)"

    @transaction.atomic
    def handle(self, *args, **options):
        created = 0
        for order, (code, capacity) in enumerate(TABLES, start=1):
            _, was_created = RestaurantTable.objects.get_or_create(
                code=code,
                defaults={"capacity": capacity, "zone": ZONE, "sort_order": order},
            )
            created += int(was_created)
        self.stdout.write(
            self.style.SUCCESS(
                f"Создано столов: {created}. Всего в базе: {RestaurantTable.objects.count()}"
            )
        )
