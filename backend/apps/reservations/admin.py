"""Админка не должна обходить бизнес-правила.

* статус меняется только действиями confirm / arrived / cancel (через сервисы);
* создание и редактирование брони идёт через create_staff_reservation / update_reservation;
* брони и столы не удаляются (бронь отменяют, стол деактивируют);
* история изменений доступна только для чтения.
"""
from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect

from .models import Reservation, ReservationHistory, RestaurantTable
from .services import (
    ReservationBusinessError,
    cancel_reservation,
    confirm_reservation,
    create_staff_reservation,
    mark_arrived,
    update_reservation,
)
from .services.availability import (
    ACTIVE_STATUSES,
    ensure_table_available,
    now_local,
    validate_visit_window,
)
from .services.reservation_service import EDITABLE_FIELDS, EDITABLE_STATUSES

# Возможные имена связи User -> staff.EmployeeProfile. Проверить после появления модуля staff.
_PROFILE_ATTRS = ("employee_profile", "employeeprofile")


def get_actor(request):
    """staff.EmployeeProfile текущего пользователя или None (например, суперпользователь без профиля)."""
    for attr in _PROFILE_ATTRS:
        profile = getattr(request.user, attr, None)
        if profile is not None:
            return profile
    return None


# ---------- столы ----------

class RestaurantTableForm(forms.ModelForm):
    class Meta:
        model = RestaurantTable
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        if not self.instance.pk or self.errors:
            return cleaned
        upcoming = Reservation.objects.filter(
            table=self.instance, status__in=ACTIVE_STATUSES, date__gte=now_local().date()
        )
        if not cleaned.get("is_active", True) and upcoming.exists():
            raise ValidationError("Нельзя отключить стол: на нём есть активные будущие брони")
        capacity = cleaned.get("capacity")
        if capacity is not None and upcoming.filter(guests_count__gt=capacity).exists():
            raise ValidationError("Нельзя уменьшить вместимость: есть брони на большее число гостей")
        return cleaned


@admin.register(RestaurantTable)
class RestaurantTableAdmin(admin.ModelAdmin):
    form = RestaurantTableForm
    list_display = ("code", "capacity", "zone", "is_active")
    list_filter = ("zone", "is_active")
    search_fields = ("code",)
    ordering = ("sort_order", "code")

    def has_delete_permission(self, request, obj=None):
        return False  # столы деактивируют, а не удаляют


# ---------- брони ----------

class ReservationAdminForm(forms.ModelForm):
    class Meta:
        model = Reservation
        fields = (
            "guest_name", "phone", "guest_note", "date", "start_time", "end_time",
            "guests_count", "source", "table", "responsible_employee",
        )

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        inst = self.instance
        creating = inst.pk is None
        if not creating and inst.status not in EDITABLE_STATUSES:
            raise ValidationError("Бронь в статусе arrived или cancelled изменять нельзя")

        def value(name):
            return cleaned[name] if name in cleaned else getattr(inst, name)

        source = value("source")
        if creating and source not in (Reservation.Source.PHONE, Reservation.Source.WALK_IN):
            raise ValidationError("В админке можно создавать только брони phone или walk_in")

        time_fields_changed = any(f in self.changed_data for f in ("date", "start_time", "end_time"))
        check_future = (
            (source != Reservation.Source.WALK_IN) if creating else time_fields_changed
        )
        table = value("table")
        try:
            validate_visit_window(
                date=value("date"), start_time=value("start_time"), end_time=value("end_time"),
                guests_count=value("guests_count"), check_future=check_future,
            )
            relevant = creating or time_fields_changed or any(
                f in self.changed_data for f in ("table", "guests_count")
            )
            if table is not None and relevant:
                # предварительная проверка; окончательная — под блокировкой в сервисе
                ensure_table_available(
                    table=table, date=value("date"), start_time=value("start_time"),
                    end_time=value("end_time"), guests_count=value("guests_count"),
                    exclude_reservation_id=inst.pk,
                )
        except ReservationBusinessError as exc:
            raise ValidationError(exc.message, code=exc.code)
        return cleaned


class ReservationHistoryInline(admin.TabularInline):
    model = ReservationHistory
    extra = 0
    can_delete = False
    fields = ("created_at", "action", "old_status", "new_status", "actor", "details")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    form = ReservationAdminForm
    inlines = [ReservationHistoryInline]
    actions = ["action_confirm", "action_arrived", "action_cancel"]
    list_display = (
        "number_display", "guest_name", "phone", "date", "start_time", "end_time",
        "table", "status", "source", "responsible_employee",
    )
    list_filter = ("date", "status", "source")
    search_fields = ("guest_name", "phone")
    list_select_related = ("table", "responsible_employee")
    date_hierarchy = "date"

    @admin.display(description="Номер", ordering="id")
    def number_display(self, obj):
        return obj.number

    # --- какие поля можно трогать ---

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        always = ("source", "status", "created_by", "created_at", "updated_at")
        if obj.status not in EDITABLE_STATUSES:
            return always + tuple(ReservationAdminForm.Meta.fields)
        return always

    def get_fields(self, request, obj=None):
        fields = list(ReservationAdminForm.Meta.fields)
        if obj is not None:
            fields += ["status", "created_by", "created_at", "updated_at"]
        return fields

    def has_delete_permission(self, request, obj=None):
        return False  # бронь отменяют, а не удаляют

    # --- сохранение только через сервисы ---

    def save_model(self, request, obj, form, change):
        actor = get_actor(request)
        if change:
            data = {f: form.cleaned_data[f] for f in form.changed_data if f in EDITABLE_FIELDS}
            if data:
                update_reservation(reservation=obj, validated_data=data, actor=actor)
            obj.refresh_from_db()
        else:
            created = create_staff_reservation(validated_data=dict(form.cleaned_data), actor=actor)
            obj.pk = created.pk
            obj.refresh_from_db()

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        # Если окончательная проверка в сервисе провалилась (гонка), транзакция админки
        # откатывается, а пользователь видит понятное сообщение.
        try:
            return super().changeform_view(request, object_id, form_url, extra_context)
        except ReservationBusinessError as exc:
            self.message_user(request, exc.message, messages.ERROR)
            return HttpResponseRedirect(request.get_full_path())

    # --- смена статусов ---

    def _run(self, request, queryset, func, done_text):
        actor = get_actor(request)
        done = 0
        for reservation in queryset:
            try:
                func(reservation=reservation, actor=actor)
                done += 1
            except ReservationBusinessError as exc:
                self.message_user(request, f"{reservation.number}: {exc.message}", messages.ERROR)
        if done:
            self.message_user(request, f"{done_text}: {done}", messages.SUCCESS)

    @admin.action(description="Подтвердить выбранные брони")
    def action_confirm(self, request, queryset):
        self._run(request, queryset, confirm_reservation, "Подтверждено")

    @admin.action(description="Отметить: гость пришёл")
    def action_arrived(self, request, queryset):
        self._run(request, queryset, mark_arrived, "Отмечено прибытие")

    @admin.action(description="Отменить выбранные брони")
    def action_cancel(self, request, queryset):
        self._run(request, queryset, cancel_reservation, "Отменено")


@admin.register(ReservationHistory)
class ReservationHistoryAdmin(admin.ModelAdmin):
    list_display = ("reservation", "action", "old_status", "new_status", "actor", "created_at")
    list_filter = ("action",)
    search_fields = ("reservation__guest_name",)
    list_select_related = ("reservation", "actor")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
