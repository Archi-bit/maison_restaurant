from django.contrib import admin
from .models import Cart, CartItem



@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ('id', 'created_at', 'updated_at', 'expires_at')
    readonly_fields = ('id', 'token_hash', 'created_at', 'updated_at')
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'cart', 'dish', 'quantity')
    search_fields = ('dish__name',)
    list_filter = ('dish__category',)
    readonly_fields = ('cart', 'dish', 'quantity')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False