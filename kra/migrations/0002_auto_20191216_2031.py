# Generated by Django 3.0 on 2019-12-16 20:31

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('kra', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='pod',
            name='namespace',
            field=models.CharField(default='', max_length=255),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='pod',
            name='workload',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='kra.Workload'),
        ),
    ]
