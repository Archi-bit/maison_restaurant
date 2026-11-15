from django.urls import path

from .views import (
    AssignTableView,
    CurrentShiftTablesView,
    CurrentShiftView,
    OpenShiftView,
    ShiftEmployeesView,
)

app_name = "operations"

urlpatterns = [
    path("staff/shifts/open/", OpenShiftView.as_view(), name="shift-open"),
    path("staff/shifts/current/", CurrentShiftView.as_view(), name="shift-current"),
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
]
