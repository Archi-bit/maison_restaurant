from rest_framework import generics
from rest_framework.exceptions import ValidationError
from .serializer import *
from .pagination import *

class CategoryListView(generics.ListAPIView):
    serializer_class = CategorySerializer
    pagination_class = None
    def get_queryset(self):
        return Category.objects.filter(is_active=True).order_by("sort_order", "id")


class DishListView(generics.ListAPIView):
    serializer_class = DishListSerializer
    pagination_class = DishPagination

    def get_queryset(self):
        queryset = Dish.objects.filter(
            is_active=True, category__is_active=True
        ).select_related("category")

        search_query = self.request.query_params.get("search")
        if search_query:
            queryset = queryset.filter(name__icontains=search_query)

        category_slug = self.request.query_params.get("category")
        if category_slug:
            queryset = queryset.filter(category__slug=category_slug)

        featured_param = self.request.query_params.get("featured")
        if featured_param is not None:
            param_lower = featured_param.lower()
            if param_lower == "true":
                queryset = queryset.filter(is_featured=True)
            elif param_lower == "false":
                queryset = queryset.filter(is_featured=False)
            else:
                raise ValidationError(
                    {"featured": "Некорректное значение. Ожидается true или false."}
                )

        return queryset.order_by("sort_order", "id")


class DishDetailView(generics.RetrieveAPIView):
    serializer_class = DishDetailSerializer
    lookup_field = "slug"

    def get_queryset(self):
        return Dish.objects.filter(
            is_active=True, category__is_active=True
        ).select_related("category")