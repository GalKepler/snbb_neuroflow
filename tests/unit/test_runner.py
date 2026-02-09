"""Tests for parallel pipeline runner."""

from concurrent.futures import Future
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from neuroflow.adapters.voxelops import PipelineResult
from neuroflow.runner import PipelineRunner, RunRequest, RunResult


class TestRunRequest:
    def test_defaults(self):
        req = RunRequest(
            participant_id="sub-001",
            session_id="ses-baseline",
            dicom_path="/data/sub-001/ses-baseline",
            pipeline_name="qsiprep",
        )
        assert req.force is False

    def test_force_flag(self):
        req = RunRequest(
            participant_id="sub-001",
            session_id="ses-baseline",
            dicom_path="/data/sub-001",
            pipeline_name="qsiprep",
            force=True,
        )
        assert req.force is True


class TestRunResult:
    def test_with_pipeline_result(self):
        req = RunRequest("sub-001", "ses-01", "/data", "qsiprep")
        pr = PipelineResult(success=True, exit_code=0, duration_seconds=120.5)
        result = RunResult(request=req, pipeline_result=pr, log_path="/tmp/log.txt")
        assert result.pipeline_result.success is True
        assert result.log_path == "/tmp/log.txt"
        assert result.error == ""

    def test_with_error(self):
        req = RunRequest("sub-001", "ses-01", "/data", "qsiprep")
        result = RunResult(request=req, pipeline_result=None, error="Something broke")
        assert result.pipeline_result is None
        assert result.error == "Something broke"


class TestPipelineRunnerDryRun:
    def test_dry_run_returns_results_without_running(self, config, tmp_path):
        runner = PipelineRunner(config, str(tmp_path / "config.yaml"))
        requests = [
            RunRequest("sub-001", "ses-01", "/data/001", "qsiprep"),
            RunRequest("sub-002", "ses-01", "/data/002", "qsiprep"),
        ]
        results = runner.run_batch(requests, dry_run=True)
        assert len(results) == 2
        for r in results:
            assert r.pipeline_result is None
            assert r.error == ""

    def test_dry_run_empty_requests(self, config, tmp_path):
        runner = PipelineRunner(config, str(tmp_path / "config.yaml"))
        results = runner.run_batch([], dry_run=True)
        assert results == []


def _make_future(result):
    """Create a completed Future with the given result."""
    f = Future()
    f.set_result(result)
    return f


def _make_failed_future(exc):
    """Create a completed Future that raises the given exception."""
    f = Future()
    f.set_exception(exc)
    return f


class _FakeExecutor:
    """A synchronous executor that records calls and returns preset futures."""

    def __init__(self, results_or_errors, **kwargs):
        self._results_or_errors = list(results_or_errors)
        self._idx = 0
        self.calls = []

    def submit(self, fn, **kwargs):
        self.calls.append(kwargs)
        item = self._results_or_errors[self._idx]
        self._idx += 1
        if isinstance(item, Exception):
            return _make_failed_future(item)
        return _make_future(item)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class TestPipelineRunnerBatch:
    def test_empty_requests(self, config, tmp_path):
        runner = PipelineRunner(config, str(tmp_path / "config.yaml"))
        results = runner.run_batch([])
        assert results == []

    @patch("neuroflow.runner.ProcessPoolExecutor")
    def test_successful_run(self, mock_executor_cls, config, tmp_path):
        result_dict = {
            "success": True,
            "exit_code": 0,
            "output_path": "/out/qsiprep",
            "error_message": "",
            "duration_seconds": 60.0,
            "log_path": "/logs/test.log",
        }
        mock_executor_cls.return_value = _FakeExecutor([result_dict])

        runner = PipelineRunner(config, str(tmp_path / "config.yaml"))
        requests = [RunRequest("sub-001", "ses-01", "/data/001", "qsiprep")]
        results = runner.run_batch(requests)

        assert len(results) == 1
        assert results[0].pipeline_result.success is True
        assert results[0].pipeline_result.exit_code == 0
        assert results[0].pipeline_result.output_path == Path("/out/qsiprep")
        assert results[0].log_path == "/logs/test.log"

    @patch("neuroflow.runner.ProcessPoolExecutor")
    def test_failed_run(self, mock_executor_cls, config, tmp_path):
        result_dict = {
            "success": False,
            "exit_code": 1,
            "output_path": "",
            "error_message": "Pipeline crashed",
            "duration_seconds": 10.0,
            "log_path": "/logs/test.log",
        }
        mock_executor_cls.return_value = _FakeExecutor([result_dict])

        runner = PipelineRunner(config, str(tmp_path / "config.yaml"))
        requests = [RunRequest("sub-001", "ses-01", "/data/001", "qsiprep")]
        results = runner.run_batch(requests)

        assert len(results) == 1
        assert results[0].pipeline_result.success is False
        assert results[0].pipeline_result.error_message == "Pipeline crashed"
        assert results[0].pipeline_result.output_path is None

    @patch("neuroflow.runner.ProcessPoolExecutor")
    def test_exception_in_worker(self, mock_executor_cls, config, tmp_path):
        mock_executor_cls.return_value = _FakeExecutor(
            [RuntimeError("Worker process died")]
        )

        runner = PipelineRunner(config, str(tmp_path / "config.yaml"))
        requests = [RunRequest("sub-001", "ses-01", "/data/001", "qsiprep")]
        results = runner.run_batch(requests)

        assert len(results) == 1
        assert results[0].pipeline_result is None
        assert "Worker process died" in results[0].error

    @patch("neuroflow.runner.ProcessPoolExecutor")
    def test_mixed_results(self, mock_executor_cls, config, tmp_path):
        mock_executor_cls.return_value = _FakeExecutor([
            {
                "success": True,
                "exit_code": 0,
                "output_path": "/out/001",
                "error_message": "",
                "duration_seconds": 60.0,
                "log_path": "",
            },
            {
                "success": False,
                "exit_code": 1,
                "output_path": "",
                "error_message": "failed",
                "duration_seconds": 5.0,
                "log_path": "",
            },
        ])

        runner = PipelineRunner(config, str(tmp_path / "config.yaml"))
        requests = [
            RunRequest("sub-001", "ses-01", "/data/001", "qsiprep"),
            RunRequest("sub-002", "ses-01", "/data/002", "qsiprep"),
        ]
        results = runner.run_batch(requests)

        assert len(results) == 2
        succeeded = [r for r in results if r.pipeline_result and r.pipeline_result.success]
        failed = [r for r in results if r.pipeline_result and not r.pipeline_result.success]
        assert len(succeeded) == 1
        assert len(failed) == 1

    @patch("neuroflow.runner.ProcessPoolExecutor")
    def test_force_flag_passed_through(self, mock_executor_cls, config, tmp_path):
        result_dict = {
            "success": True,
            "exit_code": 0,
            "output_path": "",
            "error_message": "",
            "duration_seconds": 1.0,
            "log_path": "",
        }
        fake_executor = _FakeExecutor([result_dict])
        mock_executor_cls.return_value = fake_executor

        runner = PipelineRunner(config, str(tmp_path / "config.yaml"))
        requests = [RunRequest("sub-001", "ses-01", "/data/001", "qsiprep", force=True)]
        runner.run_batch(requests)

        assert fake_executor.calls[0]["force"] is True

    @patch("neuroflow.runner.ProcessPoolExecutor")
    def test_log_dir_passed_when_log_per_session(self, mock_executor_cls, config, tmp_path):
        config.execution.log_per_session = True
        result_dict = {
            "success": True,
            "exit_code": 0,
            "output_path": "",
            "error_message": "",
            "duration_seconds": 1.0,
            "log_path": "",
        }
        fake_executor = _FakeExecutor([result_dict])
        mock_executor_cls.return_value = fake_executor

        runner = PipelineRunner(config, str(tmp_path / "config.yaml"))
        requests = [RunRequest("sub-001", "ses-01", "/data/001", "qsiprep")]
        runner.run_batch(requests)

        assert fake_executor.calls[0]["log_dir"] != ""

    @patch("neuroflow.runner.ProcessPoolExecutor")
    def test_no_log_dir_when_disabled(self, mock_executor_cls, config, tmp_path):
        config.execution.log_per_session = False
        result_dict = {
            "success": True,
            "exit_code": 0,
            "output_path": "",
            "error_message": "",
            "duration_seconds": 1.0,
            "log_path": "",
        }
        fake_executor = _FakeExecutor([result_dict])
        mock_executor_cls.return_value = fake_executor

        runner = PipelineRunner(config, str(tmp_path / "config.yaml"))
        requests = [RunRequest("sub-001", "ses-01", "/data/001", "qsiprep")]
        runner.run_batch(requests)

        assert fake_executor.calls[0]["log_dir"] == ""


class TestRunSinglePipeline:
    """Test run_single_pipeline with mocked adapter.

    The function imports VoxelopsAdapter locally, so we patch at source.
    """

    @patch("neuroflow.adapters.voxelops.VoxelopsAdapter", autospec=True)
    @patch("neuroflow.config.NeuroflowConfig.from_yaml")
    def test_successful_execution(self, mock_from_yaml, mock_adapter_cls, config, tmp_path):
        mock_from_yaml.return_value = config
        mock_adapter = MagicMock()
        mock_adapter.run.return_value = PipelineResult(
            success=True,
            exit_code=0,
            output_path=Path("/out/qsiprep"),
            duration_seconds=120.0,
            logs="stdout output",
        )
        mock_adapter_cls.return_value = mock_adapter

        from neuroflow.runner import run_single_pipeline

        result = run_single_pipeline(
            config_path=str(tmp_path / "config.yaml"),
            participant_id="sub-001",
            session_id="ses-01",
            dicom_path="/data/001",
            pipeline_name="qsiprep",
            log_dir="",
        )

        assert result["success"] is True
        assert result["exit_code"] == 0
        assert result["output_path"] == "/out/qsiprep"

    @patch("neuroflow.adapters.voxelops.VoxelopsAdapter", autospec=True)
    @patch("neuroflow.config.NeuroflowConfig.from_yaml")
    def test_failed_execution(self, mock_from_yaml, mock_adapter_cls, config, tmp_path):
        mock_from_yaml.return_value = config
        mock_adapter = MagicMock()
        mock_adapter.run.return_value = PipelineResult(
            success=False,
            exit_code=1,
            error_message="Segfault in container",
            duration_seconds=5.0,
        )
        mock_adapter_cls.return_value = mock_adapter

        from neuroflow.runner import run_single_pipeline

        result = run_single_pipeline(
            config_path=str(tmp_path / "config.yaml"),
            participant_id="sub-001",
            session_id="ses-01",
            dicom_path="/data/001",
            pipeline_name="qsiprep",
            log_dir="",
        )

        assert result["success"] is False
        assert result["error_message"] == "Segfault in container"

    @patch("neuroflow.adapters.voxelops.VoxelopsAdapter", autospec=True)
    @patch("neuroflow.config.NeuroflowConfig.from_yaml")
    def test_exception_in_adapter(self, mock_from_yaml, mock_adapter_cls, config, tmp_path):
        mock_from_yaml.return_value = config
        mock_adapter = MagicMock()
        mock_adapter.run.side_effect = RuntimeError("Adapter crashed")
        mock_adapter_cls.return_value = mock_adapter

        from neuroflow.runner import run_single_pipeline

        result = run_single_pipeline(
            config_path=str(tmp_path / "config.yaml"),
            participant_id="sub-001",
            session_id="ses-01",
            dicom_path="/data/001",
            pipeline_name="qsiprep",
            log_dir="",
        )

        assert result["success"] is False
        assert result["exit_code"] == -1
        assert "Adapter crashed" in result["error_message"]

    @patch("neuroflow.adapters.voxelops.VoxelopsAdapter", autospec=True)
    @patch("neuroflow.config.NeuroflowConfig.from_yaml")
    def test_with_session_logging(self, mock_from_yaml, mock_adapter_cls, config, tmp_path):
        mock_from_yaml.return_value = config
        mock_adapter = MagicMock()
        mock_adapter.run.return_value = PipelineResult(
            success=True,
            exit_code=0,
            duration_seconds=10.0,
            logs="pipeline stdout",
            error_message=None,
            metrics={"volume": 42},
        )
        mock_adapter_cls.return_value = mock_adapter

        log_dir = tmp_path / "logs"
        log_dir.mkdir(exist_ok=True)

        from neuroflow.runner import run_single_pipeline

        result = run_single_pipeline(
            config_path=str(tmp_path / "config.yaml"),
            participant_id="sub-001",
            session_id="ses-01",
            dicom_path="/data/001",
            pipeline_name="qsiprep",
            log_dir=str(log_dir),
        )

        assert result["success"] is True
        assert result["log_path"] != ""
        log_path = Path(result["log_path"])
        assert log_path.exists()
        # Reset logging for other tests
        from neuroflow.core.logging import setup_logging
        setup_logging(level="DEBUG", format="console")

    @patch("neuroflow.adapters.voxelops.VoxelopsAdapter", autospec=True)
    @patch("neuroflow.config.NeuroflowConfig.from_yaml")
    def test_force_kwarg_passed_to_adapter(self, mock_from_yaml, mock_adapter_cls, config, tmp_path):
        mock_from_yaml.return_value = config
        mock_adapter = MagicMock()
        mock_adapter.run.return_value = PipelineResult(
            success=True, exit_code=0, duration_seconds=1.0
        )
        mock_adapter_cls.return_value = mock_adapter

        from neuroflow.runner import run_single_pipeline

        run_single_pipeline(
            config_path=str(tmp_path / "config.yaml"),
            participant_id="sub-001",
            session_id="ses-01",
            dicom_path="/data/001",
            pipeline_name="qsiprep",
            log_dir="",
            force=True,
        )

        mock_adapter.run.assert_called_once()
        call_kwargs = mock_adapter.run.call_args[1]
        assert call_kwargs["force"] is True

    @patch("neuroflow.adapters.voxelops.VoxelopsAdapter", autospec=True)
    @patch("neuroflow.config.NeuroflowConfig.from_yaml")
    def test_empty_dicom_path(self, mock_from_yaml, mock_adapter_cls, config, tmp_path):
        mock_from_yaml.return_value = config
        mock_adapter = MagicMock()
        mock_adapter.run.return_value = PipelineResult(
            success=True, exit_code=0, duration_seconds=1.0
        )
        mock_adapter_cls.return_value = mock_adapter

        from neuroflow.runner import run_single_pipeline

        run_single_pipeline(
            config_path=str(tmp_path / "config.yaml"),
            participant_id="sub-001",
            session_id="ses-01",
            dicom_path="",
            pipeline_name="qsiprep",
            log_dir="",
        )

        call_kwargs = mock_adapter.run.call_args[1]
        assert call_kwargs["dicom_path"] is None
