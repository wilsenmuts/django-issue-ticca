import json
from datetime import timedelta
from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from .check.health import CHECKS, normalize_status, run_health_checks
from .context import clear_current_request, set_current_request
from .exceptions import TrackedException
from .incidents import log_exception, log_incident, resolve_method
from .middleware import (
    ExceptionLoggingMiddleware,
    ResponseTimeLoggingMiddleware,
)
from .models import (
    IncidentKind,
    IncidentStatus,
    generate_incident_id,
    hourly_user_stat,
    monitoring_table,
)
from .stats import prune_hourly_stats, record_hourly_user
from .tracking.exceptions import issue_ticca_exception_handler
from .views import HourlyUserStatsView, SystemHealthView


class PaymentGatewayError(TrackedException):
    """Example tracked exception used by the tests."""


class GenerateIncidentIdTests(TestCase):
    def test_format_and_uniqueness(self):
        first = generate_incident_id()
        second = generate_incident_id()
        self.assertRegex(first, r'^INC-\d{8}-[0-9A-F]{8}$')
        self.assertNotEqual(first, second)


class IncidentLifecycleTests(TestCase):
    def test_incident_id_is_generated_and_unique(self):
        incident, created = log_incident(
            kind=IncidentKind.EXCEPTION,
            exception_type='ValueError',
            affected_method='/api/orders/',
            message='boom',
        )
        self.assertTrue(created)
        self.assertTrue(incident.incident_id)
        self.assertEqual(incident.status, IncidentStatus.OPEN)
        self.assertEqual(incident.calls_before_closure, 1)

    def test_recurrence_increments_instead_of_inserting(self):
        for _ in range(3):
            incident, _created = log_incident(
                kind=IncidentKind.EXCEPTION,
                exception_type='ValueError',
                affected_method='/api/orders/',
                message='boom',
            )

        self.assertEqual(monitoring_table.objects.count(), 1)
        self.assertEqual(incident.calls_before_closure, 3)
        self.assertIsNotNone(incident.last_noticed_at)

    def test_different_methods_get_separate_incidents(self):
        log_incident(
            kind=IncidentKind.EXCEPTION, exception_type='ValueError',
            affected_method='/a/', message='x',
        )
        log_incident(
            kind=IncidentKind.EXCEPTION, exception_type='ValueError',
            affected_method='/b/', message='x',
        )
        self.assertEqual(monitoring_table.objects.count(), 2)

    def test_resolve_closes_open_incidents(self):
        log_incident(
            kind=IncidentKind.EXCEPTION, exception_type='ValueError',
            affected_method='/a/', message='x',
        )
        resolved = resolve_method('/a/')
        self.assertEqual(len(resolved), 1)

        incident = monitoring_table.objects.get()
        self.assertEqual(incident.status, IncidentStatus.CLOSED)
        self.assertIsNotNone(incident.closed_at)

    def test_reopen_after_resolution_creates_new_incident(self):
        first, _ = log_incident(
            kind=IncidentKind.EXCEPTION, exception_type='ValueError',
            affected_method='/a/', message='x',
        )
        resolve_method('/a/')
        second, created = log_incident(
            kind=IncidentKind.EXCEPTION, exception_type='ValueError',
            affected_method='/a/', message='x',
        )
        self.assertTrue(created)
        self.assertNotEqual(first.incident_id, second.incident_id)
        self.assertEqual(monitoring_table.objects.count(), 2)


class ExceptionMiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = ExceptionLoggingMiddleware(lambda request: HttpResponse())

    def test_process_exception_records_and_increments(self):
        request = self.factory.get('/api/orders/')
        exc = ValueError('boom')

        for _ in range(2):
            self.middleware.process_exception(request, exc)

        incident = monitoring_table.objects.get()
        self.assertEqual(incident.kind, IncidentKind.EXCEPTION)
        self.assertEqual(incident.exception_type, 'ValueError')
        self.assertEqual(incident.affected_method, '/api/orders/')
        self.assertEqual(incident.calls_before_closure, 2)
        self.assertTrue(request._issue_ticca_exception)

    def test_log_exception_uses_request_path_not_query_string(self):
        request = self.factory.get('/api/orders/?token=secret')
        log_exception(request, ValueError('boom'))
        self.assertEqual(monitoring_table.objects.get().affected_method, '/api/orders/')


@override_settings(ISSUE_TICCA={'SLOW_RESPONSE_THRESHOLD': 1e-9, 'ENABLED': True})
class SlowResponseMiddlewareTests(TestCase):
    def test_slow_request_is_recorded_and_fast_request_resolves(self):
        middleware = ResponseTimeLoggingMiddleware(lambda request: HttpResponse())

        request = self.factory_get('/slow/')
        middleware(request)

        incident = monitoring_table.objects.get()
        self.assertEqual(incident.kind, IncidentKind.SLOW_RESPONSE)
        self.assertEqual(incident.affected_method, '/slow/')
        self.assertEqual(incident.calls_before_closure, 1)

        # Now a fast request to the same URL should close the incident.
        with override_settings(ISSUE_TICCA={'SLOW_RESPONSE_THRESHOLD': 0, 'ENABLED': True}):
            middleware(self.factory_get('/slow/'))

        incident.refresh_from_db()
        self.assertEqual(incident.status, IncidentStatus.CLOSED)

    @staticmethod
    def factory_get(path):
        return RequestFactory().get(path)


class SystemHealthViewTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.view = SystemHealthView.as_view()

    def test_health_view_returns_report(self):
        response = self.view(self.factory.get('/health/'))
        self.assertIn(response.status_code, (200, 503))
        body = json.loads(response.content)
        self.assertIn(body['status'], ('healthy', 'unhealthy'))
        self.assertIn('database', body['components'])

    def test_health_view_rejects_unknown_component(self):
        response = self.view(self.factory.get('/health/', {'component': 'nope'}))
        self.assertEqual(response.status_code, 400)


class MonitoringTableModelTests(TestCase):
    def test_occurrence_and_close_helpers(self):
        incident = monitoring_table.objects.create(
            kind=IncidentKind.EXCEPTION,
            exception_type='ValueError',
            affected_method='/a/',
            exception_message='x',
        )
        self.assertEqual(incident.occurrence(), 1)
        self.assertTrue(incident.is_open)
        incident.close()
        self.assertFalse(incident.is_open)
        self.assertEqual(incident.status, IncidentStatus.CLOSED)


class HourlyUserStatsTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.view = HourlyUserStatsView.as_view()

    def test_records_one_row_per_hour_and_counts_requests(self):
        now = timezone.now()
        record_hourly_user(None, session_key='abc', when=now)
        record_hourly_user(None, session_key='abc', when=now)
        record_hourly_user(None, session_key='def', when=now)

        self.assertEqual(hourly_user_stat.objects.count(), 2)
        self.assertEqual(hourly_user_stat.objects.get(user_key='s:abc').requests, 2)
        self.assertEqual(hourly_user_stat.objects.get(user_key='s:def').requests, 1)

    def test_separate_hours_create_separate_rows(self):
        now = timezone.now()
        record_hourly_user(None, session_key='abc', when=now)
        record_hourly_user(None, session_key='abc', when=now - timedelta(hours=1))
        self.assertEqual(hourly_user_stat.objects.count(), 2)

    def test_authenticated_and_anonymous_get_distinct_keys(self):
        from django.contrib.auth.models import User

        user = User.objects.create_user(username='alice', password='x')
        record_hourly_user(user)
        record_hourly_user(None, session_key='sess')

        keys = set(hourly_user_stat.objects.values_list('user_key', flat=True))
        self.assertEqual(keys, {f'u:{user.pk}', 's:sess'})

    def test_endpoint_prunes_rows_older_than_retention(self):
        now = timezone.now()
        record_hourly_user(None, session_key='old', when=now - timedelta(days=30))
        record_hourly_user(None, session_key='new', when=now)
        self.assertEqual(hourly_user_stat.objects.count(), 2)

        response = self.view(self.factory.get('/stats/users/hourly/'))
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)

        self.assertGreaterEqual(body['pruned'], 1)
        self.assertEqual(hourly_user_stat.objects.count(), 1)
        self.assertEqual(body['totals']['unique_users'], 1)
        self.assertEqual(body['totals']['requests'], 1)
        self.assertEqual(len(body['buckets']), 1)
        self.assertEqual(body['buckets'][0]['unique_users'], 1)

    def test_prune_defaults_to_seven_days(self):
        now = timezone.now()
        record_hourly_user(None, session_key='old', when=now - timedelta(days=8))
        record_hourly_user(None, session_key='recent', when=now - timedelta(days=1))

        self.assertEqual(prune_hourly_stats(), 1)
        self.assertEqual(hourly_user_stat.objects.count(), 1)

    def test_endpoint_rejects_invalid_days(self):
        for value in ('abc', '0', '999'):
            response = self.view(
                self.factory.get('/stats/users/hourly/', {'days': value})
            )
            self.assertEqual(response.status_code, 400)

    def test_recording_can_be_disabled(self):
        with override_settings(ISSUE_TICCA={'TRACK_HOURLY_USERS': False}):
            record_hourly_user(None, session_key='abc')
        self.assertEqual(hourly_user_stat.objects.count(), 0)

    def test_endpoint_is_wired_up(self):
        response = self.client.get('/stats/users/hourly/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('buckets', response.json())
        # The middleware records one bucket for this anonymous request.
        self.assertEqual(hourly_user_stat.objects.count(), 1)


class TrackedExceptionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_subclass_records_itself_on_creation(self):
        PaymentGatewayError(
            'gateway timeout', code='gw_timeout', context={'order': 42}
        )

        incident = monitoring_table.objects.get()
        self.assertEqual(incident.kind, IncidentKind.EXCEPTION)
        self.assertEqual(incident.exception_type, 'PaymentGatewayError')
        self.assertEqual(incident.status, IncidentStatus.OPEN)
        self.assertEqual(incident.calls_before_closure, 1)
        self.assertIn('gateway timeout', incident.exception_message)
        self.assertIn('code=gw_timeout', incident.exception_message)
        self.assertIn('order', incident.exception_message)

    def test_repeated_raises_increment_a_single_incident(self):
        for _ in range(3):
            try:
                raise PaymentGatewayError('down')
            except PaymentGatewayError:
                pass

        self.assertEqual(monitoring_table.objects.count(), 1)
        self.assertEqual(monitoring_table.objects.get().calls_before_closure, 3)

    def test_record_is_idempotent(self):
        exc = PaymentGatewayError('once')
        exc.record()
        exc.record()
        self.assertEqual(monitoring_table.objects.count(), 1)
        self.assertEqual(monitoring_table.objects.get().calls_before_closure, 1)

    def test_log_false_defers_recording(self):
        exc = PaymentGatewayError('later', log=False)
        self.assertEqual(monitoring_table.objects.count(), 0)
        exc.record()
        self.assertEqual(monitoring_table.objects.count(), 1)

    def test_uses_current_request_path_when_available(self):
        request = self.factory.get('/payments/checkout/?token=secret')
        set_current_request(request)
        try:
            PaymentGatewayError('boom')
        finally:
            clear_current_request()

        self.assertEqual(
            monitoring_table.objects.get().affected_method, '/payments/checkout/'
        )

    def test_capture_records_an_arbitrary_exception(self):
        try:
            raise ValueError('nope')
        except ValueError as exc:
            TrackedException.capture(exc)

        incident = monitoring_table.objects.get()
        self.assertEqual(incident.exception_type, 'ValueError')
        self.assertEqual(incident.calls_before_closure, 1)

    def test_capture_is_a_noop_for_already_recorded(self):
        exc = PaymentGatewayError('once')
        TrackedException.capture(exc)
        self.assertEqual(monitoring_table.objects.get().calls_before_closure, 1)

    @override_settings(ISSUE_TICCA={'TRACK_EXCEPTIONS': False})
    def test_auto_recording_can_be_disabled(self):
        PaymentGatewayError('silent')
        self.assertEqual(monitoring_table.objects.count(), 0)

    def test_middleware_does_not_double_count(self):
        middleware = ExceptionLoggingMiddleware(lambda request: HttpResponse())
        request = self.factory.get('/api/orders/')

        set_current_request(request)
        try:
            exc = PaymentGatewayError('boom')
        finally:
            clear_current_request()

        incident = monitoring_table.objects.get()
        self.assertEqual(incident.affected_method, '/api/orders/')
        self.assertEqual(incident.calls_before_closure, 1)

        # The middleware must not count the same occurrence again.
        middleware.process_exception(request, exc)
        incident.refresh_from_db()
        self.assertEqual(incident.calls_before_closure, 1)


class HealthAggregationTests(TestCase):
    def test_status_words_are_normalised(self):
        cases = [
            ('ok', 'ok'),
            ('healthy', 'ok'),
            ('OK', 'ok'),
            (' Healthy ', 'ok'),
            ('up', 'ok'),
            ('error', 'error'),
            ('unhealthy', 'error'),
            ('failed', 'error'),
            ('not_configured', 'not_configured'),
            ('skipped', 'skipped'),
            ('something-else', 'error'),
            (None, 'error'),
        ]
        for raw, expected in cases:
            self.assertEqual(normalize_status(raw), expected, repr(raw))

    def test_healthy_component_is_not_reported_as_failing(self):
        # Regression: check_database() returns 'healthy', which used to be
        # treated as a failure by the aggregator.
        payload = {
            'status': 'healthy',
            'database': {
                'connection': {'status': 'ok', 'latency_ms': 0.03},
                'read': {'status': 'ok', 'latency_ms': 0.09},
            },
            'latency_ms': 2.75,
        }
        with patch.dict(CHECKS, {'database': lambda: payload}):
            report = run_health_checks(['database'])

        self.assertEqual(report['status'], 'healthy')
        self.assertEqual(report['failing'], [])
        self.assertEqual(report['summary'], {'ok': 1})

    def test_unhealthy_component_is_reported_as_failing(self):
        with patch.dict(CHECKS, {'database': lambda: {'status': 'unhealthy'}}):
            report = run_health_checks(['database'])

        self.assertEqual(report['status'], 'unhealthy')
        self.assertEqual(report['failing'], ['database'])
        self.assertEqual(report['summary'], {'error': 1})

    def test_real_report_does_not_flag_a_healthy_database(self):
        report = run_health_checks()

        self.assertEqual(report['components']['database']['status'], 'healthy')
        self.assertEqual(report['failing'], [])
        self.assertEqual(report['status'], 'healthy')


class DRFExceptionHandlerTests(TestCase):
    """The DRF handler records 5xx exceptions (works with or without DRF)."""

    def setUp(self):
        self.factory = RequestFactory()

    def test_records_server_errors(self):
        request = self.factory.get('/api/orders/?token=secret')
        response = issue_ticca_exception_handler(ValueError('boom'), {'request': request})

        # DRF turns an unhandled exception into a 500, so no response is returned.
        self.assertIsNone(response)
        incident = monitoring_table.objects.get()
        self.assertEqual(incident.exception_type, 'ValueError')
        self.assertEqual(incident.affected_method, '/api/orders/')
        self.assertTrue(request._issue_ticca_exception)

    def test_does_not_double_count_tracked_exceptions(self):
        request = self.factory.get('/api/orders/')
        exc = PaymentGatewayError('boom')
        issue_ticca_exception_handler(exc, {'request': request})

        self.assertEqual(monitoring_table.objects.count(), 1)
        self.assertEqual(monitoring_table.objects.get().calls_before_closure, 1)

