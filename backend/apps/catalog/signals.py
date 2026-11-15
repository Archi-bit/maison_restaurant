from django.db.models.signals import pre_save
from django.dispatch import receiver
from .models import Category, Dish
from .slug_utils import create_unique_slug


@receiver(pre_save, sender=Category)
def category_pre_save(sender, instance, **kwargs):
    if not instance.slug:
        instance.slug = create_unique_slug(instance, instance.name, 'category')


@receiver(pre_save, sender=Dish)
def dish_pre_save(sender, instance, **kwargs):
    if not instance.slug:
        instance.slug = create_unique_slug(instance, instance.name, 'dish')
