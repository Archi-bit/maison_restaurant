from decimal import Decimal

from django.urls import reverse
from rest_framework.test import APITestCase

from apps.catalog.models import Category, Dish


class CatalogApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name='Напитки', slug='drinks')
        cls.other_category = Category.objects.create(
            name='Десерты', slug='desserts', sort_order=1,
        )
        cls.dish = Dish.objects.create(
            category=cls.category,
            name='Чай', slug='tea', price=Decimal('120.00'),
            image='dishes/tea.jpg', is_featured=True,
        )
        Dish.objects.create(
            category=cls.other_category,
            name='Торт', slug='cake', price=Decimal('250.00'),
            image='dishes/cake.jpg',
        )

    def test_categories_only_include_active(self):
        Category.objects.create(name='Архив', is_active=False)
        response = self.client.get(reverse('category-list'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item['slug'] for item in response.data], ['drinks', 'desserts'],
        )

    def test_filter_category_and_featured(self):
        response = self.client.get(
            reverse('dish-list'), {'category': 'drinks', 'featured': 'true'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['slug'], 'tea')
        self.assertEqual(response.data['results'][0]['price'], '120.00')

    def test_invalid_featured_returns_400(self):
        response = self.client.get(reverse('dish-list'), {'featured': 'yes'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('featured', response.data)

    def test_detail_by_slug(self):
        response = self.client.get(reverse('dish-detail', args=['tea']))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['name'], 'Чай')
        self.assertEqual(response.data['description'], '')

    def test_inactive_category_hides_dish(self):
        self.category.is_active = False
        self.category.save(update_fields=['is_active'])
        response = self.client.get(reverse('dish-detail', args=['tea']))
        self.assertEqual(response.status_code, 404)

    def test_search_is_case_insensitive(self):
        response = self.client.get(reverse('dish-list'), {'search': 'чАЙ'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['slug'], 'tea')

    def test_combined_search_and_category(self):
        response = self.client.get(
            reverse('dish-list'), {'search': 'торт', 'category': 'drinks'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 0)

    def test_featured_false(self):
        response = self.client.get(reverse('dish-list'), {'featured': 'false'})
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['slug'], 'cake')

    def test_inactive_dish_hidden_in_list_and_detail(self):
        self.dish.is_active = False
        self.dish.save(update_fields=['is_active'])
        listing = self.client.get(reverse('dish-list'))
        detail = self.client.get(reverse('dish-detail', args=['tea']))
        self.assertEqual(listing.data['count'], 1)
        self.assertEqual(detail.status_code, 404)

    def test_unknown_slug_returns_404(self):
        response = self.client.get(reverse('dish-detail', args=['missing']))
        self.assertEqual(response.status_code, 404)

    def test_pagination_returns_twelve_per_page(self):
        for index in range(13):
            Dish.objects.create(
                category=self.category,
                name=f'Напиток {index}', slug=f'drink-{index}',
                price=Decimal('100.00'), image='dishes/test.jpg',
            )
        first = self.client.get(reverse('dish-list'))
        second = self.client.get(reverse('dish-list'), {'page': 2})
        self.assertEqual(first.data['count'], 15)
        self.assertEqual(len(first.data['results']), 12)
        self.assertEqual(len(second.data['results']), 3)

    def test_public_catalog_is_read_only(self):
        self.assertEqual(
            self.client.post(reverse('dish-list'), {'name': 'Вредное'}).status_code,
            405,
        )
        self.assertEqual(
            self.client.patch(reverse('dish-detail', args=['tea']), {}).status_code,
            405,
        )
        self.assertEqual(
            self.client.delete(reverse('dish-detail', args=['tea'])).status_code,
            405,
        )
