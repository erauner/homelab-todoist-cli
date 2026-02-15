"""Tests for Todoist client facade and SDK helpers."""

from unittest.mock import MagicMock, patch

from todoist_cli.todoist.client import TodoistClient
from todoist_cli.todoist.sdk import collect_pages


def test_collect_pages_flattens_paginator():
    pages = iter([[1, 2], [3], []])
    assert collect_pages(pages) == [1, 2, 3]


def test_collect_pages_accepts_plain_list():
    assert collect_pages([1, 2, 3]) == [1, 2, 3]


def test_todoist_client_list_projects_and_tasks_are_flattened():
    api = MagicMock()
    project_1 = MagicMock(id="p1", name="Inbox")
    project_2 = MagicMock(id="p2", name="Work")
    task_1 = MagicMock(id="t1")
    task_2 = MagicMock(id="t2")

    api.get_projects.return_value = iter([[project_1], [project_2]])
    api.get_tasks.return_value = [task_1, task_2]

    client = TodoistClient(token="test_token", api=api)

    assert client.list_projects() == [project_1, project_2]
    assert client.list_tasks(project_id="p2") == [task_1, task_2]
    api.get_tasks.assert_called_once_with(project_id="p2")


def test_list_tasks_by_filter_calls_rest_with_params_and_auth_header():
    api = MagicMock()
    client = TodoistClient(token="test_token", api=api)

    with patch("todoist_cli.todoist.client.requests.get") as get:
        resp = MagicMock()
        resp.json.return_value = [{"id": "1", "content": "One"}]
        resp.raise_for_status.return_value = None
        get.return_value = resp

        tasks = client.list_tasks_by_filter("(today | overdue) & #Work")

        assert tasks == [{"id": "1", "content": "One"}]
        get.assert_called_once()
        call_kwargs = get.call_args.kwargs
        assert call_kwargs["params"] == {"filter": "(today | overdue) & #Work"}
        assert call_kwargs["headers"] == {"Authorization": "Bearer test_token"}
