from rest_framework.pagination import PageNumberPagination


class DishPagination(PageNumberPagination):
    page_size = 12
    page_size_query_param = None