"""Facade over Todoist SDK operations used by CLI commands."""

from typing import Any

import requests
from todoist_api_python.api import TodoistAPI

from .sdk import collect_pages


def _split_filter_sections(query: str) -> list[str]:
    # Todoist filter "comma sections" are not supported by the newer filter endpoint, so we
    # emulate them by splitting on top-level commas and concatenating results.
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in query:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            part = "".join(buf).strip()
            if part:
                parts.append(part)
            buf = []
            continue
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts or [query]


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

    def list_tasks_by_filter(
        self,
        filter_query: str,
        *,
        timeout_s: float = 10.0,
        per_page: int = 200,
        max_results: int | None = None,
        lang: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Return tasks matching native Todoist filter syntax.

        Note: Todoist removed the `filter=` query parameter from the v2 tasks endpoint.
        The supported endpoint is API v1 `GET /api/v1/tasks/filter?query=...`.
        """
        headers = {"Authorization": f"Bearer {self._token}"}

        all_results: list[dict[str, Any]] = []
        for section in _split_filter_sections(filter_query):
            cursor: str | None = None
            while True:
                params: dict[str, Any] = {"query": section, "limit": per_page}
                if cursor:
                    params["cursor"] = cursor
                if lang:
                    params["lang"] = lang

                resp = requests.get(
                    "https://api.todoist.com/api/v1/tasks/filter",
                    headers=headers,
                    params=params,
                    timeout=timeout_s,
                )
                resp.raise_for_status()
                payload = resp.json()
                if not isinstance(payload, dict):
                    raise ValueError("Todoist API returned non-object tasks/filter payload")
                results = payload.get("results")
                if not isinstance(results, list):
                    raise ValueError("Todoist API returned tasks/filter payload without list results")
                all_results.extend(results)

                if max_results is not None and len(all_results) >= max_results:
                    return all_results[:max_results]

                cursor = payload.get("next_cursor")
                if not cursor:
                    break

        return all_results
