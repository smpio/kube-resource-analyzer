# Generated by Django 3.2.2 on 2021-05-29 21:59

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('kra', '0011_pod_idx'),
    ]

    operations = [
        migrations.AlterField(
            model_name='resourceusage',
            name='cpu_m_seconds',
            field=models.BigIntegerField(),
        ),
        migrations.AlterField(
            model_name='resourceusage',
            name='memory_mi',
            field=models.PositiveIntegerField(),
        ),
    ]