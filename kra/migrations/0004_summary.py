# Generated by Django 3.0 on 2020-01-09 14:18

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('kra', '0003_suggestion'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='Investigation',
            new_name='Summary',
        ),
    ]