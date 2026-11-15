from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import CheckConstraint, Q

from .slug_utils import create_unique_slug


class Category(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = create_unique_slug(self, self.name, 'category')
            if kwargs.get('update_fields') is not None:
                kwargs['update_fields'] = set(kwargs['update_fields']) | {'slug'}
        return super().save(*args, **kwargs)

    class Meta:
        ordering = ['sort_order', 'id']
        verbose_name = 'Категория'
        verbose_name_plural = 'Категории'


class Dish(models.Model):
    BADGE_CHOICES = (
        ('hit', 'Хит'),
        ('chef', 'Шеф рекомендует'),
        ('favorite', 'Любимый десерт'),
    )

    category = models.ForeignKey(
        'catalog.Category', on_delete=models.PROTECT, related_name='dishes'
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    short_description = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    image = models.ImageField(upload_to='dishes/')
    badge = models.CharField(max_length=30, choices=BADGE_CHOICES, blank=True)
    is_featured = models.BooleanField(default=False)
    is_available = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = create_unique_slug(self, self.name, 'dish')
            if kwargs.get('update_fields') is not None:
                kwargs['update_fields'] = set(kwargs['update_fields']) | {'slug'}
        return super().save(*args, **kwargs)

    class Meta:
        ordering = ['sort_order', 'id']
        verbose_name = 'Блюдо'
        verbose_name_plural = 'Блюда'
        constraints = [
            CheckConstraint(condition=Q(price__gte=0), name='dish_price_non_negative')
        ]

    def clean(self):
        super().clean()
        if self.price is not None and self.price < 0:
            raise ValidationError({'price': 'Цена блюда не может быть отрицательной.'})
