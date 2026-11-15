from django.urls import path

from .views import (
    ArriveReservationView,
    AssignTableView,
    CancelReservationView,
    ConfirmReservationView,
    HallPlanView,
    PublicReservationCreateView,
    ReservationHistoryView,
    StaffReservationDetailView,
    StaffReservationListCreateView,
)

app_name = "reservation_api"

urlpatterns = [
    path(
        "reservations/",
        PublicReservationCreateView.as_view(),
        name="public-reservation-create",
    ),
    path(
        "staff/reservations/",
        StaffReservationListCreateView.as_view(),
        name="staff-reservation-list",
    ),
    path(
        "staff/reservations/<int:id>/",
        StaffReservationDetailView.as_view(),
        name="staff-reservation-detail",
    ),
    path(
        "staff/reservations/<int:id>/confirm/",
        ConfirmReservationView.as_view(),
        name="staff-reservation-confirm",
    ),
    path(
        "staff/reservations/<int:id>/arrive/",
        ArriveReservationView.as_view(),
        name="staff-reservation-arrive",
    ),
    path(
        "staff/reservations/<int:id>/cancel/",
        CancelReservationView.as_view(),
        name="staff-reservation-cancel",
    ),
    path(
        "staff/reservations/<int:id>/assign-table/",
        AssignTableView.as_view(),
        name="staff-reservation-assign-table",
    ),
    path(
        "staff/reservations/<int:id>/history/",
        ReservationHistoryView.as_view(),
        name="staff-reservation-history",
    ),
    path("staff/tables/", HallPlanView.as_view(), name="staff-table-plan"),
]
