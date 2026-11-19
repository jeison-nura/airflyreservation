import json

import pytest

from flight_booking.shared.observability import log_event, run_logged_job


def test_worker_logs_error_type_without_exception_details_and_resets_context(capsys):
    async def failing_job():
        log_event("payments", "payment_operation", correlation_id="a" * 32)
        raise RuntimeError("private transaction details")

    with pytest.raises(RuntimeError, match="private transaction details"):
        run_logged_job("reservations", "expire_due", failing_job)
    log_event("inventory", "seat_command", correlation_id="private header value")

    output = capsys.readouterr().out
    payment, failure, after = [json.loads(line) for line in output.splitlines()]
    assert payment["entry_point"] == failure["entry_point"] == "worker"
    assert payment["request_id"] == failure["request_id"]
    assert payment["correlation_id"] == "a" * 32
    assert failure["event"] == "worker_failed"
    assert failure["level"] == "ERROR"
    assert failure["error_type"] == "RuntimeError"
    assert after["entry_point"] == "internal"
    assert after["correlation_id"] == after["request_id"] != failure["request_id"]
    assert "private" not in output


def test_worker_reports_processed_jobs_but_not_empty_periodic_polls(capsys):
    async def processed():
        return 2

    async def empty():
        return 0

    assert run_logged_job("inventory", "publish_outbox", processed) == 2
    assert run_logged_job("inventory", "publish_outbox", empty) == 0
    record = json.loads(capsys.readouterr().out)
    assert record["event"] == "worker_completed"
    assert record["count"] == 2
