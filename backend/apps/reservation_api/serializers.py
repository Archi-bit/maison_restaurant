from phonenumber_field.serializerfields import PhoneNumberField
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.reservations.models import Reservation, ReservationHistory, RestaurantTable
from apps.staff.models import EmployeeProfile


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if hasattr(data, "keys"):
            unknown_fields = set(data.keys()) - set(self.fields)
            if unknown_fields:
                raise serializers.ValidationError({
                    field: ["Это поле не допускается."]
                    for field in sorted(unknown_fields)
                })
        return super().to_internal_value(data)


class PublicReservationCreateSerializer(StrictSerializer):
    guest_name = serializers.CharField(max_length=150)
    phone = PhoneNumberField(max_length=20)
    date = serializers.DateField(format="%Y-%m-%d", input_formats=["%Y-%m-%d"])
    start_time = serializers.TimeField(format="%H:%M", input_formats=["%H:%M"])
    guests_count = serializers.IntegerField(min_value=1, max_value=6)
    guest_note = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, style={"base_template": "textarea.html"}
    )


class StaffReservationCreateSerializer(PublicReservationCreateSerializer):
    source = serializers.ChoiceField(
        choices=("phone", "walk_in"), required=False, default="phone"
    )
    duration_minutes = serializers.IntegerField(
        min_value=30, max_value=360, required=False
    )
    table_id = serializers.PrimaryKeyRelatedField(
        queryset=RestaurantTable.objects.all(),
        source="table",
        required=False,
        allow_null=True,
    )

    def validate_duration_minutes(self, value):
        if value % 30:
            raise serializers.ValidationError(
                "Длительность должна быть кратна 30 минутам."
            )
        return value


class StaffReservationUpdateSerializer(StrictSerializer):
    guest_name = serializers.CharField(max_length=150, required=False)
    phone = PhoneNumberField(max_length=20, required=False)
    guest_note = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, style={"base_template": "textarea.html"}
    )
    date = serializers.DateField(
        format="%Y-%m-%d", input_formats=["%Y-%m-%d"], required=False
    )
    start_time = serializers.TimeField(
        format="%H:%M", input_formats=["%H:%M"], required=False
    )
    guests_count = serializers.IntegerField(
        min_value=1, max_value=6, required=False
    )
    duration_minutes = serializers.IntegerField(
        min_value=30, max_value=360, required=False
    )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Укажите хотя бы одно поле для изменения.")
        if (
            "duration_minutes" in attrs
            and attrs["duration_minutes"] % 30
        ):
            raise serializers.ValidationError({
                "duration_minutes": ["Длительность должна быть кратна 30 минутам."]
            })
        return attrs


class AssignTableSerializer(StrictSerializer):
    table_id = serializers.IntegerField(min_value=1)


class NoPayloadSerializer(StrictSerializer):
    pass


class StaffReservationListQuerySerializer(StrictSerializer):
    date = serializers.DateField(required=False)
    status = serializers.ChoiceField(
        choices=Reservation._meta.get_field("status").choices, required=False
    )
    search = serializers.CharField(required=False, allow_blank=True, max_length=150)
    page = serializers.IntegerField(required=False, min_value=1)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=100)


class HallPlanQuerySerializer(StrictSerializer):
    date = serializers.DateField(required=False)
    time = serializers.TimeField(
        required=False, input_formats=["%H:%M"], format="%H:%M"
    )
    duration_minutes = serializers.IntegerField(
        required=False, min_value=30, max_value=360
    )

    def validate_duration_minutes(self, value):
        if value % 30:
            raise serializers.ValidationError(
                "Длительность должна быть кратна 30 минутам."
            )
        return value


class EmployeeSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeProfile
        fields = ("id", "full_name", "work_email", "role", "phone")
        read_only_fields = fields


class RestaurantTableSerializer(serializers.ModelSerializer):
    class Meta:
        model = RestaurantTable
        fields = ("id", "code", "capacity", "zone", "is_active")
        read_only_fields = fields


class ReservationHistorySerializer(serializers.ModelSerializer):
    actor = EmployeeSummarySerializer(read_only=True)
    old_status = serializers.CharField(read_only=True)
    new_status = serializers.CharField(read_only=True)

    class Meta:
        model = ReservationHistory
        fields = (
            "id", "action", "old_status", "new_status", "details", "actor",
            "created_at",
        )
        read_only_fields = fields


class StaffReservationListSerializer(serializers.ModelSerializer):
    reservation_number = serializers.CharField(source="number", read_only=True)
    table = RestaurantTableSerializer(read_only=True)
    date = serializers.DateField(format="%Y-%m-%d", read_only=True)
    start_time = serializers.TimeField(format="%H:%M", read_only=True)
    end_time = serializers.TimeField(format="%H:%M", read_only=True)
    status = serializers.CharField(read_only=True)
    source = serializers.CharField(read_only=True)

    class Meta:
        model = Reservation
        fields = (
            "id", "reservation_number", "guest_name", "phone", "date",
            "start_time", "end_time", "guests_count", "status", "source",
            "table",
        )
        read_only_fields = fields


class StaffReservationDetailSerializer(StaffReservationListSerializer):
    responsible_employee = EmployeeSummarySerializer(read_only=True)
    created_by = EmployeeSummarySerializer(read_only=True)
    history = serializers.SerializerMethodField()

    class Meta(StaffReservationListSerializer.Meta):
        fields = StaffReservationListSerializer.Meta.fields + (
            "guest_note", "responsible_employee", "created_by", "history",
            "created_at", "updated_at",
        )
        read_only_fields = fields

    @extend_schema_field(ReservationHistorySerializer(many=True))
    def get_history(self, obj):
        history = obj.reservationhistory_set.select_related("actor").order_by(
            "created_at", "pk"
        )
        return ReservationHistorySerializer(history, many=True).data


class PublicReservationResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    reservation_number = serializers.CharField()
    status = serializers.CharField()
    message = serializers.CharField()


class ApiErrorSerializer(serializers.Serializer):
    code = serializers.CharField()
    detail = serializers.CharField()


class HallPlanTableSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()
    capacity = serializers.IntegerField()
    zone = serializers.CharField()
    is_active = serializers.BooleanField()
    status = serializers.ChoiceField(choices=("free", "reserved", "occupied"))
    reservation = serializers.DictField(allow_null=True)


class HallPlanResponseSerializer(serializers.Serializer):
    date = serializers.DateField(format="%Y-%m-%d")
    time = serializers.TimeField(format="%H:%M")
    duration_minutes = serializers.IntegerField()
    tables = HallPlanTableSerializer(many=True)
