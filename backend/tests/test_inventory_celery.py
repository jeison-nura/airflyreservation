"""Celery wiring without starting Redis or changing a seat."""

from flight_booking.modules.inventory.adapters.worker import expiry
from flight_booking.modules.inventory.adapters.worker.celery_app import celery_app


def test_expiry_task_is_scheduled_on_inventory_queue(monkeypatch):
    schedule = celery_app.conf.beat_schedule["inventory-expire-due-holds"]
    assert schedule["task"] == "inventory.expire_due_holds"
    assert schedule["schedule"] == 2.0
    assert schedule["options"]["queue"] == "inventory"

    async def batch():
        return 3

    monkeypatch.setattr(expiry, "run_batch", batch)
    assert expiry.expire_due_holds.run() == 3
