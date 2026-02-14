"""Facade over Todoist SDK operations used by CLI commands."""

from typing import Any

from todoist_api_python.api import TodoistAPI

from .sdk import collect_pages


class TodoistClient:
    """Thin client that hides Todoist SDK pagination details."""

    def __init__(self, token: str, api: TodoistAPI | None = None):
        self._api = api or TodoistAPI(token)

    def list_projects(self) -> list[Any]:
        """Return all projects as a flat list."""
        return collect_pages(self._api.get_projects())

    def list_tasks(self, **kwargs: Any) -> list[Any]:
        """Return tasks matching optional Todoist API filters."""
        return collect_pages(self._api.get_tasks(**kwargs))
