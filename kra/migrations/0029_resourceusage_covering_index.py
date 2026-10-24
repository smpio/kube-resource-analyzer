from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [('kra', '0028_pod_spec_hash_length')]

    operations = [
        AddIndexConcurrently(
            model_name='resourceusage',
            index=models.Index(
                fields=['container_id', 'measured_at'],
                include=['memory_mi', 'cpu_m_seconds'],
                name='kra_ru_history_cover_idx',
            ),
        ),
    ]
