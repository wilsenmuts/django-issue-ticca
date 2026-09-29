import django_issue_ticca.models
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='database_probe',
            fields=[
                ('id', models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False,
                    verbose_name='ID')),
                ('probe_name', models.CharField(db_index=True, max_length=100)),
                ('probe_status', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Database Probe',
                'verbose_name_plural': 'Database Probes',
                'db_table': 'issue_ticca_database_probe_x',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='monitoring_table',
            fields=[
                ('id', models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False,
                    verbose_name='ID')),
                ('kind', models.CharField(
                    choices=[
                        ('exception', 'Exception'),
                        ('slow_response', 'Slow response'),
                    ],
                    db_index=True, default='exception', max_length=20)),
                ('exception_type', models.CharField(db_index=True, max_length=200)),
                ('affected_method', models.CharField(db_index=True, max_length=255)),
                ('exception_message', models.CharField(
                    blank=True, default='', max_length=500)),
                ('incident_id', models.CharField(
                    default=django_issue_ticca.models.generate_incident_id,
                    editable=False, max_length=64, unique=True)),
                ('status', models.CharField(
                    choices=[('open', 'Open'), ('closed', 'Closed')],
                    db_index=True, default='open', max_length=20)),
                ('exception_traceback', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('last_noticed_at', models.DateTimeField(blank=True, null=True)),
                ('closed_at', models.DateTimeField(blank=True, null=True)),
                ('calls_before_closure', models.IntegerField(default=0)),
            ],
            options={
                'verbose_name': 'Monitoring Table',
                'verbose_name_plural': 'Monitoring Tables',
                'db_table': 'issue_ticca_monitoring_table_x',
                'ordering': ['-created_at'],
            },
        ),
    ]
