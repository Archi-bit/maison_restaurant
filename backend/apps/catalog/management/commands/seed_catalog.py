"""Create repeatable demo catalog data and local placeholder images.

Usage: python manage.py seed_catalog
Demo prices and images are illustrative, NOT verified against Figma.
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from PIL import Image, ImageDraw

from apps.catalog.models import Category, Dish


CATEGORIES = [
    ("appetizers", "Закуски"),
    ("salads", "Салаты"),
    ("hot", "Горячее"),
    ("desserts", "Десерты"),
]

# slug, name, category_slug, demo_price, featured, available, active
DISHES = [
    ("filet-mignon", "Филе миньон", "hot", "1890.00", True, True, True),
    ("beef-tartare", "Тартар из говядины", "appetizers", "990.00", True, True, True),
    ("grilled-salmon", "Лосось на гриле", "hot", "1590.00", False, True, True),
    ("burrata-tomato", "Буррата с томатами", "appetizers", "890.00", True, True, True),
    ("truffle-pasta", "Трюфельная паста", "hot", "1290.00", False, True, True),
    ("chocolate-fondant", "Шоколадный фондан", "desserts", "590.00", True, True, True),
    ("seasonal-salad", "Сезонный салат", "salads", "690.00", False, False, True),
    ("berry-tart", "Ягодный тарт", "desserts", "650.00", False, True, False),
]


class Command(BaseCommand):
    help = "Create demo MAISON categories, dishes and placeholder images (idempotent)."

    def handle(self, *args, **options):
        categories = {}
        for position, (slug, name) in enumerate(CATEGORIES):
            category, _ = Category.objects.get_or_create(
                slug=slug, defaults={"name": name, "sort_order": position}
            )
            categories[slug] = category

        image_dir = Path(settings.MEDIA_ROOT) / "dishes"
        image_dir.mkdir(parents=True, exist_ok=True)

        created_count = 0
        for position, (slug, name, category_slug, price, featured, available, active) in enumerate(DISHES):
            image_path = image_dir / f"{slug}.png"
            if not image_path.exists():
                image = Image.new("RGB", (640, 420), (235, 227, 214))
                draw = ImageDraw.Draw(image)
                draw.ellipse((120, 40, 520, 395), fill=(247, 247, 243), outline=(143, 134, 119), width=10)
                draw.ellipse((195, 108, 445, 340), fill=(177, 166, 143))
                image.save(image_path, format="PNG")

            dish, created = Dish.objects.get_or_create(
                slug=slug,
                defaults={
                    "category": categories[category_slug],
                    "name": name,
                    "short_description": "Учебное блюдо для интеграции API.",
                    "description": "Демонстрационные данные; замените на сведения из Figma.",
                    "price": price,
                    "image": f"dishes/{slug}.png",
                    "is_featured": featured,
                    "is_available": available,
                    "is_active": active,
                    "sort_order": position,
                },
            )
            if created:
                created_count += 1
            elif not dish.image:
                dish.image = f"dishes/{slug}.png"
                dish.save(update_fields=["image"])

        self.stdout.write(self.style.SUCCESS(
            f"Demo catalog ready: {len(categories)} categories, "
            f"{len(DISHES)} expected dishes, {created_count} newly created."
        ))