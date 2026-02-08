"""Tests for logging configuration."""

from pathlib import Path

import structlog

from neuroflow.core.logging import (
    get_logger,
    setup_logging,
    setup_session_logger,
    write_to_log,
)


class TestSetupLogging:
    def test_console_format(self):
        setup_logging(level="INFO", format="console")
        log = structlog.get_logger()
        assert log is not None

    def test_json_format(self):
        setup_logging(level="DEBUG", format="json")
        log = structlog.get_logger()
        assert log is not None

    def test_log_level_case_insensitive(self):
        setup_logging(level="debug", format="console")
        log = structlog.get_logger()
        assert log is not None

    def test_log_to_file(self, tmp_path):
        log_file = tmp_path / "test.log"
        setup_logging(level="INFO", format="console", log_file=log_file)
        log = structlog.get_logger()
        log.info("test message")
        assert log_file.exists()
        # Reset to stdout for other tests
        setup_logging(level="DEBUG", format="console")

    def test_log_to_file_creates_parent_dirs(self, tmp_path):
        log_file = tmp_path / "sub" / "dir" / "test.log"
        setup_logging(level="INFO", format="console", log_file=log_file)
        log = structlog.get_logger()
        log.info("test message")
        assert log_file.parent.exists()
        # Reset
        setup_logging(level="DEBUG", format="console")

    def test_json_format_to_file(self, tmp_path):
        log_file = tmp_path / "json.log"
        setup_logging(level="DEBUG", format="json", log_file=log_file)
        log = structlog.get_logger()
        log.info("json test")
        assert log_file.exists()
        content = log_file.read_text()
        assert "json test" in content
        # Reset
        setup_logging(level="DEBUG", format="console")


class TestGetLogger:
    def test_without_name(self):
        setup_logging(level="DEBUG", format="console")
        log = get_logger()
        assert log is not None

    def test_with_name(self):
        setup_logging(level="DEBUG", format="console")
        log = get_logger("mycomponent")
        assert log is not None

    def test_different_names_return_different_loggers(self):
        setup_logging(level="DEBUG", format="console")
        log1 = get_logger("comp1")
        log2 = get_logger("comp2")
        # They should be separate bound loggers
        assert log1 is not log2


class TestSetupSessionLogger:
    def test_creates_log_file(self, tmp_path):
        log_path = setup_session_logger(
            tmp_path, "qsiprep", "sub-001", "ses-baseline"
        )
        assert log_path == tmp_path / "qsiprep" / "sub-001_ses-baseline.log"
        assert log_path.parent.exists()
        # Reset logging for other tests
        setup_logging(level="DEBUG", format="console")

    def test_creates_pipeline_subdir(self, tmp_path):
        setup_session_logger(tmp_path, "bids_conversion", "sub-001", "ses-01")
        assert (tmp_path / "bids_conversion").is_dir()
        setup_logging(level="DEBUG", format="console")

    def test_logging_writes_to_file(self, tmp_path):
        log_path = setup_session_logger(
            tmp_path, "qsiprep", "sub-001", "ses-01"
        )
        log = structlog.get_logger()
        log.info("test session log")
        content = log_path.read_text()
        assert "test session log" in content
        setup_logging(level="DEBUG", format="console")

    def test_append_mode(self, tmp_path):
        log_path = tmp_path / "qsiprep" / "sub-001_ses-01.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("existing content\n")

        setup_session_logger(tmp_path, "qsiprep", "sub-001", "ses-01")
        log = structlog.get_logger()
        log.info("new entry")

        content = log_path.read_text()
        assert "existing content" in content
        assert "new entry" in content
        setup_logging(level="DEBUG", format="console")


class TestWriteToLog:
    def test_writes_header_and_content(self, tmp_path):
        log_path = tmp_path / "test.log"
        write_to_log(log_path, "STDOUT", "pipeline output here")
        content = log_path.read_text()
        assert "STDOUT" in content
        assert "pipeline output here" in content
        assert "=" * 72 in content

    def test_adds_trailing_newline(self, tmp_path):
        log_path = tmp_path / "test.log"
        write_to_log(log_path, "TEST", "no newline at end")
        content = log_path.read_text()
        assert content.endswith("\n")

    def test_preserves_trailing_newline(self, tmp_path):
        log_path = tmp_path / "test.log"
        write_to_log(log_path, "TEST", "has newline\n")
        content = log_path.read_text()
        # Should not double the newline
        assert not content.endswith("\n\n")

    def test_empty_content_skipped(self, tmp_path):
        log_path = tmp_path / "test.log"
        write_to_log(log_path, "TEST", "")
        assert not log_path.exists()

    def test_whitespace_only_content_skipped(self, tmp_path):
        log_path = tmp_path / "test.log"
        write_to_log(log_path, "TEST", "   \n  \n  ")
        assert not log_path.exists()

    def test_appends_to_existing_file(self, tmp_path):
        log_path = tmp_path / "test.log"
        log_path.write_text("first block\n")
        write_to_log(log_path, "SECOND", "second block")
        content = log_path.read_text()
        assert "first block" in content
        assert "SECOND" in content
        assert "second block" in content

    def test_multiline_content(self, tmp_path):
        log_path = tmp_path / "test.log"
        write_to_log(log_path, "ERROR", "line 1\nline 2\nline 3")
        content = log_path.read_text()
        assert "line 1" in content
        assert "line 2" in content
        assert "line 3" in content
