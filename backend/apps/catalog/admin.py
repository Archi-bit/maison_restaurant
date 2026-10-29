from django.contrib import admin
from .models import Catalog, Dish, Category


@admin.register(Catalog)
class MenuAdmin(admin.ModelAdmin):
    list_display = ('title', )

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'slug', 'sort_order', 'is_active')
    search_fields = ('name', 'slug')
    list_filter = ('is_active',)
    list_editable = ('sort_order', 'is_active')
    ordering = ('sort_order', 'id')

@admin.register(Dish)
class DishAdmin(admin.ModelAdmin):
    list_display = ('id','name','category','price','is_available','is_featured','is_active','sort_order')
    search_fields = ('name', 'slug', 'description')
    list_filter = ('category','is_available','is_featured','is_active')
    list_editable = ('price','is_available','is_featured','is_active','sort_order')
    ordering = ('sort_order', 'id')