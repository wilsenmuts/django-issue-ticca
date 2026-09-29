"""
check/database.py

Database health checks: connection, read, transaction, and a write/read probe.
"""

import time
from typing import Any

from django.db import connection, transaction

from django_issue_ticca.models import database_probe


def _latency(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


def check_connection() -> dict[str, Any]:
    """Check whether Django can establish a database connection."""
    start = time.perf_counter()

    try:
        connection.ensure_connection()
        return {
            "status": "ok",
            "latency_ms": _latency(start),
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "exception": type(exc).__name__,
        }


def check_read() -> dict[str, Any]:
    """Check whether the database can execute a simple SELECT query."""
    start = time.perf_counter()

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            result = cursor.fetchone()

        if result and result[0] == 1:
            return {
                "status": "ok",
                "latency_ms": _latency(start),
            }

        return {
            "status": "error",
            "error": "Unexpected database response",
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "exception": type(exc).__name__,
        }


def check_transaction() -> dict[str, Any]:
    """Check whether the database can start and rollback a transaction."""
    start = time.perf_counter()

    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                result = cursor.fetchone()

            if not result or result[0] != 1:
                raise RuntimeError("Transaction test returned an unexpected result")

        return {
            "status": "ok",
            "latency_ms": _latency(start),
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "exception": type(exc).__name__,
        }


def check_database_probe() -> dict[str, Any]:
    """
    Round-trip a probe row: upsert it, then read it back.

    Uses ``update_or_create`` so repeated health checks don't grow the table
    without bound.
    """
    try:
        database_probe.objects.update_or_create(
            probe_name="health_check",
            defaults={"probe_status": True},
        )
        insert_status: dict[str, Any] = {"status": "ok"}
    except Exception as exc:
        insert_status = {
            "status": "error",
            "error": str(exc),
            "exception": type(exc).__name__,
        }

    try:
        retrieved = database_probe.objects.filter(
            probe_name="health_check", probe_status=True
        ).exists()
        if retrieved:
            retrieve_status: dict[str, Any] = {"status": "ok"}
        else:
            retrieve_status = {
                "status": "error",
                "error": "No healthy probe row found",
            }
    except Exception as exc:
        retrieve_status = {
            "status": "error",
            "error": str(exc),
            "exception": type(exc).__name__,
        }

    ok = insert_status["status"] == "ok" and retrieve_status["status"] == "ok"

    # The top-level ``status`` key is required so ``check_database`` can treat
    # this component like every other one.
    return {
        "status": "ok" if ok else "error",
        "insert_status": insert_status,
        "retrieved_probe": retrieve_status,
    }


def check_database() -> dict[str, Any]:
    """Run the basic database health checks and return an aggregate result."""
    start = time.perf_counter()

    connection_check = check_connection()

    # Don't run further checks if we cannot connect.
    if connection_check["status"] != "ok":
        return {
            "status": "unhealthy",
            "database": {
                "connection": connection_check,
            },
            "latency_ms": _latency(start),
        }

    checks = {
        "connection": connection_check,
        "read": check_read(),
        "transaction": check_transaction(),
        "database_probe": check_database_probe(),
    }

    # ``.get`` keeps this robust even if a future check omits ``status``.
    healthy = all(check.get("status") == "ok" for check in checks.values())

    return {
        "status": "healthy" if healthy else "unhealthy",
        "database": checks,
        "latency_ms": _latency(start),
    }