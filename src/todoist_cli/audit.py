"""
GTD audit functionality for Todoist CLI.

Audits GTD project health by checking for next action coverage and staleness.
Follows Autodoist conventions for identifying GTD projects (- or = suffix).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any, TypeVar

from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from rich.console import Console
    from todoist_api_python.api import TodoistAPI
    from todoist_api_python.models import Project, Task


# GTD suffix pattern: 1-3 trailing characters of - or =
# Matches Autodoist conventions for sequential (-) and parallel (=) projects
GTD_SUFFIX_PATTERN = re.compile(r"[-=]{1,3}$")

T = TypeVar("T")


def _flatten_pages(maybe_pages: Iterable[Any]) -> list[T]:
    """
    Flatten API results that may be paginated or flat.

    The Todoist SDK may return either:
    - An iterator of pages (list of items)
    - An iterator of items directly

    This helper handles both cases safely.
    """
    out: list[T] = []
    for chunk in maybe_pages:
        if isinstance(chunk, list):
            out.extend(chunk)
        else:
            out.append(chunk)
    return out


@dataclass
class TaskInfo:
    """Information about a next action task."""

    id: str
    content: str
    project_name: str
    days_stale: int
    created_at: str


@dataclass
class ProjectInfo:
    """Information about a GTD project."""

    id: str
    name: str
    task_count: int  # non-completed tasks in project


@dataclass
class AuditResult:
    """Results of a GTD audit."""

    gtd_projects: list[ProjectInfo] = field(default_factory=list)
    projects_with_next: list[ProjectInfo] = field(default_factory=list)
    projects_without_next: list[ProjectInfo] = field(default_factory=list)
    next_action_tasks: list[TaskInfo] = field(default_factory=list)
    stale_tasks: list[TaskInfo] = field(default_factory=list)
    health_score: int = 0


def is_gtd_project(name: str) -> bool:
    """
    Check if a project name indicates a GTD project.

    GTD projects are identified by Autodoist-style suffixes:
    - Sequential projects end with '-' (or up to 3: '--', '---')
    - Parallel projects end with '=' (or up to 3: '==', '===')
    - Mixed suffixes are also valid (e.g., '=-=')

    Args:
        name: The project name to check.

    Returns:
        True if the project has a GTD suffix, False otherwise.
    """
    if not name:
        return False
    return bool(GTD_SUFFIX_PATTERN.search(name.rstrip()))


def compute_health_score(
    gtd_projects: list[ProjectInfo],
    projects_with_next: list[ProjectInfo],
    next_action_tasks: list[TaskInfo],
    stale_tasks: list[TaskInfo],
) -> int:
    """
    Compute a health score (0-100) based on project coverage and task freshness.

    Weighting:
    - 70% weight: project coverage (GTD projects with at least one next action)
    - 30% weight: task freshness (next actions that are not stale)

    Edge cases:
    - Zero GTD projects: project_score = 1.0 (nothing to audit)
    - Zero next actions: freshness_score = 1.0 (nothing stale)

    Args:
        gtd_projects: All GTD projects.
        projects_with_next: GTD projects that have at least one next action.
        next_action_tasks: All tasks with the next action label.
        stale_tasks: Next action tasks older than the staleness threshold.

    Returns:
        Health score from 0 to 100.
    """
    # 70% weight: project coverage
    if len(gtd_projects) > 0:
        project_score = len(projects_with_next) / len(gtd_projects)
    else:
        project_score = 1.0  # No GTD projects = nothing to audit

    # 30% weight: task freshness
    if len(next_action_tasks) > 0:
        freshness_score = 1.0 - (len(stale_tasks) / len(next_action_tasks))
    else:
        freshness_score = 1.0  # No next actions = nothing stale

    return int(project_score * 70 + freshness_score * 30)


def format_score_label(score: int) -> str:
    """
    Return a label describing the health score.

    Args:
        score: Health score from 0 to 100.

    Returns:
        "Excellent" (90+), "Good" (70+), "Needs Attention" (50+), or "Critical" (<50).
    """
    if score >= 90:
        return "Excellent"
    elif score >= 70:
        return "Good"
    elif score >= 50:
        return "Needs Attention"
    else:
        return "Critical"


def run_audit(
    api: TodoistAPI,
    label_name: str,
    stale_days: int,
) -> AuditResult:
    """
    Run a GTD audit against the Todoist account.

    This function:
    1. Fetches all projects and identifies GTD projects (- or = suffix)
    2. Fetches all tasks and groups them by project
    3. Determines which GTD projects have next action labeled tasks
    4. Identifies stale next action tasks (created_at older than threshold)
    5. Computes a health score

    Note: Staleness is based on task.created_at since the Todoist REST API
    doesn't expose updated_at. A task created long ago but actively worked on
    may appear stale even if it's being progressed. This is a known limitation.

    Args:
        api: Todoist API client.
        label_name: Label name identifying next actions (e.g., "next_action").
        stale_days: Number of days after which a next action is considered stale.

    Returns:
        AuditResult containing all audit data and computed health score.
    """
    # Fetch all projects (handles both paginated and flat SDK responses)
    projects: list[Project] = _flatten_pages(api.get_projects())

    # Build project name lookup
    project_name_by_id: dict[str, str] = {p.id: p.name for p in projects}

    # Identify GTD projects
    gtd_project_ids: set[str] = set()
    for project in projects:
        if is_gtd_project(project.name):
            gtd_project_ids.add(project.id)

    # Fetch all tasks (handles both paginated and flat SDK responses)
    all_tasks: list[Task] = _flatten_pages(api.get_tasks())

    # Group tasks by project_id (for GTD projects only)
    tasks_by_project: dict[str, list[Task]] = {pid: [] for pid in gtd_project_ids}
    for task in all_tasks:
        if task.project_id in gtd_project_ids:
            tasks_by_project[task.project_id].append(task)

    # Build ProjectInfo for each GTD project and partition by next action presence
    gtd_projects: list[ProjectInfo] = []
    projects_with_next: list[ProjectInfo] = []
    projects_without_next: list[ProjectInfo] = []
    project_ids_with_next: set[str] = set()

    for pid in gtd_project_ids:
        tasks = tasks_by_project[pid]
        has_next = any(label_name in (task.labels or []) for task in tasks)

        project_info = ProjectInfo(
            id=pid,
            name=project_name_by_id[pid],
            task_count=len(tasks),
        )
        gtd_projects.append(project_info)

        if has_next:
            projects_with_next.append(project_info)
            project_ids_with_next.add(pid)
        else:
            projects_without_next.append(project_info)

    # Sort projects by name for consistent output
    gtd_projects.sort(key=lambda p: p.name.lower())
    projects_with_next.sort(key=lambda p: p.name.lower())
    projects_without_next.sort(key=lambda p: p.name.lower())

    # Find all next action tasks globally
    today = date.today()
    next_action_tasks: list[TaskInfo] = []
    stale_tasks: list[TaskInfo] = []

    for task in all_tasks:
        labels = task.labels or []
        if label_name in labels:
            # Parse created_at to compute staleness
            # created_at is ISO format like "2024-01-15T10:30:00Z"
            created_at = getattr(task, "created_at", None)
            if not created_at or len(created_at) < 10:
                # Skip tasks with missing/invalid created_at
                continue

            try:
                created_date_str = created_at[:10]
                created_date = date.fromisoformat(created_date_str)
            except ValueError:
                # Skip tasks with unparseable dates
                continue

            days_since_created = (today - created_date).days

            task_info = TaskInfo(
                id=task.id,
                content=task.content,
                project_name=project_name_by_id.get(task.project_id, "Unknown"),
                days_stale=days_since_created,
                created_at=created_date_str,
            )
            next_action_tasks.append(task_info)

            if days_since_created > stale_days:
                stale_tasks.append(task_info)

    # Sort stale tasks by staleness (most stale first)
    stale_tasks.sort(key=lambda t: t.days_stale, reverse=True)

    # Compute health score
    health_score = compute_health_score(
        gtd_projects,
        projects_with_next,
        next_action_tasks,
        stale_tasks,
    )

    return AuditResult(
        gtd_projects=gtd_projects,
        projects_with_next=projects_with_next,
        projects_without_next=projects_without_next,
        next_action_tasks=next_action_tasks,
        stale_tasks=stale_tasks,
        health_score=health_score,
    )


def print_audit(result: AuditResult, stale_days: int, console: Console) -> None:
    """
    Print a formatted audit report using Rich.

    Args:
        result: The audit result to display.
        stale_days: The staleness threshold (for display purposes).
        console: Rich console for output.
    """
    # Check for empty GTD setup
    if not result.gtd_projects and not result.next_action_tasks:
        console.print()
        console.print(
            "[yellow]No GTD projects or next actions found.[/yellow]"
        )
        console.print(
            "Tip: GTD projects should end with '-' (sequential) or '=' (parallel)."
        )
        console.print(
            "See Autodoist conventions: https://github.com/Hoffelhas/autodoist"
        )
        return

    # Health score with color
    score = result.health_score
    label = format_score_label(score)

    if score >= 90:
        score_style = "bold green"
    elif score >= 70:
        score_style = "bold yellow"
    elif score >= 50:
        score_style = "bold orange1"
    else:
        score_style = "bold red"

    console.print()
    console.rule("[bold]GTD Audit Report[/bold]")
    console.print()

    # Summary line
    score_text = Text()
    score_text.append("Health Score: ")
    score_text.append(f"{score}%", style=score_style)
    score_text.append(f" ({label})")
    console.print(score_text)
    console.print()

    # Statistics
    console.print(f"[dim]GTD Projects:[/dim] {len(result.gtd_projects)}")
    if len(result.gtd_projects) > 0:
        console.print(
            f"[dim]With Next Actions:[/dim] {len(result.projects_with_next)} "
            f"[dim]([green]{len(result.projects_with_next)}[/green]/"
            f"{len(result.gtd_projects)})[/dim]"
        )
    else:
        console.print("[dim]With Next Actions:[/dim] n/a (no GTD projects)")
    console.print(f"[dim]Total Next Actions:[/dim] {len(result.next_action_tasks)}")
    console.print(
        f"[dim]Stale (>{stale_days} days):[/dim] {len(result.stale_tasks)}"
    )

    # Projects without next actions (only if there are any)
    if result.projects_without_next:
        console.print()
        console.rule("[red]Projects Without Next Actions[/red]")
        console.print()

        table = Table(show_header=True, header_style="bold")
        table.add_column("Project", style="cyan")
        table.add_column("Tasks", justify="right")
        table.add_column("Status", justify="center")

        for project in result.projects_without_next:
            if project.task_count > 0:
                status = f"[yellow]{project.task_count} task(s), none labeled[/yellow]"
            else:
                status = "[dim]Empty project[/dim]"

            table.add_row(
                project.name,
                str(project.task_count),
                status,
            )

        console.print(table)

    # Stale tasks (only if there are any)
    if result.stale_tasks:
        console.print()
        console.rule("[yellow]Stale Next Actions[/yellow]")
        console.print()

        table = Table(show_header=True, header_style="bold")
        table.add_column("Task", style="white", max_width=60)
        table.add_column("Project", style="cyan")
        table.add_column("Age", justify="right", style="yellow")

        for task in result.stale_tasks:
            # Truncate content if too long
            content = task.content
            if len(content) > 57:
                content = content[:57] + "..."

            table.add_row(
                content,
                task.project_name,
                f"{task.days_stale}d",
            )

        console.print(table)

    # Recommendations (only if score < 90)
    if score < 90:
        console.print()
        console.rule("[dim]Recommendations[/dim]")
        console.print()

        if result.projects_without_next:
            console.print(
                "[yellow]•[/yellow] Review projects without next actions and "
                "add the next physical action for each."
            )

        if result.stale_tasks:
            console.print(
                "[yellow]•[/yellow] Review stale next actions — are they still "
                "relevant? Consider completing, delegating, or deferring."
            )

    console.print()
