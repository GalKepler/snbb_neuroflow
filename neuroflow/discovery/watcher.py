"""File system watcher for incoming DICOM data."""

from datetime import datetime, timezone
from pathlib import Path

import structlog
from watchdog.events import DirCreatedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from neuroflow.config import NeuroflowConfig
from neuroflow.core.state import StateManager

log = structlog.get_logger("watcher")


class DicomEventHandler(FileSystemEventHandler):
    """Handle new DICOM directory events."""

    def __init__(self, config: NeuroflowConfig, state: StateManager):
        self.config = config
        self.state = state
        self.pending_sessions: dict[str, datetime] = {}

    def on_created(self, event: DirCreatedEvent) -> None:
        if isinstance(event, DirCreatedEvent):
            self._handle_new_directory(Path(event.src_path))

    def _handle_new_directory(self, path: Path) -> None:
        """Handle a newly created directory."""
        if self.config.dataset.google_sheet.enabled:
            scan_id = path.name
            log.info(
                "dicom.detected",
                scan_id=scan_id,
                path=str(path),
            )
            self.pending_sessions[str(path)] = datetime.now(timezone.utc)
            return

        from neuroflow.discovery.scanner import parse_dicom_path

        parsed = parse_dicom_path(
            path, self.config.dataset.dicom_participant_first
        )
        if parsed:
            participant_id, session_id = parsed
            log.info(
                "dicom.detected",
                participant_id=participant_id,
                session_id=session_id,
                path=str(path),
            )
            self.pending_sessions[str(path)] = datetime.now(timezone.utc)


class DicomWatcher:
    """Watch DICOM incoming directory for new data."""

    def __init__(self, config: NeuroflowConfig, state: StateManager | None = None):
        self.config = config
        self.state = state or StateManager(config)
        self.observer = Observer()
        self.handler = DicomEventHandler(config, self.state)

    def start(self) -> None:
        """Start watching for new DICOM data."""
        watch_path = self.config.paths.dicom_incoming
        if not watch_path.exists():
            log.warning("watcher.path_not_found", path=str(watch_path))
            return
        self.observer.schedule(self.handler, str(watch_path), recursive=True)
        self.observer.start()
        log.info("watcher.started", path=str(watch_path))

    def stop(self) -> None:
        """Stop the watcher."""
        self.observer.stop()
        self.observer.join()
        log.info("watcher.stopped")
