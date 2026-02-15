"""Facade over Todoist SDK operations used by CLI commands."""

from typing import Any

import requests
from todoist_api_python.api import TodoistAPI

from .sdk import collect_pages


class TodoistClient:
    """Thin client that hides Todoist SDK pagination details."""

    def __init__(self, token: str, api: TodoistAPI | None = None):
        self._token = token
        self._api = api or TodoistAPI(token)

    def list_projects(self) -> list[Any]:
        """Return all projects as a flat list."""
        return collect_pages(self._api.get_projects())

    def list_tasks(self, **kwargs: Any) -> list[Any]:
        """Return tasks matching optional Todoist API filters."""
        return collect_pages(self._api.get_tasks(**kwargs))

    def list_tasks_by_filter(self, filter_query: str, *, timeout_s: float = 10.0) -> list[dict[str, Any]]:
        """
        Return tasks matching native Todoist filter syntax.

        This uses Todoist REST v2 directly because the official Python SDK does not expose the full
        filter-query surface (e.g. boolean ops, sections, etc).
        """
        resp = requests.get(
            "https://api.todoist.com/rest/v2/tasks",
            headers={"Authorization": f"Bearer {self._token}"},
            params={"filter": filter_query},
            timeout=timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            raise ValueError("Todoist REST returned non-list tasks payload")
        return data
