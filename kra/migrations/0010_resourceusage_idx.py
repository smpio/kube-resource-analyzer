# Generated by Django 3.2.2 on 2021-05-27 15:31

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('kra', '0009_clean_models'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='resourceusage',
            index=models.Index(fields=['container_id', 'measured_at'], name='kra_resourc_contain_4085bf_idx'),
        ),
    ]
