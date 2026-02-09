"""Tests for worker CLI commands."""

import time
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
from click.testing import CliRunner

from neuroflow.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def yaml_config(tmp_path):
    cfg = tmp_path / "neuroflow.yaml"
    cfg.write_text(
        f"""\
paths:
  dicom_incoming: {tmp_path / 'incoming'}
  bids_root: {tmp_path / 'bids'}
  derivatives: {tmp_path / 'derivatives'}
  log_dir: {tmp_path / 'logs'}
execution:
  max_workers: 2
  state_dir: {tmp_path / 'state'}
"""
    )
    for d in ("incoming", "bids", "derivatives", "logs"):
        (tmp_path / d).mkdir()
    return str(cfg)


class TestWorkerStart:
    @patch("neuroflow.cli.worker.subprocess.Popen")
    @patch("neuroflow.cli.worker._read_pid")
    def test_start_foreground(self, mock_read_pid, mock_popen, runner, yaml_config):
        """Test starting worker in foreground mode."""
        mock_read_pid.return_value = None  # No existing worker
        mock_proc = Mock()
        mock_proc.wait = Mock()
        mock_popen.return_value = mock_proc

        result = runner.invoke(
            cli,
            ["--config", yaml_config, "worker", "start"],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert "Starting Huey consumer" in result.output
        assert "foreground" in result.output
        mock_popen.assert_called_once()

        # Check command arguments
        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        assert "huey.bin.huey_consumer" in " ".join(cmd)
        assert "neuroflow.tasks.huey" in cmd

    @patch("neuroflow.cli.worker.subprocess.Popen")
    @patch("neuroflow.cli.worker._read_pid")
    @patch("neuroflow.cli.worker._write_pid")
    @patch("neuroflow.cli.worker.time.sleep")
    def test_start_daemon(
        self, mock_sleep, mock_write_pid, mock_read_pid, mock_popen, runner, yaml_config
    ):
        """Test starting worker in daemon mode."""
        mock_read_pid.return_value = None
        mock_proc = Mock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None  # Still running
        mock_popen.return_value = mock_proc

        result = runner.invoke(
            cli,
            ["--config", yaml_config, "worker", "start", "--daemon"],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert "Starting Huey consumer" in result.output
        assert "daemon" in result.output
        assert "Worker started successfully" in result.output
        assert "PID: 12345" in result.output

        # Check that PID was written
        mock_write_pid.assert_called_once()

    @patch("neuroflow.cli.worker._read_pid")
    def test_start_when_already_running(self, mock_read_pid, runner, yaml_config):
        """Test start fails when worker already running."""
        mock_read_pid.return_value = 99999

        result = runner.invoke(
            cli, ["--config", yaml_config, "worker", "start"]
        )

        assert result.exit_code == 1
        assert "already running" in result.output
        assert "99999" in result.output

    @patch("neuroflow.cli.worker.subprocess.Popen")
    @patch("neuroflow.cli.worker._read_pid")
    @patch("neuroflow.cli.worker.time.sleep")
    def test_start_daemon_fails(
        self, mock_sleep, mock_read_pid, mock_popen, runner, yaml_config
    ):
        """Test daemon start handles process failure."""
        mock_read_pid.return_value = None
        mock_proc = Mock()
        mock_proc.poll.return_value = 1  # Process exited with error
        mock_proc.returncode = 1
        mock_popen.return_value = mock_proc

        result = runner.invoke(
            cli, ["--config", yaml_config, "worker", "start", "--daemon"]
        )

        assert result.exit_code == 1
        assert "failed to start" in result.output

    @patch("neuroflow.cli.worker.subprocess.Popen")
    @patch("neuroflow.cli.worker._read_pid")
    def test_start_with_custom_workers(
        self, mock_read_pid, mock_popen, runner, yaml_config
    ):
        """Test start with custom worker count."""
        mock_read_pid.return_value = None
        mock_proc = Mock()
        mock_proc.wait = Mock()
        mock_popen.return_value = mock_proc

        result = runner.invoke(
            cli,
            ["--config", yaml_config, "worker", "start", "-w", "8"],
        )

        assert result.exit_code == 0
        assert "Workers: 8" in result.output

        # Check command has -w 8
        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        assert "-w" in cmd
        w_index = cmd.index("-w")
        assert cmd[w_index + 1] == "8"


class TestWorkerStop:
    @patch("neuroflow.cli.worker.psutil.Process")
    @patch("neuroflow.cli.worker._read_pid")
    def test_stop_running_worker(self, mock_read_pid, mock_process_cls, runner, yaml_config):
        """Test stopping a running worker."""
        mock_read_pid.return_value = 12345
        mock_proc = Mock()
        mock_proc.wait = Mock()
        mock_process_cls.return_value = mock_proc

        result = runner.invoke(
            cli, ["--config", yaml_config, "worker", "stop"]
        )

        assert result.exit_code == 0
        assert "Stopping worker" in result.output
        assert "12345" in result.output
        assert "stopped successfully" in result.output

        mock_proc.terminate.assert_called_once()
        mock_proc.wait.assert_called_once()

    @patch("neuroflow.cli.worker._read_pid")
    def test_stop_no_worker(self, mock_read_pid, runner, yaml_config):
        """Test stop when no worker is running."""
        mock_read_pid.return_value = None

        result = runner.invoke(
            cli, ["--config", yaml_config, "worker", "stop"]
        )

        assert result.exit_code == 0
        assert "No running worker" in result.output

    @patch("neuroflow.cli.worker.psutil.Process")
    @patch("neuroflow.cli.worker._read_pid")
    def test_stop_with_kill(self, mock_read_pid, mock_process_cls, runner, yaml_config):
        """Test stop escalates to SIGKILL if timeout."""
        import psutil

        mock_read_pid.return_value = 12345
        mock_proc = Mock()
        mock_proc.wait.side_effect = [psutil.TimeoutExpired(30), None]
        mock_process_cls.return_value = mock_proc

        result = runner.invoke(
            cli, ["--config", yaml_config, "worker", "stop", "-t", "1"]
        )

        assert result.exit_code == 0
        assert "sending SIGKILL" in result.output
        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()


class TestWorkerStatus:
    @patch("neuroflow.tasks.get_queue_stats")
    @patch("neuroflow.cli.worker._get_worker_info")
    @patch("neuroflow.cli.worker._read_pid")
    def test_status_running(
        self, mock_read_pid, mock_get_info, mock_get_stats, runner, yaml_config
    ):
        """Test status when worker is running."""
        mock_read_pid.return_value = 12345
        mock_get_info.return_value = {
            "pid": 12345,
            "status": "running",
            "cpu_percent": 10.5,
            "memory_mb": 256.3,
            "num_threads": 5,
            "create_time": time.time() - 3600,  # 1 hour ago
        }
        mock_get_stats.return_value = {"pending": 3, "scheduled": 1}

        result = runner.invoke(
            cli, ["--config", yaml_config, "worker", "status"]
        )

        assert result.exit_code == 0
        assert "Worker: Running" in result.output
        assert "12345" in result.output
        assert "10.5%" in result.output
        assert "256.3 MB" in result.output
        assert "Pending: 3" in result.output
        assert "Scheduled: 1" in result.output

    @patch("neuroflow.tasks.get_queue_stats")
    @patch("neuroflow.cli.worker._read_pid")
    def test_status_not_running(
        self, mock_read_pid, mock_get_stats, runner, yaml_config
    ):
        """Test status when worker is not running."""
        mock_read_pid.return_value = None
        mock_get_stats.return_value = {"pending": 0, "scheduled": 0}

        result = runner.invoke(
            cli, ["--config", yaml_config, "worker", "status"]
        )

        assert result.exit_code == 0
        assert "Worker: Not running" in result.output
        assert "Pending: 0" in result.output

    @patch("neuroflow.tasks.get_queue_stats")
    @patch("neuroflow.cli.worker._get_worker_info")
    @patch("neuroflow.cli.worker._read_pid")
    def test_status_stale_pid(
        self, mock_read_pid, mock_get_info, mock_get_stats, runner, yaml_config
    ):
        """Test status with stale PID file."""
        mock_read_pid.return_value = 12345
        mock_get_info.return_value = None  # Process not found
        mock_get_stats.return_value = {"pending": 0, "scheduled": 0}

        result = runner.invoke(
            cli, ["--config", yaml_config, "worker", "status"]
        )

        assert result.exit_code == 0
        assert "not found" in result.output or "stale" in result.output


class TestWorkerRestart:
    @patch("neuroflow.cli.worker.psutil.Process")
    @patch("neuroflow.cli.worker.subprocess.Popen")
    @patch("neuroflow.cli.worker._read_pid")
    @patch("neuroflow.cli.worker._write_pid")
    @patch("neuroflow.cli.worker.time.sleep")
    def test_restart(
        self,
        mock_sleep,
        mock_write_pid,
        mock_read_pid,
        mock_popen,
        mock_process_cls,
        runner,
        yaml_config,
    ):
        """Test restart command."""
        # First call: worker running (for stop)
        # Second call: no worker (for start)
        mock_read_pid.side_effect = [12345, None]

        # Mock stop
        mock_proc_stop = Mock()
        mock_proc_stop.wait = Mock()
        mock_process_cls.return_value = mock_proc_stop

        # Mock start
        mock_proc_start = Mock()
        mock_proc_start.pid = 54321
        mock_proc_start.poll.return_value = None
        mock_popen.return_value = mock_proc_start

        result = runner.invoke(
            cli, ["--config", yaml_config, "worker", "restart"]
        )

        assert result.exit_code == 0
        assert "Restarting worker" in result.output
        assert "stopped successfully" in result.output
        assert "started successfully" in result.output


class TestPIDFileOperations:
    @patch("neuroflow.cli.worker.psutil.pid_exists")
    def test_read_write_pid(self, mock_pid_exists, tmp_path):
        """Test PID file read/write operations."""
        from neuroflow.cli.worker import _read_pid, _write_pid, _get_pid_file

        mock_pid_exists.return_value = True  # Pretend PID exists

        state_dir = tmp_path / "state"
        pid_file = _get_pid_file(state_dir)

        # Write PID
        _write_pid(pid_file, 12345)
        assert pid_file.exists()

        # Read PID
        pid = _read_pid(pid_file)
        assert pid == 12345

    def test_read_nonexistent_pid(self, tmp_path):
        """Test reading non-existent PID file."""
        from neuroflow.cli.worker import _read_pid, _get_pid_file

        state_dir = tmp_path / "state"
        pid_file = _get_pid_file(state_dir)

        pid = _read_pid(pid_file)
        assert pid is None

    def test_read_invalid_pid(self, tmp_path):
        """Test reading invalid PID file."""
        from neuroflow.cli.worker import _read_pid, _get_pid_file

        state_dir = tmp_path / "state"
        pid_file = _get_pid_file(state_dir)

        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text("not_a_number")

        pid = _read_pid(pid_file)
        assert pid is None
