"""Celery application configuration.

Provides:
- celery_app: the main Celery instance used by the FastAPI app
- task discovery from app.tasks package
"""

import os
from celery import Celery

redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "notero",
    broker=redis_url,
    backend=redis_url,
    include=["app.tasks.agent_tasks", "app.tasks.workflow_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=600,  # 10 minutes hard limit
    task_soft_time_limit=540,  # 9 minutes soft limit
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    beat_schedule={
        "sweep-stale-workflows": {
            "task": "app.tasks.workflow_tasks.sweep_stale_workflows",
            "schedule": 60.0,  # every minute
        },
    },
)
