"""SDK helpers for Todoist API integration."""

from typing import Any, TypeVar

T = TypeVar("T")


def collect_pages(result: Any) -> list[T]:
    """Normalize Todoist SDK list/paginator results into a single list."""
    if result is None:
        return []

    if isinstance(result, list):
        return result

    items: list[T] = []
    for chunk in result:
        if isinstance(chunk, list):
            items.extend(chunk)
        else:
            items.append(chunk)
    return items
