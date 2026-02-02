"""Tests for configuration handling."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from todoist_cli.config import get_token, get_config, save_config


def test_get_token_from_env(monkeypatch):
    """Token from environment takes precedence."""
    monkeypatch.setenv("TODOIST_API_TOKEN", "env_token_123")
    assert get_token() == "env_token_123"


def test_get_token_from_config(tmp_path, monkeypatch):
    """Token from config file when env not set."""
    monkeypatch.delenv("TODOIST_API_TOKEN", raising=False)

    config_dir = tmp_path / ".config" / "todoist"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "config.json"
    config_file.write_text(json.dumps({"token": "config_token_456"}))

    with patch("todoist_cli.config.CONFIG_FILE", config_file):
        assert get_token() == "config_token_456"


def test_get_token_none(tmp_path, monkeypatch):
    """Returns None when no token configured."""
    monkeypatch.delenv("TODOIST_API_TOKEN", raising=False)

    config_file = tmp_path / "nonexistent.json"
    with patch("todoist_cli.config.CONFIG_FILE", config_file):
        assert get_token() is None


def test_save_config_creates_file(tmp_path):
    """Config file is created with correct permissions."""
    config_dir = tmp_path / ".config" / "todoist"
    config_file = config_dir / "config.json"

    with patch("todoist_cli.config.CONFIG_DIR", config_dir):
        with patch("todoist_cli.config.CONFIG_FILE", config_file):
            save_config({"token": "test_token"})

            assert config_file.exists()
            assert json.loads(config_file.read_text()) == {"token": "test_token"}
            # Check file permissions (600 = owner read/write only)
            assert oct(config_file.stat().st_mode)[-3:] == "600"
