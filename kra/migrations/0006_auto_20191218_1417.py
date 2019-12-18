# Generated by Django 3.0 on 2019-12-18 14:17

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('kra', '0005_auto_20191218_1331'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='oomevent',
            name='comm',
        ),
        migrations.RemoveField(
            model_name='oomevent',
            name='pid',
        ),
        migrations.AddField(
            model_name='oomevent',
            name='target_comm',
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name='oomevent',
            name='target_pid',
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='oomevent',
            name='victim_comm',
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name='oomevent',
            name='victim_pid',
            field=models.BigIntegerField(blank=True, null=True),
        ),
    ]
