"""Celery application configuration."""

from celery import Celery
from kombu import Queue

from neuroflow.config import NeuroflowConfig

# Module-level app, lazily initialized
_celery_app: Celery | None = None


def create_celery_app(config: NeuroflowConfig | None = None) -> Celery:
    """Create and configure the Celery application."""
    global _celery_app

    if _celery_app is not None:
        return _celery_app

    if config is None:
        config = NeuroflowConfig.find_and_load()

    app = Celery("neuroflow")

    app.conf.update(
        broker_url=config.redis.url,
        result_backend=config.redis.url,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_soft_time_limit=config.celery.task_soft_time_limit,
        task_time_limit=config.celery.task_time_limit,
        worker_prefetch_multiplier=1,
        worker_concurrency=config.celery.worker_concurrency,
        result_expires=86400,
        task_queues=(
            Queue("default", routing_key="default"),
            Queue("bids", routing_key="bids"),
            Queue("processing", routing_key="processing"),
        ),
        task_default_queue="default",
        beat_schedule={
            "scan-for-new-sessions": {
                "task": "neuroflow.workers.tasks.scan_directories",
                "schedule": 300.0,
            },
        },
    )

    # Auto-discover tasks
    app.autodiscover_tasks(["neuroflow.workers"])

    # Store config reference
    app.config_obj = config

    _celery_app = app
    return app


def get_celery_app() -> Celery:
    """Get or create the Celery app."""
    if _celery_app is None:
        return create_celery_app()
    return _celery_app
