from django.contrib import admin

from django_issue_ticca.models import (
    IncidentStatus,
    database_probe,
    hourly_user_stat,
    monitoring_table,
)
from django_issue_ticca.stats import prune_hourly_stats

admin.site.site_header = "Django Issue Ticca Administration"
admin.site.index_title = "Django Issue Ticca Administration"
admin.site.site_title = "Django Issue Ticca Administration"


@admin.register(database_probe)
class DatabaseProbeAdmin(admin.ModelAdmin):
    list_display = ('probe_name', 'probe_status', 'created_at', 'updated_at')
    list_filter = ('probe_status',)
    search_fields = ('probe_name',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(monitoring_table)
class MonitoringTableAdmin(admin.ModelAdmin):
    list_display = (
        'incident_id',
        'kind',
        'exception_type',
        'affected_method',
        'status',
        'calls_before_closure',
        'created_at',
        'last_noticed_at',
        'closed_at',
    )
    list_filter = ('status', 'kind', 'exception_type')
    search_fields = (
        'incident_id',
        'exception_type',
        'affected_method',
        'exception_message',
    )
    readonly_fields = ('incident_id', 'created_at', 'last_noticed_at', 'closed_at')
    date_hierarchy = 'created_at'
    list_select_related = False
    actions = ('close_selected',)

    @admin.action(description='Close selected open incidents')
    def close_selected(self, request, queryset):
        closed = 0
        for incident in queryset.filter(status=IncidentStatus.OPEN):
            incident.close()
            closed += 1
        self.message_user(request, f"Closed {closed} incident(s).")


@admin.register(hourly_user_stat)
class HourlyUserStatAdmin(admin.ModelAdmin):
    list_display = ('hour_start', 'user_key', 'requests', 'last_seen_at')
    list_filter = ('hour_start',)
    search_fields = ('user_key',)
    date_hierarchy = 'hour_start'
    readonly_fields = ('created_at', 'last_seen_at')
    actions = ('prune_older_than_retention',)

    @admin.action(description='Prune stats older than the retention window')
    def prune_older_than_retention(self, request, queryset):
        deleted = prune_hourly_stats()
        self.message_user(request, f"Pruned {deleted} hourly stat row(s).")