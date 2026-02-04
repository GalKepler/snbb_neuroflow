# Neuroflow - CLI Specification

## Overview

The CLI is built with **Click** for command structure and **Rich** for beautiful terminal output. It provides full access to all neuroflow operations.

---

## Installation

```bash
pip install neuroflow

# CLI is available as:
neuroflow --help
```

---

## Command Structure

```
neuroflow
├── run                    # Start services
│   ├── all               # Start all services (watcher, worker, beat)
│   ├── watcher           # Start file system watcher only
│   ├── worker            # Start Celery worker only
│   └── beat              # Start Celery beat scheduler only
│
├── status                 # View system status
│   ├── summary           # Overall status summary (default)
│   ├── sessions          # List sessions with filters
│   ├── subjects          # List subjects with filters
│   ├── pipelines         # Pipeline run status
│   ├── queue             # Celery queue status
│   └── workers           # Worker status
│
├── scan                   # Discovery operations
│   ├── now               # Scan DICOM directories immediately
│   └── validate          # Validate specific session
│
├── process               # Processing operations
│   ├── session           # Process a specific session
│   ├── subject           # Process a specific subject
│   ├── pending           # Process all pending work
│   └── retry             # Retry failed runs
│
├── admin                  # Administrative operations
│   ├── init-db           # Initialize database
│   ├── migrate           # Run database migrations
│   ├── reset             # Reset database (dangerous!)
│   ├── exclude           # Exclude session/subject
│   ├── include           # Re-include excluded session/subject
│   └── purge             # Clean up old data
│
├── export                 # Export data
│   ├── sessions          # Export session data
│   ├── failures          # Export failure report
│   └── audit             # Export audit log
│
├── logs                   # View logs
│   ├── tail              # Tail main log
│   └── show              # Show logs for specific run
│
└── config                 # Configuration
    ├── show              # Show current configuration
    └── validate          # Validate configuration file
```

---

## Command Details

### `neuroflow run`

Start neuroflow services.

```bash
# Start everything (recommended for production)
neuroflow run all

# Start individual components
neuroflow run watcher       # File system monitoring
neuroflow run worker        # Celery worker for task execution
neuroflow run worker -c 4   # With 4 concurrent workers
neuroflow run beat          # Celery beat for scheduled tasks

# Options
--config PATH     # Configuration file path
--log-level LEVEL # Override log level (DEBUG, INFO, WARNING, ERROR)
--foreground      # Run in foreground (don't daemonize)
```

---

### `neuroflow status`

View system and processing status.

#### `neuroflow status summary` (default)

```bash
neuroflow status
# or
neuroflow status summary
```

Output:
```
╭──────────────────────────────────────────────────────────────────────╮
│                        Neuroflow Status                              │
╰──────────────────────────────────────────────────────────────────────╯

Services
┏━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┓
┃ Service  ┃ Status   ┃ Last Active          ┃
┡━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━┩
│ Watcher  │ ● Active │ 2 seconds ago        │
│ Worker   │ ● Active │ 5 seconds ago        │
│ Beat     │ ● Active │ 1 minute ago         │
│ Redis    │ ● Active │ -                    │
│ Database │ ● Active │ -                    │
└──────────┴──────────┴──────────────────────┘

Sessions                          Pipeline Runs
┏━━━━━━━━━━━━━┳━━━━━━━┓           ┏━━━━━━━━━━━━┳━━━━━━━┓
┃ Status      ┃ Count ┃           ┃ Status     ┃ Count ┃
┡━━━━━━━━━━━━━╇━━━━━━━┩           ┡━━━━━━━━━━━━╇━━━━━━━┩
│ Discovered  │    12 │           │ Pending    │    24 │
│ Validated   │     8 │           │ Running    │     3 │
│ Processing  │     3 │           │ Completed  │   156 │
│ Completed   │    87 │           │ Failed     │     7 │
│ Failed      │     2 │           └────────────┴───────┘
└─────────────┴───────┘

Recent Activity (last 24h)
  • 5 sessions discovered
  • 3 sessions completed processing
  • 12 pipeline runs completed
  • 2 pipeline runs failed
```

#### `neuroflow status sessions`

```bash
# List all sessions
neuroflow status sessions

# Filter by status
neuroflow status sessions --status failed
neuroflow status sessions --status processing
neuroflow status sessions --status validated

# Filter by subject
neuroflow status sessions --subject sub-001

# Filter by date range
neuroflow status sessions --since 2024-01-01
neuroflow status sessions --since "7 days ago"

# Show more details
neuroflow status sessions --verbose

# Output format
neuroflow status sessions --format table   # (default)
neuroflow status sessions --format json
neuroflow status sessions --format csv
```

Output:
```
Sessions (filtered: status=failed)
┏━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Subject   ┃ Session      ┃ Status   ┃ Discovered          ┃ Error                    ┃
┡━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ sub-003   │ ses-baseline │ failed   │ 2024-01-15 10:23    │ freesurfer: Out of mem…  │
│ sub-007   │ ses-followup │ failed   │ 2024-01-14 14:45    │ qsiprep: Invalid DWI d…  │
└───────────┴──────────────┴──────────┴─────────────────────┴──────────────────────────┘

2 sessions shown. Use --verbose for full error messages.
```

#### `neuroflow status pipelines`

```bash
# List recent pipeline runs
neuroflow status pipelines

# Filter by pipeline
neuroflow status pipelines --pipeline freesurfer

# Filter by status
neuroflow status pipelines --status failed
neuroflow status pipelines --status running

# Show timing statistics
neuroflow status pipelines --stats
```

Output (with `--stats`):
```
Pipeline Statistics
┏━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┓
┃ Pipeline      ┃ Completed ┃ Failed ┃ Running  ┃ Avg Duration      ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━┩
│ mriqc         │        45 │      2 │        1 │ 12m 34s           │
│ freesurfer    │        42 │      3 │        2 │ 8h 23m            │
│ fmriprep      │        38 │      1 │        0 │ 3h 45m            │
│ qsiprep       │        30 │      4 │        1 │ 2h 12m            │
└───────────────┴───────────┴────────┴──────────┴───────────────────┘
```

---

### `neuroflow scan`

DICOM discovery operations.

```bash
# Scan for new sessions now
neuroflow scan now

# Scan specific directory
neuroflow scan now --path /mnt/scanner/incoming

# Validate a specific session
neuroflow scan validate /path/to/dicom/session

# Dry run - show what would be found without registering
neuroflow scan now --dry-run
```

Output:
```
Scanning /mnt/62/Raw_Data...

Found 3 new sessions:
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ Path                                 ┃ Subject   ┃ Session      ┃ Status    ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━┩
│ /mnt/62/Raw_Data/sub-012/ses-01      │ sub-012   │ ses-baseline │ validated │
│ /mnt/62/Raw_Data/sub-013/ses-01      │ sub-013   │ ses-baseline │ validated │
│ /mnt/62/Raw_Data/sub-008/ses-02      │ sub-008   │ ses-followup │ validated │
└──────────────────────────────────────┴───────────┴──────────────┴───────────┘

3 sessions registered and queued for processing.
```

---

### `neuroflow process`

Manual processing operations.

```bash
# Process a specific session
neuroflow process session sub-001 ses-baseline

# Process all pipelines for a subject
neuroflow process subject sub-001

# Process all pending work
neuroflow process pending

# Limit concurrent tasks
neuroflow process pending --max-tasks 10

# Retry failed runs
neuroflow process retry --all
neuroflow process retry --session sub-001/ses-baseline
neuroflow process retry --pipeline freesurfer

# Retry with increased resources
neuroflow process retry --run-id 123 --memory 32G

# Force reprocess (even if already completed)
neuroflow process session sub-001 ses-baseline --force

# Process specific pipeline only
neuroflow process session sub-001 ses-baseline --pipeline mriqc
```

---

### `neuroflow admin`

Administrative operations.

```bash
# Initialize database
neuroflow admin init-db

# Run migrations
neuroflow admin migrate

# Reset database (DANGEROUS - requires confirmation)
neuroflow admin reset --confirm

# Exclude a session from processing
neuroflow admin exclude session sub-001 ses-baseline --reason "Corrupted data"

# Exclude a subject
neuroflow admin exclude subject sub-001 --reason "Withdrawn from study"

# Re-include
neuroflow admin include session sub-001 ses-baseline

# Purge old data
neuroflow admin purge --completed-before "90 days ago"
neuroflow admin purge --audit-before "1 year ago"
```

---

### `neuroflow export`

Export data for analysis.

```bash
# Export all sessions to CSV
neuroflow export sessions --output sessions.csv

# Export with all fields
neuroflow export sessions --output sessions.csv --verbose

# Export failures report
neuroflow export failures --output failures.csv
neuroflow export failures --output failures.json --format json

# Export audit log
neuroflow export audit --output audit.csv
neuroflow export audit --since "30 days ago" --output recent_audit.csv
```

---

### `neuroflow logs`

View logs.

```bash
# Tail the main log
neuroflow logs tail

# Tail with filtering
neuroflow logs tail --level ERROR
neuroflow logs tail --grep "sub-001"

# Show logs for a specific pipeline run
neuroflow logs show --run-id 123

# Show logs for a session's processing
neuroflow logs show --session sub-001/ses-baseline

# Follow logs in real-time
neuroflow logs tail -f
```

---

### `neuroflow config`

Configuration management.

```bash
# Show current configuration
neuroflow config show

# Show specific section
neuroflow config show --section pipelines

# Validate configuration file
neuroflow config validate

# Validate specific file
neuroflow config validate --config /path/to/neuroflow.yaml
```

---

## Global Options

These options are available for all commands:

```bash
--config PATH        # Configuration file path (default: neuroflow.yaml)
--log-level LEVEL    # Log level: DEBUG, INFO, WARNING, ERROR
--quiet              # Suppress non-essential output
--verbose            # Increase output verbosity
--json               # Output in JSON format (where applicable)
--help               # Show help message
```

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0    | Success |
| 1    | General error |
| 2    | Configuration error |
| 3    | Database error |
| 4    | Service not running |
| 5    | Invalid arguments |

---

## Implementation Notes

### Rich Tables

Use Rich for all tabular output:

```python
from rich.console import Console
from rich.table import Table

console = Console()

def show_sessions(sessions: list[Session]) -> None:
    table = Table(title="Sessions")
    table.add_column("Subject", style="cyan")
    table.add_column("Session", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Discovered")
    
    for s in sessions:
        status_style = {
            "completed": "green",
            "failed": "red",
            "processing": "yellow",
        }.get(s.status.value, "white")
        
        table.add_row(
            s.subject.participant_id,
            s.session_id,
            f"[{status_style}]{s.status.value}[/]",
            s.discovered_at.strftime("%Y-%m-%d %H:%M"),
        )
    
    console.print(table)
```

### Structured Logging Output

For JSON log output (useful for log aggregation):

```python
import structlog

log = structlog.get_logger()

@cli.command()
def scan_now():
    log.info("scan.started", path=str(config.paths.dicom_incoming))
    # ...
    log.info("scan.completed", sessions_found=len(sessions))
```

### Progress Bars

Use Rich progress for long operations:

```python
from rich.progress import Progress, SpinnerColumn, TextColumn

with Progress(
    SpinnerColumn(),
    TextColumn("[progress.description]{task.description}"),
) as progress:
    task = progress.add_task("Scanning directories...", total=None)
    # ... scanning code
```
