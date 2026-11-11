from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.catalog.models import Category, Dish


class SeedCatalogTests(TestCase):
    def test_seed_is_repeatable_and_does_not_overwrite_existing_price(self):
        with TemporaryDirectory() as media_dir:
            with override_settings(MEDIA_ROOT=media_dir):
                call_command('seed_catalog', verbosity=0)
                self.assertEqual(Category.objects.count(), 4)
                self.assertEqual(Dish.objects.count(), 8)
                dish = Dish.objects.get(slug='filet-mignon')
                dish.price = '999.00'
                dish.save(update_fields=['price'])

                call_command('seed_catalog', verbosity=0)
                dish.refresh_from_db()
                self.assertEqual(Category.objects.count(), 4)
                self.assertEqual(Dish.objects.count(), 8)
                self.assertEqual(str(dish.price), '999.00')
                self.assertTrue(Path(media_dir, dish.image.name).is_file())
