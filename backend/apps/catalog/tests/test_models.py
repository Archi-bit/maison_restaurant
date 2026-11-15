from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from apps.catalog.models import Category, Dish


class CategoryModelTests(TestCase):
    def test_category_generates_latin_slug(self):
        category = Category.objects.create(name='Горячие блюда')
        self.assertEqual(category.slug, 'goryachie-blyuda')
        self.assertEqual(str(category), 'Горячие блюда')

    def test_category_slug_is_unique(self):
        Category.objects.create(name='Салаты')
        duplicate = Category.objects.create(name='Салаты')
        self.assertEqual(duplicate.slug, 'salaty-2')

    def test_explicit_category_slug_is_preserved(self):
        category = Category.objects.create(name='Закуски', slug='appetizers')
        category.name = 'Другие закуски'
        category.save()
        self.assertEqual(category.slug, 'appetizers')

    def test_category_sorting(self):
        Category.objects.create(name='Позже', sort_order=10)
        Category.objects.create(name='Раньше', sort_order=1)
        self.assertEqual(
            list(Category.objects.values_list('name', flat=True)),
            ['Раньше', 'Позже'],
        )


class DishModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name='Горячее', slug='hot')

    def new_dish(self, **kwargs):
        fields = {
            'category': self.category,
            'name': 'Филе миньон',
            'price': Decimal('1890.00'),
            'image': 'dishes/filet.jpg',
        }
        fields.update(kwargs)
        return Dish.objects.create(**fields)

    def test_dish_generates_slug_and_preserves_it(self):
        dish = self.new_dish()
        self.assertEqual(dish.slug, 'file-minon')
        dish.name = 'Новое название'
        dish.save()
        self.assertEqual(dish.slug, 'file-minon')

    def test_duplicate_dish_slug_gets_suffix(self):
        self.new_dish()
        dish = self.new_dish()
        self.assertEqual(dish.slug, 'file-minon-2')

    def test_explicit_dish_slug_is_preserved(self):
        dish = self.new_dish(slug='filet-mignon')
        self.assertEqual(dish.slug, 'filet-mignon')
        self.assertEqual(str(dish), 'Филе миньон')

    def test_negative_price_is_rejected_by_model_validation(self):
        dish = Dish(
            category=self.category,
            name='Блюдо',
            price=Decimal('-1.00'),
            image='dishes/test.jpg',
        )
        with self.assertRaises(ValidationError):
            dish.full_clean()

    def test_negative_price_is_rejected_by_database(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.new_dish(price=Decimal('-1.00'))

    def test_category_with_dish_cannot_be_deleted(self):
        self.new_dish()
        with self.assertRaises(ProtectedError):
            self.category.delete()

    def test_sort_order(self):
        self.new_dish(name='Второе', sort_order=2)
        self.new_dish(name='Первое', sort_order=1)
        self.assertEqual(
            list(Dish.objects.values_list('name', flat=True)),
            ['Первое', 'Второе'],
        )
