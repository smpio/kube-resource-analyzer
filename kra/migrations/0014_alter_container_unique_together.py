# Generated by Django 3.2.2 on 2021-05-30 03:11

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('kra', '0013_container_started_at'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='container',
            unique_together={('pod', 'runtime_id')},
        ),
    ]
