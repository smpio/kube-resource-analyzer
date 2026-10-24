from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('kra', '0026_adjustment_resource_version_and_active_constraint')]

    operations = [
        migrations.AddField(
            model_name='container',
            name='oom_killed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
