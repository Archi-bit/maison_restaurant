from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('catalog', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='category',
            name='slug',
            field=models.SlugField(blank=True, max_length=120, unique=True),
        ),
        migrations.AlterField(
            model_name='dish',
            name='slug',
            field=models.SlugField(blank=True, max_length=220, unique=True),
        ),
    ]
