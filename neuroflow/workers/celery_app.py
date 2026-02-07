"""Celery application configuration."""

from celery import Celery
from celery.schedules import crontab
from kombu import Exchange, Queue

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

    # Define exchanges
    default_exchange = Exchange("neuroflow", type="direct")

    # Define queues with routing and priorities
    app.conf.task_queues = (
        # High priority - workflow orchestration
        Queue(
            "workflow",
            exchange=default_exchange,
            routing_key="workflow",
            queue_arguments={"x-max-priority": 10},
        ),
        # High priority - discovery
        Queue(
            "discovery",
            exchange=default_exchange,
            routing_key="discovery",
            queue_arguments={"x-max-priority": 8},
        ),
        # Medium priority - BIDS conversion
        Queue(
            "bids",
            exchange=default_exchange,
            routing_key="bids",
            queue_arguments={"x-max-priority": 5},
        ),
        # Low priority - heavy processing (QSIPrep)
        Queue(
            "heavy_processing",
            exchange=default_exchange,
            routing_key="heavy",
            queue_arguments={"x-max-priority": 2},
        ),
        # Medium priority - standard processing (QSIRecon, QSIParc)
        Queue(
            "processing",
            exchange=default_exchange,
            routing_key="processing",
            queue_arguments={"x-max-priority": 4},
        ),
        # Default queue
        Queue(
            "default",
            exchange=default_exchange,
            routing_key="default",
        ),
    )

    # Task routing
    app.conf.task_routes = {
        # Workflow tasks
        "neuroflow.workers.workflow_tasks.run_master_workflow": {"queue": "workflow"},
        "neuroflow.workers.workflow_tasks.run_discovery_stage": {"queue": "discovery"},
        "neuroflow.workers.workflow_tasks.run_bids_stage": {"queue": "bids"},
        "neuroflow.workers.workflow_tasks.run_qsiprep_stage": {"queue": "heavy_processing"},
        "neuroflow.workers.workflow_tasks.run_qsirecon_stage": {"queue": "processing"},
        "neuroflow.workers.workflow_tasks.run_qsiparc_stage": {"queue": "processing"},
        # Discovery tasks
        "neuroflow.workers.tasks.scan_directories": {"queue": "discovery"},
        "neuroflow.workers.tasks.validate_session": {"queue": "discovery"},
        # Pipeline execution tasks
        "neuroflow.workers.tasks.run_bids_conversion": {"queue": "bids"},
    }

    # Get workflow configuration
    workflow_config = getattr(config, 'workflow', None) or {}
    schedule_cron = workflow_config.get('schedule', '0 2 */3 * *')  # Default: 2 AM every 3 days

    # Parse cron expression (minute, hour, day_of_month, month, day_of_week)
    cron_parts = schedule_cron.split()
    if len(cron_parts) == 5:
        minute, hour, day_of_month, month, day_of_week = cron_parts
        workflow_schedule = crontab(
            minute=minute,
            hour=hour,
            day_of_month=day_of_month,
            month_of_year=month,
            day_of_week=day_of_week,
        )
    else:
        # Default fallback
        workflow_schedule = crontab(minute=0, hour=2)

    # Celery beat schedule
    app.conf.beat_schedule = {
        # Master workflow - runs on configured schedule
        "master-workflow": {
            "task": "neuroflow.workers.workflow_tasks.run_master_workflow",
            "schedule": workflow_schedule,
            "options": {"queue": "workflow"},
        },
        # Quick scan for new sessions - runs hourly
        "hourly-scan": {
            "task": "neuroflow.workers.tasks.scan_directories",
            "schedule": crontab(minute=0),  # Every hour
            "options": {"queue": "discovery"},
        },
        # Cleanup stale runs - runs daily
        "daily-cleanup": {
            "task": "neuroflow.workers.tasks.cleanup_stale_runs",
            "schedule": crontab(minute=0, hour=3),  # 3 AM daily
            "options": {"queue": "default"},
        },
    }

    # Core configuration
    app.conf.update(
        broker_url=config.redis.url,
        result_backend=config.redis.url,
        # Serialization
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        # Time limits
        task_soft_time_limit=config.celery.task_soft_time_limit,
        task_time_limit=config.celery.task_time_limit,
        # Worker settings
        worker_prefetch_multiplier=1,  # Don't prefetch tasks
        worker_concurrency=config.celery.worker_concurrency,
        # Result settings
        result_expires=86400 * 7,  # 7 days
        result_extended=True,  # Store task args/kwargs
        # Task settings
        task_acks_late=True,  # Acknowledge after completion
        task_reject_on_worker_lost=True,  # Requeue on worker crash
        task_track_started=True,  # Track when tasks start
        # Retry settings
        task_default_retry_delay=config.celery.default_retry_delay,
        # Priority
        task_default_queue="default",
        task_queue_max_priority=10,
        task_default_priority=5,
        # Timezone
        timezone="UTC",
        enable_utc=True,
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
