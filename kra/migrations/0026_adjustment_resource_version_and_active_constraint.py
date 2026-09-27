from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ('kra', '0025_oomevent_is_ignored'),
    ]

    operations = [
        migrations.AddField(
            model_name='adjustment',
            name='resource_version',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddConstraint(
            model_name='adjustment',
            constraint=models.UniqueConstraint(
                condition=Q(result__isnull=True),
                fields=('workload',),
                name='kra_one_active_adjustment_per_workload',
            ),
        ),
    ]
