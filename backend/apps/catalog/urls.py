from rest_framework import routers
from .views import CategoryListView, DishDetailView, DishListView
from django.urls import path, include

router = routers.DefaultRouter()

urlpatterns = [
    path('', include(router.urls)),
    path('categories/', CategoryListView.as_view()),
    path('dishes/', DishListView.as_view()),
    path('dishes/<slug:slug>/', DishDetailView.as_view()),
]