import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("reservations", "0001_initial"),
        ("staff", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="reservation",
            name="table",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="reservations.restauranttable",
            ),
        ),
        migrations.AddField(
            model_name="reservation",
            name="responsible_employee",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="responsible_reservations",
                to="staff.employeeprofile",
            ),
        ),
        migrations.AddField(
            model_name="reservation",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="created_reservations",
                to="staff.employeeprofile",
            ),
        ),
        migrations.AddField(
            model_name="reservationhistory",
            name="actor",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="staff.employeeprofile",
            ),
        ),
    ]
