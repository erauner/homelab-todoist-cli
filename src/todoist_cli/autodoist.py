"""HTTP client for Autodoist debug API endpoints."""

from __future__ import annotations

from typing import Any

import requests


class AutodoistClientError(RuntimeError):
    """Raised when Autodoist API requests fail."""


class AutodoistClient:
    """Minimal client for Autodoist web UI/API integration."""

    def __init__(self, base_url: str, timeout_s: float = 10.0):
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            response = requests.request(
                method,
                url,
                params=params,
                json=json,
                timeout=self._timeout_s,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise AutodoistClientError(f"Request failed: {exc}") from exc
        except ValueError as exc:
            raise AutodoistClientError("Autodoist API returned invalid JSON") from exc

        if not isinstance(payload, dict):
            raise AutodoistClientError("Autodoist API returned non-object payload")
        return payload

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/api/health")

    def state(self) -> dict[str, Any]:
        return self._request("GET", "/api/state")

    def tasks(self, *, label: str | None = None, contains: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if label:
            params["label"] = label
        if contains:
            params["contains"] = contains
        return self._request("GET", "/api/tasks", params=params or None)

    def reconcile_focus(
        self,
        *,
        apply: bool = False,
        winner_task_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"apply": apply}
        if winner_task_id:
            body["winner_task_id"] = winner_task_id
        return self._request("POST", "/api/focus/reconcile", json=body)

    def task_label_action(self, task_id: str, action: str) -> dict[str, Any]:
        return self._request("POST", f"/api/tasks/{task_id}/labels", json={"action": action})
