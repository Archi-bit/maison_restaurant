from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import generics
from rest_framework.exceptions import ValidationError as DRFValidationError

from .models import Category, Dish
from .pagination import DishPagination
from .serializers import CategorySerializer, DishDetailSerializer, DishListSerializer


@extend_schema_view(
    get=extend_schema(
        summary='Активные категории',
        responses={200: CategorySerializer(many=True)},
    ),
)
class CategoryListView(generics.ListAPIView):
    serializer_class = CategorySerializer
    pagination_class = None

    def get_queryset(self):
        return Category.objects.filter(is_active=True).order_by('sort_order', 'id')


@extend_schema_view(
    get=extend_schema(
        summary='Список блюд',
        parameters=[
            OpenApiParameter(name='search', type=str, description='Поиск по названию'),
            OpenApiParameter(name='category', type=str, description='Slug категории'),
            OpenApiParameter(name='featured', type=bool, description='true/false'),
        ],
        responses={
            200: DishListSerializer(many=True),
            400: OpenApiResponse(
                response=OpenApiTypes.OBJECT,
                description='Некорректный параметр featured или номер страницы.',
                examples=[
                    OpenApiExample(
                        'Некорректный featured',
                        value={'featured': ['Некорректное значение. Ожидается true или false.']},
                        response_only=True,
                        status_codes=['400'],
                    ),
                ],
            ),
        },
    ),
)
class DishListView(generics.ListAPIView):
    serializer_class = DishListSerializer
    pagination_class = DishPagination

    def get_queryset(self):
        queryset = Dish.objects.filter(
            is_active=True, category__is_active=True,
        ).select_related('category').order_by('sort_order', 'id')

        search_query = self.request.query_params.get('search')
        if search_query:
            queryset = queryset.filter(name__icontains=search_query)

        category_slug = self.request.query_params.get('category')
        if category_slug:
            queryset = queryset.filter(category__slug=category_slug)

        featured = self.request.query_params.get('featured')
        if featured is not None:
            if featured.lower() == 'true':
                queryset = queryset.filter(is_featured=True)
            elif featured.lower() == 'false':
                queryset = queryset.filter(is_featured=False)
            else:
                raise DRFValidationError(
                    {'featured': 'Некорректное значение. Ожидается true или false.'}
                )

        return queryset


@extend_schema_view(
    get=extend_schema(
        summary='Детали блюда',
        responses={
            200: DishDetailSerializer,
            404: OpenApiResponse(
                response=OpenApiTypes.OBJECT,
                description='Блюдо не найдено, скрыто или его категория неактивна.',
                examples=[
                    OpenApiExample(
                        'Блюдо не найдено',
                        value={'detail': 'No Dish matches the given query.'},
                        response_only=True,
                        status_codes=['404'],
                    ),
                ],
            ),
        },
    ),
)
class DishDetailView(generics.RetrieveAPIView):
    serializer_class = DishDetailSerializer
    lookup_field = 'slug'

    def get_queryset(self):
        return Dish.objects.filter(
            is_active=True, category__is_active=True,
        ).select_related('category')
