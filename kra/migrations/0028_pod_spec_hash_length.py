from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('kra', '0027_container_oom_killed_at')]

    operations = [
        migrations.AlterField(
            model_name='pod',
            name='spec_hash',
            field=models.CharField(max_length=63),
        ),
    ]
