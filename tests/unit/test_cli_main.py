"""Tests for CLI main entry point."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from neuroflow.cli.main import _find_config_path, cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def yaml_config(tmp_path):
    """Write a minimal valid config to a temp file."""
    cfg = tmp_path / "neuroflow.yaml"
    cfg.write_text(
        """\
paths:
  dicom_incoming: /tmp/incoming
  bids_root: /tmp/bids
  derivatives: /tmp/derivatives
"""
    )
    return str(cfg)


class TestCli:
    def test_help(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Neuroflow" in result.output

    @patch("neuroflow.cli.main.NeuroflowConfig.find_and_load")
    def test_missing_config(self, mock_find, runner):
        mock_find.side_effect = FileNotFoundError("No configuration file found.")
        result = runner.invoke(cli, ["status"])
        assert result.exit_code != 0
        assert "No configuration file found" in result.output

    def test_with_valid_config(self, runner, yaml_config):
        result = runner.invoke(cli, ["--config", yaml_config, "status"])
        assert result.exit_code == 0

    def test_dry_run_flag(self, runner, yaml_config):
        result = runner.invoke(cli, ["--config", yaml_config, "--dry-run", "status"])
        assert result.exit_code == 0

    def test_log_level_override(self, runner, yaml_config):
        result = runner.invoke(
            cli, ["--config", yaml_config, "--log-level", "WARNING", "status"]
        )
        assert result.exit_code == 0


class TestConfigShow:
    def test_show_full_config(self, runner, yaml_config):
        result = runner.invoke(cli, ["--config", yaml_config, "config", "show"])
        assert result.exit_code == 0
        assert "paths" in result.output

    def test_show_section(self, runner, yaml_config):
        result = runner.invoke(
            cli, ["--config", yaml_config, "config", "show", "--section", "paths"]
        )
        assert result.exit_code == 0
        assert "dicom_incoming" in result.output

    def test_show_unknown_section(self, runner, yaml_config):
        result = runner.invoke(
            cli,
            ["--config", yaml_config, "config", "show", "--section", "nonexistent"],
        )
        assert result.exit_code != 0


class TestConfigValidate:
    def test_validate_valid_config(self, runner, yaml_config):
        result = runner.invoke(
            cli,
            ["--config", yaml_config, "config", "validate", "--config-file", yaml_config],
        )
        assert result.exit_code == 0
        assert "valid" in result.output.lower()

    def test_validate_invalid_config(self, runner, yaml_config, tmp_path):
        bad_cfg = tmp_path / "bad.yaml"
        bad_cfg.write_text("paths: {}")
        result = runner.invoke(
            cli,
            ["--config", yaml_config, "config", "validate", "--config-file", str(bad_cfg)],
        )
        assert result.exit_code != 0

    def test_validate_current_config(self, runner, yaml_config):
        result = runner.invoke(
            cli, ["--config", yaml_config, "config", "validate"]
        )
        assert result.exit_code == 0
        assert "valid" in result.output.lower()


class TestFindConfigPath:
    def test_finds_env_variable(self, tmp_path, monkeypatch):
        cfg = tmp_path / "env_config.yaml"
        cfg.write_text("test: true")
        monkeypatch.setenv("NEUROFLOW_CONFIG", str(cfg))
        result = _find_config_path()
        assert result == str(cfg.resolve())

    def test_finds_local_config(self, tmp_path, monkeypatch):
        monkeypatch.delenv("NEUROFLOW_CONFIG", raising=False)
        monkeypatch.chdir(tmp_path)
        cfg = tmp_path / "neuroflow.yaml"
        cfg.write_text("test: true")
        result = _find_config_path()
        assert result == str(cfg.resolve())

    def test_fallback_when_no_config(self, tmp_path, monkeypatch):
        monkeypatch.delenv("NEUROFLOW_CONFIG", raising=False)
        monkeypatch.chdir(tmp_path)
        # _find_config_path falls back to ./neuroflow.yaml if nothing found,
        # or picks up /etc/neuroflow/neuroflow.yaml if it exists on the system
        result = _find_config_path()
        # Should return a path (either fallback or system config)
        assert isinstance(result, str)
        assert "neuroflow.yaml" in result
