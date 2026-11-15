from django.urls import path

from .views import (
    AssignTableView,
    CloseShiftView,
    CurrentShiftTablesView,
    CurrentShiftView,
    OpenShiftView,
    PopularDishesView,
    SalesChannelsView,
    SalesComparisonView,
    SalesCSVView,
    SalesSummaryView,
    ShiftEmployeesView,
)

app_name = "operations"

urlpatterns = [
    path("staff/shifts/open/", OpenShiftView.as_view(), name="shift-open"),
    path("staff/shifts/current/", CurrentShiftView.as_view(), name="shift-current"),
    path("staff/shifts/<int:id>/close/", CloseShiftView.as_view(), name="shift-close"),
    path(
        "staff/shifts/current/tables/",
        CurrentShiftTablesView.as_view(),
        name="shift-current-tables",
    ),
    path(
        "staff/shifts/<int:id>/employees/",
        ShiftEmployeesView.as_view(),
        name="shift-employees",
    ),
    path(
        "staff/shifts/<int:id>/tables/<int:table_id>/",
        AssignTableView.as_view(),
        name="shift-assign-table",
    ),
    path("staff/reports/summary/", SalesSummaryView.as_view(), name="sales-summary"),
    path("staff/reports/popular-dishes/", PopularDishesView.as_view(), name="popular-dishes"),
    path("staff/reports/channels/", SalesChannelsView.as_view(), name="sales-channels"),
    path("staff/reports/compare/", SalesComparisonView.as_view(), name="sales-compare"),
    path("staff/reports/sales.csv", SalesCSVView.as_view(), name="sales-csv"),
]
