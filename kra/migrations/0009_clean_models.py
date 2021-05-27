# Generated by Django 3.2.2 on 2021-05-27 12:43

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('kra', '0008_instancesummary'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='resourceusage',
            name='cpu_m',
        ),
        migrations.AlterField(
            model_name='summary',
            name='avg_cpu_m',
            field=models.PositiveIntegerField(),
        ),
        migrations.AlterField(
            model_name='summary',
            name='max_memory_mi',
            field=models.PositiveIntegerField(),
        ),
    ]
