"""Tests for Todoist client facade and SDK helpers."""

from unittest.mock import MagicMock

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
