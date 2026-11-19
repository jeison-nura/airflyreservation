"""Reservations background tasks; Redis Streams carry events, Celery schedules work."""

import os

from celery import Celery

celery_app = Celery(
    "reservations",
    broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    include=["flight_booking.modules.reservations.adapters.worker.tasks"],
)
celery_app.conf.update(
    timezone="UTC",
    task_ignore_result=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    worker_redirect_stdouts=False,
    task_default_queue="reservations",
    beat_schedule={
        "reservations-publish-outbox": {
            "task": "reservations.publish_outbox",
            "schedule": 1.0,
            "options": {"queue": "reservations"},
        },
        "reservations-expire-due": {
            "task": "reservations.expire_due",
            "schedule": 2.0,
            "options": {"queue": "reservations"},
        },
    },
)
