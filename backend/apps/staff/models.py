from django.conf import settings
from django.db import models



class EmployeeProfile(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Владелец"
        ADMINISTRATOR = "administrator", "Администратор"
        WAITER = "waiter", "Официант"
        CHEF = "chef", "Повар"
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="employee_profile")
    work_email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150)
    role = models.CharField(max_length=13, choices=Role.choices)
    phone = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.full_name
