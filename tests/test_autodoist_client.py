"""Tests for Autodoist client."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from todoist_cli.autodoist import AutodoistClient, AutodoistClientError


def test_health_calls_expected_path():
    client = AutodoistClient("https://autodoist.example.com/")

    with patch("todoist_cli.autodoist.requests.request") as req:
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"ok": True}
        req.return_value = resp

        payload = client.health()

        assert payload == {"ok": True}
        req.assert_called_once_with(
            "GET",
            "https://autodoist.example.com/api/health",
            params=None,
            json=None,
            timeout=10.0,
        )


def test_tasks_passes_optional_filters():
    client = AutodoistClient("https://autodoist.example.com")

    with patch("todoist_cli.autodoist.requests.request") as req:
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"tasks": []}
        req.return_value = resp

        client.tasks(label="doing_now", contains="hello")

        req.assert_called_once_with(
            "GET",
            "https://autodoist.example.com/api/tasks",
            params={"label": "doing_now", "contains": "hello"},
            json=None,
            timeout=10.0,
        )


def test_reconcile_posts_payload():
    client = AutodoistClient("https://autodoist.example.com")

    with patch("todoist_cli.autodoist.requests.request") as req:
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"ok": True}
        req.return_value = resp

        client.reconcile_doing_now(apply=True, winner_task_id="abc123")

        req.assert_called_once_with(
            "POST",
            "https://autodoist.example.com/api/doing-now/reconcile",
            params=None,
            json={"apply": True, "winner_task_id": "abc123"},
            timeout=10.0,
        )


def test_request_exception_wrapped():
    client = AutodoistClient("https://autodoist.example.com")

    with patch("todoist_cli.autodoist.requests.request", side_effect=requests.RequestException("boom")):
        with pytest.raises(AutodoistClientError):
            client.state()
