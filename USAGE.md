# Neuroflow - Usage Guide

## Setup

```bash
# Activate environment
source .venv/bin/activate

# Initialize database
neuroflow admin init-db
```

## CLI Commands

### Status & Monitoring

```bash
# Overall summary (subjects, sessions, pipeline runs by status)
neuroflow status

# Session details
neuroflow status --sessions
neuroflow status --sessions --failed
neuroflow status --sessions --status-filter processing
neuroflow status --sessions --subject sub-001

# Subject details
neuroflow status --subjects
neuroflow status --subjects --failed
```

### Discovery

```bash
# Scan DICOM directories for new sessions
neuroflow scan now
neuroflow scan now --dry-run

# Validate a specific session directory
neuroflow scan validate /path/to/dicom/session
```

### Processing

```bash
# Process a specific session
neuroflow process session sub-001 ses-baseline
neuroflow process session sub-001 ses-baseline --pipeline mriqc
neuroflow process session sub-001 ses-baseline --force

# Process all sessions for a subject
neuroflow process subject sub-001

# Process all pending work
neuroflow process pending
neuroflow process pending --max-tasks 10

# Retry failed runs
neuroflow process retry --all
neuroflow process retry --pipeline freesurfer
neuroflow process retry --run-id 123
```

### Services

```bash
# Start Celery worker (executes queued pipelines)
neuroflow run worker
neuroflow run worker -c 4          # 4 concurrent workers

# Start Celery beat (periodic scan every 5 min)
neuroflow run beat

# Start file system watcher (real-time DICOM detection)
neuroflow run watcher

# Start everything
neuroflow run all
```

### Export

```bash
# Export session data
neuroflow export sessions -o sessions.csv
neuroflow export sessions -o sessions.json --format json
neuroflow export sessions --verbose    # all fields

# Export failure report
neuroflow export failures -o failures.csv

# Export audit log
neuroflow export audit -o audit.csv
neuroflow export audit --since "2024-01-01"
```

### Configuration

```bash
# Show current config
neuroflow config show
neuroflow config show --section paths
neuroflow config show --section pipelines

# Validate config file
neuroflow config validate
neuroflow config validate --config-file /path/to/other.yaml
```

### Admin

```bash
# Initialize database
neuroflow admin init-db

# Reset database (requires --confirm)
neuroflow admin reset --confirm
```

### Global Options

```bash
neuroflow --config /path/to/neuroflow.yaml <command>
neuroflow --log-level DEBUG <command>
```

## Running Tests

```bash
pytest tests/ -v
pytest tests/ -v --cov=neuroflow
```

## Configuration

Edit `neuroflow.yaml` in the project root. Key sections:

- **paths** - DICOM incoming, BIDS root, derivatives, work/log dirs
- **database** - SQLite or PostgreSQL URL
- **redis** - Redis URL for Celery broker
- **dataset** - Name, session IDs, directory structure
- **protocol** - Stability wait, required/optional scan definitions
- **pipelines** - BIDS conversion, session-level, subject-level pipelines
- **celery** - Worker concurrency, time limits, retry settings
- **logging** - Level (DEBUG/INFO/WARNING/ERROR), format (json/console)

Environment variables override config with `NEUROFLOW_` prefix:

```bash
export NEUROFLOW_DATABASE__URL="postgresql://user:pass@host:5432/neuroflow"
export NEUROFLOW_LOGGING__LEVEL="DEBUG"
```

## Google Sheet Scanner

Instead of relying on a nested `subject/session` directory layout, you can map
DICOM folders to subjects via a Google Sheet. Each folder directly under
`dicom_incoming` is treated as a **ScanID** (e.g. `20240115_1430`), and the
sheet provides the corresponding **SubjectCode**.

### 1. Prepare the Google Sheet

Create a Google Sheet with (at minimum) two columns:

| ScanID | SubjectCode |
|---|---|
| 20240115_1430 | CLM_L_01 |
| 20240116_0900 | CLM_L_02 |

- The column headers must match `scan_id_column` and `subject_code_column` in
  your config (defaults: `ScanID` and `SubjectCode`).
- The **spreadsheet key** is the long ID in the sheet URL:
  `https://docs.google.com/spreadsheets/d/<SPREADSHEET_KEY>/edit`

### 2. Create a Google Cloud Service Account

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project (or use an existing one).
3. Enable the **Google Sheets API** under *APIs & Services > Library*.
4. Go to *APIs & Services > Credentials* and create a **Service Account**.
5. On the service account page, go to the *Keys* tab, click
   *Add Key > Create new key*, and choose **JSON**. Save the downloaded file
   somewhere secure (e.g. `/etc/neuroflow/service-account.json`).
6. **Share the Google Sheet** with the service account's email address
   (found in the JSON file under `client_email`) with at least *Viewer*
   access.

### 3. Configure `neuroflow.yaml`

Under the `dataset:` section, add or update the `google_sheet:` block:

```yaml
dataset:
  google_sheet:
    enabled: true
    spreadsheet_key: "1aBcDeFgHiJkLmNoPqRsTuVwXyZ..."
    worksheet_name: "Sheet1"
    service_account_file: "/etc/neuroflow/service-account.json"
    csv_file: ""
    scan_id_column: "ScanID"
    subject_code_column: "SubjectCode"
    unknown_subject_id: "unknown"
```

| Field | Description |
|---|---|
| `enabled` | Set to `true` to activate sheet-based discovery. |
| `spreadsheet_key` | The ID from the Google Sheet URL. |
| `worksheet_name` | Name of the tab/worksheet to read (default `Sheet1`). |
| `service_account_file` | Absolute path to the service account JSON key file. |
| `scan_id_column` | Header of the column containing ScanIDs. |
| `subject_code_column` | Header of the column containing SubjectCodes. |
| `csv_file` | Path to a local CSV file. When set, the CSV is used instead of Google Sheets. |
| `unknown_subject_id` | Participant ID used when a ScanID is not found in the sheet. |

### Local CSV alternative

Instead of connecting to a Google Sheet you can point to a local CSV file with
the same column headers. Set the `csv_file` field and leave `spreadsheet_key`
empty (or any value -- it will be ignored):

```yaml
dataset:
  google_sheet:
    enabled: true
    csv_file: "/data/mappings/scan_mapping.csv"
    scan_id_column: "ScanID"
    subject_code_column: "SubjectCode"
```

The CSV file should look like:

```csv
ScanID,SubjectCode
20240115_1430,CLM_L_01
20240116_0900,CLM_L_02
```

When `csv_file` is set the mapper reads from that file and never contacts
Google Sheets, so no service account is required. If `csv_file` is empty, the
Google Sheet path is used as before.

### 4. Directory layout

When the sheet reader is enabled, `dicom_incoming` is expected to be **flat** --
each immediate subdirectory is a ScanID:

```
dicom_incoming/
  20240115_1430/
  20240116_0900/
  20240201_1100/
```

The scanner derives IDs as follows:

- **session_id** = ScanID with `_` removed (e.g. `20240115_1430` -> `202401151430`)
- **participant_id** = SubjectCode with non-alphanumeric characters stripped (e.g. `CLM_L_01` -> `CLML01`)
- **recruitment_id** = raw SubjectCode as-is (stored on the Subject record for reference)

If a directory name does not appear in the sheet, it is registered with
`participant_id` set to the configured `unknown_subject_id`.

### 5. Verify

```bash
# Dry-run scan to check mappings without writing to the database
neuroflow scan now --dry-run
```

The output table includes a **Recruitment ID** column showing the raw
SubjectCode from the sheet.

## What's Left to Implement

1. **Voxelops adapter** - Customize `_build_container_command` in `neuroflow/adapters/voxelops.py` with actual pipeline CLI arguments and bind mounts for your environment
2. **Alembic migrations** - Currently uses `create_all`; add Alembic when the schema needs to evolve
3. **Notifications** - Slack/email config is present but not wired into pipeline callbacks
4. **REST API** - `neuroflow/api/` is stubbed for a FastAPI dashboard
5. **SLURM/SGE** - `compute_environment` config exists but job submission logic isn't implemented
6. **Systemd services** - For production daemonization of worker/beat/watcher
