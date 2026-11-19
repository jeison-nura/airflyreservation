"""Inventory's Celery composition: Redis transports tasks, PostgreSQL owns seats."""

import os

from celery import Celery

celery_app = Celery(
    "inventory",
    broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    include=["flight_booking.modules.inventory.adapters.worker.expiry"],
)
celery_app.conf.update(
    timezone="UTC",
    task_ignore_result=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    worker_redirect_stdouts=False,
    task_default_queue="inventory",
    beat_schedule={
        "inventory-expire-due-holds": {
            "task": "inventory.expire_due_holds",
            "schedule": 2.0,
            "options": {"queue": "inventory"},
        },
        "inventory-publish-outbox": {
            "task": "inventory.publish_outbox",
            "schedule": 1.0,
            "options": {"queue": "inventory"},
        },
    },
)
