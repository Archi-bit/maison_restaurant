from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from apps.reservations.models import RestaurantTable
from apps.staff.models import EmployeeProfile

from .models import RestaurantShift, ShiftEmployee, ShiftTableAssignment


PASSWORD = "Local-shift-test-42!"


def create_employee(username, role, *, is_active=True):
    user = get_user_model().objects.create_user(
        username=username, password=PASSWORD, is_active=is_active
    )
    return EmployeeProfile.objects.create(
        user=user, work_email=f"{username}@example.com", full_name=username, role=role
    )


class ShiftAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = create_employee("owner", EmployeeProfile.Role.OWNER)
        cls.administrator = create_employee("administrator", EmployeeProfile.Role.ADMINISTRATOR)
        cls.waiter = create_employee("waiter", EmployeeProfile.Role.WAITER)
        cls.other_waiter = create_employee("other_waiter", EmployeeProfile.Role.WAITER)
        cls.chef = create_employee("chef", EmployeeProfile.Role.CHEF)
        cls.inactive = create_employee(
            "inactive", EmployeeProfile.Role.WAITER, is_active=False
        )
        cls.table = RestaurantTable.objects.create(code="T05", capacity=2, zone="Зал")
        cls.other_table = RestaurantTable.objects.create(code="T06", capacity=4, zone="Зал")
        cls.inactive_table = RestaurantTable.objects.create(
            code="T07", capacity=4, zone="Зал", is_active=False
        )
        cls.open_url = reverse("operations:shift-open")
        cls.current_url = reverse("operations:shift-current")
        cls.tables_url = reverse("operations:shift-current-tables")

    def authenticate(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")

    def create_shift(self):
        return RestaurantShift.objects.create(opened_by=self.owner)

    def employees_url(self, shift_id):
        return reverse("operations:shift-employees", args=[shift_id])

    def assignment_url(self, shift_id, table_id):
        return reverse("operations:shift-assign-table", args=[shift_id, table_id])

    def test_owner_login_and_open_shift(self):
        login = self.client.post(
            reverse("staff:login"),
            {"work_email": self.owner.work_email, "password": PASSWORD},
            format="json",
        )
        self.assertEqual(login.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        me = self.client.get(reverse("staff:me"))
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data["role"], EmployeeProfile.Role.OWNER)
        self.assertEqual(self.client.get(self.current_url).data, {"shift": None})
        self.assertEqual(self.client.get(self.tables_url).data, [])

        opened = self.client.post(self.open_url, {}, format="json")
        self.assertEqual(opened.status_code, 201)
        self.assertEqual(opened.data["status"], RestaurantShift.Status.OPEN)
        self.assertEqual(opened.data["opened_by"], self.owner.pk)
        self.assertIsNone(opened.data["closed_at"])
        self.assertEqual(self.client.get(self.current_url).data, opened.data)

        duplicate = self.client.post(self.open_url, {}, format="json")
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(duplicate.data["code"], "shift_already_open")
        self.assertEqual(RestaurantShift.objects.count(), 1)

    def test_administrator_can_add_and_list_shift_employees(self):
        self.authenticate(self.administrator.user)
        shift = self.create_shift()
        url = self.employees_url(shift.pk)
        for employee in (self.waiter, self.chef):
            response = self.client.post(url, {"employee_id": employee.pk}, format="json")
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.data["employee"], employee.pk)
            self.assertNotIn("work_email", response.data)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [member["employee"] for member in response.data], [self.waiter.pk, self.chef.pk]
        )
        duplicate = self.client.post(url, {"employee_id": self.waiter.pk}, format="json")
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(duplicate.data["code"], "employee_already_added")
        inactive = self.client.post(url, {"employee_id": self.inactive.pk}, format="json")
        self.assertEqual(inactive.status_code, 400)
        self.assertEqual(inactive.data["code"], "inactive_employee")
        self.assertEqual(shift.employees.count(), 2)

    def test_assign_table_is_idempotent_and_rejects_a_second_waiter(self):
        self.authenticate(self.administrator.user)
        shift = self.create_shift()
        for waiter in (self.waiter, self.other_waiter):
            shift.employees.create(employee=waiter)
        url = self.assignment_url(shift.pk, self.table.pk)
        payload = {"waiter_id": self.waiter.pk}
        assigned = self.client.put(url, payload, format="json")
        self.assertEqual(assigned.status_code, 201)
        self.assertEqual(assigned.data["table_code"], "T05")
        self.assertEqual(assigned.data["waiter"], self.waiter.pk)
        repeated = self.client.put(url, payload, format="json")
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.data, assigned.data)
        conflict = self.client.put(url, {"waiter_id": self.other_waiter.pk}, format="json")
        self.assertEqual(conflict.status_code, 400)
        self.assertEqual(conflict.data["code"], "table_already_assigned")
        self.assertEqual(ShiftTableAssignment.objects.get().waiter_id, self.waiter.pk)

    def test_assign_table_checks_role_activity_and_membership(self):
        self.authenticate(self.owner.user)
        shift = self.create_shift()
        for employee in (self.chef, self.inactive, self.waiter):
            shift.employees.create(employee=employee)
        cases = [
            (self.table, self.chef, "invalid_waiter_role"),
            (self.table, self.other_waiter, "waiter_not_in_shift"),
            (self.table, self.inactive, "inactive_employee"),
            (self.inactive_table, self.waiter, "inactive_table"),
        ]
        for table, employee, code in cases:
            with self.subTest(code=code):
                response = self.client.put(
                    self.assignment_url(shift.pk, table.pk),
                    {"waiter_id": employee.pk},
                    format="json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data["code"], code)
        self.assertFalse(ShiftTableAssignment.objects.exists())

    def test_table_list_is_scoped_to_current_shift_and_waiter(self):
        shift = self.create_shift()
        closed = RestaurantShift.objects.create(status=RestaurantShift.Status.CLOSED)
        for assignment_shift, table, waiter in (
            (shift, self.table, self.waiter),
            (shift, self.other_table, self.other_waiter),
            (closed, self.other_table, self.waiter),
        ):
            assignment_shift.employees.create(employee=waiter)
            ShiftTableAssignment.objects.create(shift=assignment_shift, table=table, waiter=waiter)

        self.authenticate(self.waiter.user)
        response = self.client.get(self.tables_url, {"waiter_id": self.other_waiter.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["table"] for item in response.data], [self.table.pk])
        self.authenticate(self.administrator.user)
        response = self.client.get(self.tables_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["table"] for item in response.data], [self.table.pk, self.other_table.pk]
        )

    def test_jwt_and_roles_are_required(self):
        shift = self.create_shift()
        management_requests = [
            ("post", self.open_url),
            ("get", self.employees_url(shift.pk)),
            ("post", self.employees_url(shift.pk)),
            ("put", self.assignment_url(shift.pk, self.table.pk)),
        ]
        for method, url in [
            *management_requests, ("get", self.current_url), ("get", self.tables_url)
        ]:
            with self.subTest(method=method, url=url):
                self.assertEqual(getattr(self.client, method)(url).status_code, 401)

        for employee in (self.waiter, self.chef):
            self.authenticate(employee.user)
            self.assertEqual(self.client.get(self.current_url).status_code, 200)
            for method, url in management_requests:
                with self.subTest(role=employee.role, method=method, url=url):
                    self.assertEqual(getattr(self.client, method)(url).status_code, 403)
        self.assertEqual(self.client.get(self.tables_url).status_code, 403)

        user_without_profile = get_user_model().objects.create_user(username="no_profile")
        self.authenticate(user_without_profile)
        self.assertEqual(self.client.get(self.current_url).status_code, 403)
        self.authenticate(self.waiter.user)
        self.waiter.user.is_active = False
        self.waiter.user.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(self.current_url).status_code, 401)

    def test_closed_shift_rejects_members_and_assignments(self):
        self.authenticate(self.owner.user)
        shift = RestaurantShift.objects.create(status=RestaurantShift.Status.CLOSED)
        member = self.client.post(
            self.employees_url(shift.pk), {"employee_id": self.waiter.pk}, format="json"
        )
        assignment = self.client.put(
            self.assignment_url(shift.pk, self.table.pk),
            {"waiter_id": self.waiter.pk},
            format="json",
        )
        for response in (member, assignment):
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.data["code"], "shift_closed")

    def test_missing_objects_and_invalid_employee_id(self):
        self.authenticate(self.owner.user)
        shift = self.create_shift()
        self.assertEqual(self.client.get(self.employees_url(shift.pk + 1)).status_code, 404)
        missing_employee = self.client.post(
            self.employees_url(shift.pk), {"employee_id": 999999}, format="json"
        )
        missing_table = self.client.put(
            self.assignment_url(shift.pk, 999999), {"waiter_id": self.waiter.pk},
            format="json",
        )
        invalid_employee = self.client.post(
            self.employees_url(shift.pk), {"employee_id": 0}, format="json"
        )
        self.assertEqual(missing_employee.status_code, 404)
        self.assertEqual(missing_table.status_code, 404)
        self.assertEqual(invalid_employee.status_code, 400)

    def test_database_constraints(self):
        shift = self.create_shift()
        shift.employees.create(employee=self.waiter)
        ShiftTableAssignment.objects.create(shift=shift, table=self.table, waiter=self.waiter)
        with self.assertRaises(IntegrityError), transaction.atomic():
            RestaurantShift.objects.create()
        with self.assertRaises(IntegrityError), transaction.atomic():
            ShiftEmployee.objects.create(shift=shift, employee=self.waiter)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ShiftTableAssignment.objects.create(
                shift=shift, table=self.table, waiter=self.other_waiter
            )
