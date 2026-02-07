# Deployment Guide

## Overview

This document describes how to deploy neuroflow for production use, including Docker deployment, systemd services, and monitoring setup.

## Deployment Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      PRODUCTION ARCHITECTURE                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────────┐   │
│  │   Redis      │   │  PostgreSQL  │   │   Neuroflow Workers      │   │
│  │   (Broker)   │   │  (Database)  │   │                          │   │
│  └──────┬───────┘   └──────┬───────┘   │  ┌────────────────────┐ │   │
│         │                  │           │  │ workflow (1x)      │ │   │
│         │                  │           │  │ discovery (2x)     │ │   │
│         │                  │           │  │ bids (4x)          │ │   │
│         │                  │           │  │ processing (2x)    │ │   │
│         │                  │           │  │ heavy (1x)         │ │   │
│         │                  │           │  └────────────────────┘ │   │
│         │                  │           └──────────────────────────┘   │
│         │                  │                                           │
│         └──────────────────┼──────────────────────────────────────────│
│                            │                                           │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │                     Shared Storage                                │ │
│  │   /data/dicom    /data/bids    /data/derivatives                 │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## Docker Deployment

### Dockerfile

```dockerfile
# Dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Install Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# Copy application code
COPY neuroflow/ ./neuroflow/

# Create non-root user
RUN useradd -m -s /bin/bash neuroflow
USER neuroflow

# Default command
CMD ["neuroflow", "run", "worker"]
```

### Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    volumes:
      - redis-data:/data
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  postgres:
    image: postgres:15-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: neuroflow
      POSTGRES_USER: neuroflow
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres-data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U neuroflow"]
      interval: 10s
      timeout: 5s
      retries: 5

  neuroflow-beat:
    build: .
    command: neuroflow run beat
    restart: unless-stopped
    depends_on:
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
    environment:
      - NEUROFLOW_DATABASE__URL=postgresql://neuroflow:${POSTGRES_PASSWORD}@postgres:5432/neuroflow
      - NEUROFLOW_REDIS__URL=redis://redis:6379/0
    volumes:
      - ./neuroflow.yaml:/app/neuroflow.yaml:ro
      - neuroflow-logs:/var/log/neuroflow

  neuroflow-workflow:
    build: .
    command: celery -A neuroflow.workers.celery_app worker -Q workflow,discovery -c 2
    restart: unless-stopped
    depends_on:
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
    environment:
      - NEUROFLOW_DATABASE__URL=postgresql://neuroflow:${POSTGRES_PASSWORD}@postgres:5432/neuroflow
      - NEUROFLOW_REDIS__URL=redis://redis:6379/0
    volumes:
      - ./neuroflow.yaml:/app/neuroflow.yaml:ro
      - ${DICOM_ROOT}:/data/dicom:ro
      - ${BIDS_ROOT}:/data/bids
      - ${DERIVATIVES_ROOT}:/data/derivatives
      - neuroflow-logs:/var/log/neuroflow

  neuroflow-bids:
    build: .
    command: celery -A neuroflow.workers.celery_app worker -Q bids -c 4
    restart: unless-stopped
    depends_on:
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
    environment:
      - NEUROFLOW_DATABASE__URL=postgresql://neuroflow:${POSTGRES_PASSWORD}@postgres:5432/neuroflow
      - NEUROFLOW_REDIS__URL=redis://redis:6379/0
    volumes:
      - ./neuroflow.yaml:/app/neuroflow.yaml:ro
      - ${DICOM_ROOT}:/data/dicom:ro
      - ${BIDS_ROOT}:/data/bids
      - neuroflow-logs:/var/log/neuroflow
    deploy:
      resources:
        limits:
          memory: 8G

  neuroflow-heavy:
    build: .
    command: celery -A neuroflow.workers.celery_app worker -Q heavy_processing -c 1
    restart: unless-stopped
    depends_on:
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
    environment:
      - NEUROFLOW_DATABASE__URL=postgresql://neuroflow:${POSTGRES_PASSWORD}@postgres:5432/neuroflow
      - NEUROFLOW_REDIS__URL=redis://redis:6379/0
    volumes:
      - ./neuroflow.yaml:/app/neuroflow.yaml:ro
      - ${BIDS_ROOT}:/data/bids:ro
      - ${DERIVATIVES_ROOT}:/data/derivatives
      - neuroflow-logs:/var/log/neuroflow
    deploy:
      resources:
        limits:
          memory: 32G
          cpus: '8'

  neuroflow-processing:
    build: .
    command: celery -A neuroflow.workers.celery_app worker -Q processing -c 2
    restart: unless-stopped
    depends_on:
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
    environment:
      - NEUROFLOW_DATABASE__URL=postgresql://neuroflow:${POSTGRES_PASSWORD}@postgres:5432/neuroflow
      - NEUROFLOW_REDIS__URL=redis://redis:6379/0
    volumes:
      - ./neuroflow.yaml:/app/neuroflow.yaml:ro
      - ${BIDS_ROOT}:/data/bids:ro
      - ${DERIVATIVES_ROOT}:/data/derivatives
      - neuroflow-logs:/var/log/neuroflow
    deploy:
      resources:
        limits:
          memory: 16G

  flower:
    image: mher/flower:2.0
    command: celery --broker=redis://redis:6379/0 flower --port=5555
    restart: unless-stopped
    depends_on:
      - redis
    ports:
      - "5555:5555"

volumes:
  redis-data:
  postgres-data:
  neuroflow-logs:
```

### Environment File

```bash
# .env
POSTGRES_PASSWORD=your-secure-password
DICOM_ROOT=/data/brainbank/dicom
BIDS_ROOT=/data/brainbank/bids
DERIVATIVES_ROOT=/data/brainbank/derivatives
```

## Systemd Deployment

### Service Files

```ini
# /etc/systemd/system/neuroflow-beat.service
[Unit]
Description=Neuroflow Beat Scheduler
After=network.target redis.service postgresql.service

[Service]
Type=simple
User=neuroflow
Group=neuroflow
WorkingDirectory=/opt/neuroflow
ExecStart=/opt/neuroflow/venv/bin/neuroflow run beat
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/neuroflow-worker@.service
[Unit]
Description=Neuroflow Worker %i
After=network.target redis.service postgresql.service

[Service]
Type=simple
User=neuroflow
Group=neuroflow
WorkingDirectory=/opt/neuroflow
ExecStart=/opt/neuroflow/venv/bin/celery -A neuroflow.workers.celery_app worker -Q %i -c ${CONCURRENCY}
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment="CONCURRENCY=2"

[Install]
WantedBy=multi-user.target
```

### Installation Script

```bash
#!/bin/bash
# install.sh

set -e

# Create user
sudo useradd -r -s /bin/false neuroflow

# Create directories
sudo mkdir -p /opt/neuroflow
sudo mkdir -p /var/log/neuroflow
sudo chown neuroflow:neuroflow /opt/neuroflow /var/log/neuroflow

# Install application
sudo -u neuroflow python -m venv /opt/neuroflow/venv
sudo -u neuroflow /opt/neuroflow/venv/bin/pip install neuroflow

# Copy config
sudo cp neuroflow.yaml /opt/neuroflow/
sudo chown neuroflow:neuroflow /opt/neuroflow/neuroflow.yaml

# Install services
sudo cp systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload

# Enable services
sudo systemctl enable neuroflow-beat
sudo systemctl enable neuroflow-worker@workflow
sudo systemctl enable neuroflow-worker@discovery
sudo systemctl enable neuroflow-worker@bids
sudo systemctl enable neuroflow-worker@processing
sudo systemctl enable neuroflow-worker@heavy_processing

# Start services
sudo systemctl start neuroflow-beat
sudo systemctl start neuroflow-worker@workflow
sudo systemctl start neuroflow-worker@discovery
sudo systemctl start neuroflow-worker@bids
sudo systemctl start neuroflow-worker@processing
sudo systemctl start neuroflow-worker@heavy_processing

echo "Neuroflow installed and started"
```

## Production Configuration

### neuroflow.yaml

```yaml
# Production neuroflow.yaml

paths:
  dicom_root: /data/brainbank/dicom
  bids_root: /data/brainbank/bids
  derivatives_root: /data/brainbank/derivatives
  log_dir: /var/log/neuroflow

database:
  url: postgresql://neuroflow:${POSTGRES_PASSWORD}@localhost:5432/neuroflow
  pool_size: 10
  max_overflow: 20

redis:
  url: redis://localhost:6379/0

workflow:
  schedule: "0 2 */3 * *"  # 2 AM every 3 days
  max_concurrent:
    bids_conversion: 4
    qsiprep: 1
    qsirecon: 2
    qsiparc: 4

celery:
  worker_concurrency: 4
  task_soft_time_limit: 43200
  task_time_limit: 86400

pipelines:
  bids_conversion:
    enabled: true
    timeout_minutes: 60
  
  subject_level:
    - name: qsiprep
      enabled: true
      timeout_minutes: 1440
      voxelops_config:
        nprocs: 8
        mem_mb: 24000
  
  session_level:
    - name: qsirecon
      enabled: true
      timeout_minutes: 720
    - name: qsiparc
      enabled: true
      timeout_minutes: 240

logging:
  level: INFO
  format: json
  log_dir: /var/log/neuroflow

error_handling:
  default_retry:
    max_attempts: 3
    initial_delay_minutes: 5
    max_delay_minutes: 60
    exponential_backoff: true
  
  notifications:
    on_dead_letter: true
    slack_webhook: ${SLACK_WEBHOOK}
```

## Database Migrations

```bash
# Initialize database
cd /opt/neuroflow
source venv/bin/activate

# Run migrations
alembic upgrade head

# Create initial admin user (if applicable)
neuroflow db init
```

## Monitoring

### Prometheus Metrics

```yaml
# prometheus.yml addition
scrape_configs:
  - job_name: 'neuroflow'
    static_configs:
      - targets: ['localhost:9090']
    metrics_path: /metrics
```

### Grafana Dashboard

Import the provided dashboard JSON for monitoring:
- Workflow runs over time
- Pipeline success/failure rates
- Queue depths
- Processing durations
- Error rates by type

## Backup Strategy

```bash
#!/bin/bash
# backup.sh

DATE=$(date +%Y%m%d)
BACKUP_DIR=/backup/neuroflow

# Backup database
pg_dump -U neuroflow neuroflow | gzip > $BACKUP_DIR/db_$DATE.sql.gz

# Backup configuration
cp /opt/neuroflow/neuroflow.yaml $BACKUP_DIR/config_$DATE.yaml

# Rotate backups (keep 30 days)
find $BACKUP_DIR -mtime +30 -delete
```

## Health Checks

```bash
#!/bin/bash
# healthcheck.sh

# Check Redis
redis-cli ping || exit 1

# Check PostgreSQL
pg_isready -U neuroflow || exit 1

# Check workers
celery -A neuroflow.workers.celery_app inspect ping || exit 1

# Check beat
systemctl is-active neuroflow-beat || exit 1

echo "All services healthy"
```

## Troubleshooting

### Common Issues

1. **Workers not processing tasks**
   ```bash
   # Check worker status
   celery -A neuroflow.workers.celery_app inspect active
   
   # Check queue lengths
   celery -A neuroflow.workers.celery_app inspect reserved
   ```

2. **Database connection issues**
   ```bash
   # Check PostgreSQL logs
   journalctl -u postgresql -f
   
   # Test connection
   psql -U neuroflow -h localhost -d neuroflow
   ```

3. **Memory issues with QSIPrep**
   ```bash
   # Check container memory
   docker stats neuroflow-heavy
   
   # Adjust memory limit in docker-compose.yml
   ```

### Log Locations

- Application logs: `/var/log/neuroflow/neuroflow.log`
- Worker logs: `journalctl -u neuroflow-worker@*`
- Beat logs: `journalctl -u neuroflow-beat`

### Recovery Commands

```bash
# Restart all workers
sudo systemctl restart 'neuroflow-worker@*'

# Clear stuck tasks
celery -A neuroflow.workers.celery_app purge

# Manual workflow trigger
neuroflow workflow run --sync
```
