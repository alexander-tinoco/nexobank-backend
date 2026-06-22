"""Celery application instance.

The worker and beat processes are launched with:
    celery -A app.workers.celery_app worker
    celery -A app.workers.celery_app beat

Task modules are auto-discovered under ``app.workers.*``.
"""

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "nexobank",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.workers.notification_tasks",
        "app.workers.risk_tasks",
        "app.workers.cleanup_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Prevent tasks from running forever if a worker hangs
    task_soft_time_limit=300,  # seconds — raises SoftTimeLimitExceeded
    task_time_limit=360,  # seconds — kills the worker process
    worker_prefetch_multiplier=1,  # fair dispatch for long-running tasks
    beat_schedule={
        # Run every day at 03:00 UTC to purge expired refresh tokens.
        "cleanup-expired-refresh-tokens-daily": {
            "task": "nexobank.cleanup_expired_refresh_tokens",
            "schedule": crontab(hour=3, minute=0),
        },
    },
)
