
from django.core.management.base import BaseCommand
from apps.reservations.models import RestaurantTable


class Command(BaseCommand):
    help = "Создание начальных 12 столов ресторана"

    def handle(self, *args, **options):

        tables = [
            ("T01", 2),
            ("T02", 4),
            ("T03", 2),
            ("T04", 4),
            ("T05", 4),
            ("T06", 2),
            ("T07", 4),
            ("T08", 4),
            ("T09", 2),
            ("T10", 4),
            ("T11", 2),
            ("T12", 6),
        ]

        created_count = 0
        existing_count = 0

        for code, capacity in tables:

            table, created = RestaurantTable.objects.get_or_create(
                code=code,
                defaults={
                    "capacity": capacity,
                    "zone": "Основной зал",
                    "sort_order": int(code[1:]),
                    "is_active": True,
                }
            )

            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Создан стол {table.code}"
                    )
                )
            else:
                existing_count += 1
                self.stdout.write(
                    f"Стол {table.code} уже существует"
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Готово! Создано: {created_count}, "
                f"уже существовало: {existing_count}"
            )
        )
