from rest_framework import serializers
from .models import Category, Dish


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'slug']


class DishListSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)

    class Meta:
        model = Dish
        fields = ['id', 'name', 'slug', 'short_description', 'price', 'image', 'badge', 'is_featured', 'is_available', 'category']


class DishDetailSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)

    class Meta:
        model = Dish
        fields = ['id', 'name', 'slug', 'short_description', 'description', 'price', 'image', 'badge', 'is_featured', 'is_available', 'category']