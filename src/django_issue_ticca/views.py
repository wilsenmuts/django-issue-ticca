from django.core.paginator import InvalidPage, Paginator
from django.db.models import Count
from django.http import JsonResponse
from django.views import View

from .check.database import check_database
from .check.health import available_components, run_health_checks
from .middleware import user_counter
from .models import IncidentStatus, monitoring_table
from .stats import hourly_user_stats


class DatabaseProbeView(View):
    """Single-subsystem database health check (kept for backwards compat)."""

    def get(self, request):
        result = check_database()
        if result.get('status') != 'healthy':
            return JsonResponse(result, status=503)
        return JsonResponse(result, status=200)


class SystemHealthView(View):
    """
    Overall system health: aggregates every configured subsystem.

    ``GET /health/``                     -> full report
    ``GET /health/?component=database``  -> a single component
    ``GET /health/?component=redis,celery``

    Responds 200 when healthy, 503 when any configured component is failing.
    """

    def get(self, request):
        raw = request.GET.get('component')
        components = None
        if raw:
            components = [part.strip() for part in raw.split(',') if part.strip()]
            unknown = [c for c in components if c not in available_components()]
            if unknown:
                return JsonResponse(
                    {
                        'error': f'Unknown component(s): {", ".join(unknown)}',
                        'available': available_components(),
                    },
                    status=400,
                )

        report = run_health_checks(components)
        status_code = 200 if report['status'] == 'healthy' else 503
        return JsonResponse(report, status=status_code)


class MonitoringTableView(View):
    """Retrieve monitoring/incident records with pagination and filtering."""

    def get(self, request):
        try:
            page = int(request.GET.get('page', 1))
            page_size = int(request.GET.get('page_size', 10))
        except (TypeError, ValueError):
            return JsonResponse(
                {'error': 'page and page_size must be integers'},
                status=400,
            )

        # Guard against unreasonable page sizes
        page_size = max(1, min(page_size, 100))

        queryset = monitoring_table.objects.all()

        status = request.GET.get('status')
        if status in IncidentStatus.values:
            queryset = queryset.filter(status=status)

        kind = request.GET.get('kind')
        if kind:
            queryset = queryset.filter(kind=kind)

        method = request.GET.get('method')
        if method:
            queryset = queryset.filter(affected_method=method)

        paginator = Paginator(queryset.values(), page_size)

        try:
            page_obj = paginator.page(page)
        except InvalidPage:
            return JsonResponse(
                {'error': f'Invalid page. Valid range: 1-{paginator.num_pages}'},
                status=404,
            )

        return JsonResponse(
            {
                'count': paginator.count,
                'num_pages': paginator.num_pages,
                'current_page': page_obj.number,
                'page_size': page_size,
                'has_next': page_obj.has_next(),
                'has_previous': page_obj.has_previous(),
                'results': list(page_obj.object_list),
            },
            safe=False,
            status=200,
        )


class OpenByTypeView(View):
    """Count open incidents grouped by exception_type."""

    def get(self, request):
        results = (
            monitoring_table.objects
            .filter(status=IncidentStatus.OPEN)
            .values('exception_type')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        return JsonResponse(
            {'total_open': sum(r['count'] for r in results), 'data': list(results)},
            safe=False,
            status=200,
        )


class OpenByMethodView(View):
    """Count open incidents grouped by affected_method (URL)."""

    def get(self, request):
        results = (
            monitoring_table.objects
            .filter(status=IncidentStatus.OPEN)
            .values('affected_method')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        return JsonResponse(
            {'total_open': sum(r['count'] for r in results), 'data': list(results)},
            safe=False,
            status=200,
        )


class UserStatsView(View):
    def get(self, request):
        return JsonResponse(user_counter.snapshot(), status=200)


class HourlyUserStatsView(View):
    """
    Unique users per hour for the last N days (default 7, from settings).

    ``GET /stats/users/hourly/``         -> last 7 days
    ``GET /stats/users/hourly/?days=2``  -> last 2 days

    Older stats are always pruned when this endpoint is called; the number of
    rows removed is reported as ``pruned``.
    """

    def get(self, request):
        raw = request.GET.get('days')
        days = None
        if raw is not None and raw != '':
            try:
                days = int(raw)
            except (TypeError, ValueError):
                return JsonResponse({'error': 'days must be an integer'}, status=400)
            if not 1 <= days <= 90:
                return JsonResponse(
                    {'error': 'days must be between 1 and 90'}, status=400
                )

        return JsonResponse(hourly_user_stats(days=days), status=200)