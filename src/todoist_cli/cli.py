"""Todoist CLI - Main command-line interface."""

import json
import re
from difflib import SequenceMatcher
from datetime import date, datetime, timedelta
from typing import Optional
import uuid
from zoneinfo import ZoneInfo
import typer
import requests
from rich.console import Console
from todoist_api_python.api import TodoistAPI
from todoist_core.models import TaskContext
from todoist_core.selectors import rank_next_action_candidates

from . import __version__
from .autodoist import AutodoistClient, AutodoistClientError
from .config import get_autodoist_url, require_token, get_config, save_config
from .formatting import (
    print_task,
    print_rest_task,
    print_tasks_table,
    print_projects,
    print_labels,
    print_comments,
    print_task_detail,
    canonical_task_url,
    console,
)
from .audit import run_audit, print_audit
from .todoist import TodoistClient, collect_pages

app = typer.Typer(
    name="td",
    help="Todoist CLI - Full-featured command-line interface with description and comment support.",
    no_args_is_help=True,
)
autodoist_app = typer.Typer(help="Autodoist debug API helpers.")
app.add_typer(autodoist_app, name="autodoist")


def get_api() -> TodoistAPI:
    """Get configured API client."""
    return TodoistAPI(require_token())


def get_client() -> TodoistClient:
    """Get Todoist client facade."""
    token = require_token()
    return TodoistClient(token=token, api=TodoistAPI(token))


def get_autodoist_client() -> AutodoistClient:
    """Get configured Autodoist API client."""
    url = get_autodoist_url()
    return AutodoistClient(base_url=url)


def get_project_map(api: Optional[TodoistAPI] = None, client: Optional[TodoistClient] = None) -> dict[str, str]:
    """Get mapping of project ID to name."""
    if client is not None:
        projects = client.list_projects()
    else:
        api = api or get_api()
        projects = collect_pages(api.get_projects())

    result = {}
    for p in projects:
        result[p.id] = p.name
    return result


def sync_api_command(token: str, command_type: str, args: dict) -> dict:
    """Execute a command via the Todoist Sync API v1."""
    command = {
        "type": command_type,
        "uuid": str(uuid.uuid4()),
        "args": args,
    }
    response = requests.post(
        "https://api.todoist.com/api/v1/sync",
        headers={"Authorization": f"Bearer {token}"},
        data={"commands": f"[{__import__('json').dumps(command)}]"},
    )
    response.raise_for_status()
    return response.json()


def _normalize_rich_text(text: str) -> str:
    """Normalize multi-line text while preserving readability structure."""
    raw = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw:
        return ""

    # If user gave one giant paragraph, break sentence boundaries for readability.
    if "\n" not in raw and len(raw) > 220:
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", raw)
        if len(sentences) > 1:
            raw = "\n\n".join(s.strip() for s in sentences if s.strip())

    lines: list[str] = []
    blank_pending = False
    for original in raw.split("\n"):
        line = original.strip()
        if not line:
            if lines:
                blank_pending = True
            continue

        # Normalize horizontal whitespace without collapsing paragraph boundaries.
        line = re.sub(r"[ \t]+", " ", line)
        if blank_pending and lines:
            lines.append("")
            blank_pending = False
        lines.append(line)

    return "\n".join(lines).strip()


def _normalize_description(description: str) -> str:
    """Normalize description text while preserving intentional paragraph breaks."""
    return _normalize_rich_text(description)


def _normalize_comment_text(text: str) -> str:
    """Normalize comment text for stable duplicate checks."""
    return re.sub(r"\s+", " ", _normalize_rich_text(text)).strip().lower()


def _ensure_comment_marker(text: str, marker: str) -> str:
    """Ensure comment starts with a marker prefix."""
    stripped = _normalize_rich_text(text)
    if _normalize_comment_text(stripped).startswith(_normalize_comment_text(marker)):
        return stripped
    return f"{marker} {stripped}"


def _is_similar_comment(existing: str, proposed: str, threshold: float = 0.94) -> bool:
    """Return True when comment bodies are effectively the same."""
    a = _normalize_comment_text(existing)
    b = _normalize_comment_text(proposed)
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 40 and len(b) >= 40 and (a in b or b in a):
        return True
    return SequenceMatcher(a=a, b=b).ratio() >= threshold


def _collect_task_comments(api: TodoistAPI, task_id: str) -> list:
    """Return task comments sorted most-recent first (best effort)."""
    task_comments = []
    for page in api.get_comments(task_id=task_id):
        task_comments.extend(page)
    return sorted(task_comments, key=lambda c: str(getattr(c, "posted_at", "")), reverse=True)


def _clear_task_comments(api: TodoistAPI, task_id: str, *, keep_plan: bool = False) -> tuple[int, int]:
    """Delete task comments and return (deleted_count, kept_count)."""
    task_comments = _collect_task_comments(api, task_id)
    if not task_comments:
        return 0, 0

    deleted = 0
    kept = 0
    for comment in task_comments:
        content = str(getattr(comment, "content", ""))
        if keep_plan and "[openclaw:plan]" in _normalize_comment_text(content):
            kept += 1
            continue
        api.delete_comment(str(comment.id))
        deleted += 1
    return deleted, kept


def _write_task_comment(
    api: TodoistAPI,
    task_id: str,
    text: str,
    *,
    mode: str = "append",
    dedupe: bool = True,
    recent: int = 5,
) -> tuple[str, str]:
    """Write comment based on mode and return action + comment id."""
    text = _normalize_rich_text(text)
    task_comments = _collect_task_comments(api, task_id)
    if dedupe:
        for existing in task_comments[:recent]:
            if _is_similar_comment(str(getattr(existing, "content", "")), text):
                return "skipped_duplicate", str(existing.id)

    if mode == "append":
        created = api.add_comment(task_id=task_id, content=text)
        return "added", str(created.id)

    if mode == "update-last":
        if not task_comments:
            created = api.add_comment(task_id=task_id, content=text)
            return "added", str(created.id)
        latest = task_comments[0]
        updated = api.update_comment(comment_id=latest.id, content=text)
        return "updated_latest", str(updated.id)

    # mode == overwrite-latest-plan
    plan_markers = ("[openclaw:plan]", "next action", "plan/next steps", "next step")
    target = next(
        (
            c
            for c in task_comments
            if any(marker in _normalize_comment_text(str(getattr(c, "content", ""))) for marker in plan_markers)
        ),
        None,
    )
    if target is None:
        created = api.add_comment(task_id=task_id, content=text)
        return "added", str(created.id)
    updated = api.update_comment(comment_id=target.id, content=text)
    return "overwrote_plan", str(updated.id)


def _infer_progress_type(text: str) -> str:
    """Infer whether content looks like a plan snapshot or progress update."""
    normalized = _normalize_comment_text(text)
    progress_cues = (
        "done",
        "completed",
        "finished",
        "sent",
        "posted",
        "created",
        "opened",
        "merged",
        "closed",
        "confirmed",
        "found",
        "verified",
        "updated",
        "replied",
        "pinged",
        "shared",
        "result",
        "outcome",
    )
    if "http://" in normalized or "https://" in normalized:
        return "progress"
    if any(cue in normalized for cue in progress_cues):
        return "progress"
    return "plan"


def _parse_iso_date(value: object) -> Optional[date]:
    """Parse a date-like value into a date object."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _parse_hhmm(value: str) -> Optional[tuple[int, int]]:
    """Parse HH:MM to (hour, minute)."""
    raw = value.strip()
    if not raw or ":" not in raw:
        return None
    hh, mm = raw.split(":", 1)
    try:
        hour = int(hh)
        minute = int(mm)
    except ValueError:
        return None
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return (hour, minute)


def _task_due_datetime_local(task: object, tz_name: str) -> Optional[datetime]:
    """Return task due datetime converted to local timezone."""
    due = getattr(task, "due", None)
    if due is None:
        return None
    due_dt = getattr(due, "datetime", None)
    if not due_dt:
        return None
    try:
        parsed = datetime.fromisoformat(str(due_dt).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo(tz_name))
        return parsed.astimezone(ZoneInfo(tz_name))
    except Exception:
        return None


def _task_due_date(task: object) -> Optional[date]:
    """Return due date from task due payload."""
    due = getattr(task, "due", None)
    if due is None:
        return None
    return _parse_iso_date(getattr(due, "date", None))


def _task_duration_minutes(task: object, default_minutes: int = 30) -> int:
    """Return duration in minutes (Todoist day unit approximated to 8h/day)."""
    duration = getattr(task, "duration", None)
    if duration is None:
        return max(5, default_minutes)
    amount = getattr(duration, "amount", None)
    unit = getattr(duration, "unit", None)
    try:
        amount_i = int(amount)
    except (TypeError, ValueError):
        return max(5, default_minutes)
    if amount_i <= 0:
        return max(5, default_minutes)
    if unit == "minute":
        return amount_i
    if unit == "day":
        return amount_i * 8 * 60
    return max(5, default_minutes)


def _to_task_context(task: object) -> TaskContext:
    """Convert Todoist SDK task object into shared TaskContext."""
    due = getattr(task, "due", None)
    due_date = _parse_iso_date(getattr(due, "date", None) if due is not None else None)
    due_dt_local = None
    if due is not None and getattr(due, "datetime", None):
        due_dt_local = _task_due_datetime_local(task, "America/Chicago")
    return TaskContext(
        id=str(getattr(task, "id", "")),
        content=str(getattr(task, "content", "")),
        labels=tuple(getattr(task, "labels", []) or []),
        project_id=str(getattr(task, "project_id", "")) or None,
        due_date=due_date,
        due_datetime_local=due_dt_local,
        duration_minutes=_task_duration_minutes(task, default_minutes=30),
        priority=int(getattr(task, "priority", 1) or 1),
        url=canonical_task_url(str(getattr(task, "id", ""))),
    )


def _compute_free_intervals(
    busy_intervals: list[tuple[datetime, datetime]],
    day_start: datetime,
    day_end: datetime,
) -> list[tuple[datetime, datetime]]:
    """Compute free intervals within [day_start, day_end)."""
    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted(busy_intervals, key=lambda x: x[0]):
        if end <= day_start or start >= day_end:
            continue
        start = max(start, day_start)
        end = min(end, day_end)
        if end <= start:
            continue
        if not merged:
            merged.append((start, end))
            continue
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))

    free: list[tuple[datetime, datetime]] = []
    cursor = day_start
    for start, end in merged:
        if start > cursor:
            free.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < day_end:
        free.append((cursor, day_end))
    return free


def _format_slot(dt: datetime) -> str:
    """Format slot timestamp for CLI output."""
    return dt.strftime("%H:%M")


# --- List Command ---
@app.command()
def list(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Filter by project name"),
    label: Optional[str] = typer.Option(None, "--label", "-l", help="Filter by label name"),
    priority: bool = typer.Option(False, "--priority", "-P", help="Sort by priority"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    show_description: bool = typer.Option(False, "--description", "-d", help="Show task descriptions"),
):
    """List tasks with optional filtering."""
    client = get_client()
    project_map = get_project_map(client=client)

    # Build kwargs for get_tasks
    kwargs = {}
    if project:
        # Find project ID by name
        project_id = None
        for pid, pname in project_map.items():
            if pname.lower() == project.lower():
                project_id = pid
                break
        if project_id:
            kwargs["project_id"] = project_id
        else:
            console.print(f"[red]Project '{project}' not found[/red]")
            raise typer.Exit(1)

    if label:
        kwargs["label"] = label

    tasks = client.list_tasks(**kwargs)

    if priority:
        tasks = sorted(tasks, key=lambda t: -t.priority)

    if not tasks:
        console.print("[dim]No tasks found[/dim]")
        return

    if table:
        print_tasks_table(tasks, project_map)
    else:
        for task in tasks:
            project_name = project_map.get(task.project_id, "")
            print_task(task, show_description=show_description, project_name=project_name)


# --- Query Command ---
@app.command()
def query(
    filter_query: str = typer.Argument(..., help="Native Todoist filter query (e.g. '(today | overdue) & #Work')"),
    limit: Optional[int] = typer.Option(None, "--limit", "-n", help="Max number of tasks to show (client-side)"),
    json_output: bool = typer.Option(False, "--json", help="Print raw REST JSON to stdout"),
):
    """Query tasks using native Todoist filter syntax (REST v2 tasks?filter=...)."""
    import json as _json

    client = get_client()
    tasks = client.list_tasks_by_filter(filter_query)

    if limit is not None and limit >= 0:
        tasks = tasks[:limit]

    if json_output:
        typer.echo(_json.dumps(tasks, indent=2, sort_keys=True))
        return

    if not tasks:
        console.print("[dim]No tasks found[/dim]")
        return

    for task in tasks:
        print_rest_task(task)


# --- Add Command ---
@app.command()
def add(
    content: str = typer.Argument(..., help="Task content"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Task description"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name"),
    parent_id: Optional[str] = typer.Option(None, "--parent-id", "--parent", help="Parent task ID (create as subtask)"),
    priority: int = typer.Option(1, "--priority", "-P", help="Priority (1=p4 lowest, 4=p1 highest)"),
    due: Optional[str] = typer.Option(None, "--due", "--do", "-D", help="Do date - when to work on it (e.g., 'today', 'tomorrow', 'wednesday')"),
    deadline: Optional[str] = typer.Option(None, "--deadline", help="Hard deadline date (YYYY-MM-DD format)"),
    duration: Optional[int] = typer.Option(None, "--duration", help="Task duration amount"),
    duration_unit: Optional[str] = typer.Option(None, "--duration-unit", help="Duration unit: 'minute' or 'day'"),
    labels: Optional[str] = typer.Option(None, "--labels", "-l", help="Labels (comma-separated)"),
):
    """Add a new task."""
    api = get_api()

    kwargs = {"content": content, "priority": priority}

    if description is not None:
        normalized_description = _normalize_description(description)
        if normalized_description:
            kwargs["description"] = normalized_description

    if project:
        project_map = get_project_map(api)
        project_id = None
        for pid, pname in project_map.items():
            if pname.lower() == project.lower():
                project_id = pid
                break
        if project_id:
            kwargs["project_id"] = project_id
        else:
            console.print(f"[red]Project '{project}' not found[/red]")
            raise typer.Exit(1)

    if parent_id:
        kwargs["parent_id"] = parent_id

    if due:
        kwargs["due_string"] = due

    if deadline:
        try:
            kwargs["deadline_date"] = datetime.strptime(deadline, "%Y-%m-%d").date()
        except ValueError:
            console.print("[red]Invalid deadline format. Use YYYY-MM-DD (e.g., 2025-02-15)[/red]")
            raise typer.Exit(1)

    if duration is not None or duration_unit is not None:
        if duration is None or duration_unit is None:
            console.print("[red]Both --duration and --duration-unit must be specified together[/red]")
            raise typer.Exit(1)
        if duration_unit not in ("minute", "day"):
            console.print("[red]Duration unit must be 'minute' or 'day'[/red]")
            raise typer.Exit(1)
        kwargs["duration"] = duration
        kwargs["duration_unit"] = duration_unit

    if labels:
        kwargs["labels"] = [l.strip() for l in labels.split(",")]

    task = api.add_task(**kwargs)
    console.print(f"[green]Created task:[/green] {task.id} - {task.content}")
    console.print(f"[bold]Task link:[/bold] {task.content} - {canonical_task_url(task.id)}")
    if task.description:
        console.print(f"[dim]Description: {task.description}[/dim]")
    if task.deadline:
        console.print(f"[dim]Deadline: {task.deadline.date}[/dim]")
    if task.duration:
        console.print(f"[dim]Duration: {task.duration.amount} {task.duration.unit}(s)[/dim]")


@app.command(name="add-focus")
def add_focus(
    content: str = typer.Argument(..., help="Task content"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Task description"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name"),
    parent_id: Optional[str] = typer.Option(None, "--parent-id", "--parent", help="Parent task ID (create as subtask)"),
    priority: int = typer.Option(1, "--priority", "-P", help="Priority (1=p4 lowest, 4=p1 highest)"),
    due: Optional[str] = typer.Option(None, "--due", "--do", "-D", help="Do date - when to work on it (e.g., 'today', 'tomorrow', 'wednesday')"),
    deadline: Optional[str] = typer.Option(None, "--deadline", help="Hard deadline date (YYYY-MM-DD format)"),
    duration: Optional[int] = typer.Option(None, "--duration", help="Task duration amount"),
    duration_unit: Optional[str] = typer.Option(None, "--duration-unit", help="Duration unit: 'minute' or 'day'"),
    labels: Optional[str] = typer.Option(None, "--labels", "-l", help="Labels (comma-separated)"),
):
    """Add a new task and immediately set it as singleton focus."""
    api = get_api()

    kwargs = {"content": content, "priority": priority}

    if description is not None:
        normalized_description = _normalize_description(description)
        if normalized_description:
            kwargs["description"] = normalized_description

    if project:
        project_map = get_project_map(api)
        project_id = None
        for pid, pname in project_map.items():
            if pname.lower() == project.lower():
                project_id = pid
                break
        if project_id:
            kwargs["project_id"] = project_id
        else:
            console.print(f"[red]Project '{project}' not found[/red]")
            raise typer.Exit(1)

    if parent_id:
        kwargs["parent_id"] = parent_id

    if due:
        kwargs["due_string"] = due

    if deadline:
        try:
            kwargs["deadline_date"] = datetime.strptime(deadline, "%Y-%m-%d").date()
        except ValueError:
            console.print("[red]Invalid deadline format. Use YYYY-MM-DD (e.g., 2025-02-15)[/red]")
            raise typer.Exit(1)

    if duration is not None or duration_unit is not None:
        if duration is None or duration_unit is None:
            console.print("[red]Both --duration and --duration-unit must be specified together[/red]")
            raise typer.Exit(1)
        if duration_unit not in ("minute", "day"):
            console.print("[red]Duration unit must be 'minute' or 'day'[/red]")
            raise typer.Exit(1)
        kwargs["duration"] = duration
        kwargs["duration_unit"] = duration_unit

    if labels:
        kwargs["labels"] = [label_name.strip() for label_name in labels.split(",")]

    task = api.add_task(**kwargs)
    console.print(f"[green]Created task:[/green] {task.id} - {task.content}")
    console.print(f"[bold]Task link:[/bold] {task.content} - {canonical_task_url(task.id)}")

    client = get_autodoist_client()
    try:
        focus_result = client.task_label_action(task_id=task.id, action="make_winner")
    except AutodoistClientError as exc:
        console.print(f"[red]Failed to set focus for new task:[/red] {exc}")
        raise typer.Exit(1)

    console.print(f"[green]Set focus:[/green] {task.id}")
    if focus_result.get("message"):
        console.print(f"[dim]{focus_result['message']}[/dim]")
    console.print(f"[bold]Task link:[/bold] {task.content} - {canonical_task_url(task.id)}")


# --- Quick Add Command ---
@app.command()
def quick(
    text: str = typer.Argument(..., help="Quick add text (e.g., 'Buy milk tomorrow #Shopping p2')"),
):
    """Quick add a task using natural language."""
    api = get_api()
    # The API's add_task with due_string handles natural language parsing
    # But for proper quick-add with project/label parsing, we need to parse ourselves
    # For now, just pass content and let due_string handle dates

    task = api.add_task(content=text)
    console.print(f"[green]Created task:[/green] {task.id} - {task.content}")
    console.print(f"[bold]Task link:[/bold] {task.content} - {canonical_task_url(task.id)}")


# --- Show Command ---
@app.command()
def show(
    task_id: str = typer.Argument(..., help="Task ID"),
    comments: bool = typer.Option(True, "--comments/--no-comments", "-c/-C", help="Show comments"),
):
    """Show detailed task information."""
    api = get_api()

    try:
        task = api.get_task(task_id)
    except Exception as e:
        console.print(f"[red]Task not found: {task_id}[/red]")
        raise typer.Exit(1)

    project_map = get_project_map(api)
    project_name = project_map.get(task.project_id, "")

    task_comments = None
    if comments:
        try:
            task_comments = []
            for page in api.get_comments(task_id=task_id):
                task_comments.extend(page)
        except Exception:
            pass

    print_task_detail(task, comments=task_comments, project_name=project_name)


# --- Close Command ---
@app.command()
def close(
    task_id: str = typer.Argument(..., help="Task ID to complete"),
    clear_comments: Optional[bool] = typer.Option(
        None,
        "--clear-comments/--no-clear-comments",
        help="Delete task comments before completing (default: keep comments)",
    ),
    keep_plan: bool = typer.Option(
        False,
        "--keep-plan",
        help="When clearing comments, keep [openclaw:plan] entries",
    ),
):
    """Complete/close a task.

    Default behavior:
    - Keep comments unless explicitly requested with --clear-comments
    """
    api = get_api()
    if keep_plan and clear_comments is False:
        console.print("[red]--keep-plan cannot be used with --no-clear-comments[/red]")
        raise typer.Exit(1)

    try:
        should_clear = (clear_comments is True) or keep_plan

        if should_clear:
            deleted, kept = _clear_task_comments(api, task_id, keep_plan=keep_plan)
            if keep_plan:
                console.print(f"[green]Cleared comments:[/green] deleted={deleted} kept_plan={kept}")
            else:
                console.print(f"[green]Cleared comments:[/green] deleted={deleted}")
        api.complete_task(task_id)
        console.print(f"[green]Completed task:[/green] {task_id}")
    except Exception as e:
        console.print(f"[red]Failed to close task: {e}[/red]")
        raise typer.Exit(1)


# --- Reopen Command ---
@app.command()
def reopen(
    task_id: str = typer.Argument(..., help="Task ID to reopen"),
):
    """Reopen a completed task."""
    api = get_api()

    try:
        api.uncomplete_task(task_id)
        console.print(f"[green]Reopened task:[/green] {task_id}")
    except Exception as e:
        console.print(f"[red]Failed to reopen task: {e}[/red]")
        raise typer.Exit(1)


# --- Postpone Command ---
@app.command()
def postpone(
    task_id: str = typer.Argument(..., help="Task ID to postpone"),
    time: str = typer.Argument(..., help="Time to postpone (e.g., '2 hours', '1 day', 'tomorrow', '3 days')"),
):
    """Postpone a task's due date by a relative amount.

    Examples:
        td postpone <id> "2 hours"
        td postpone <id> "1 day"
        td postpone <id> "tomorrow"
        td postpone <id> "next monday"
    """
    api = get_api()

    # Prepend "in" if the time doesn't start with common keywords
    time_lower = time.lower().strip()
    if not any(time_lower.startswith(kw) for kw in ("in ", "tomorrow", "today", "next ", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")):
        due_string = f"in {time}"
    else:
        due_string = time

    try:
        task = api.update_task(task_id, due_string=due_string)
        new_due = task.due.string if task.due else "no due date"
        console.print(f"[green]Postponed task:[/green] {task_id} → {new_due}")
    except Exception as e:
        console.print(f"[red]Failed to postpone task: {e}[/red]")
        raise typer.Exit(1)


# --- Snooze Command ---
@app.command()
def snooze(
    target: str = typer.Argument(..., help="Target date: 'tomorrow', 'weekend', 'monday', 'next week', or natural language"),
    overdue_only: bool = typer.Option(False, "--overdue-only", "-o", help="Only snooze overdue tasks (not today's)"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Preview what would be snoozed without making changes"),
):
    """Bulk snooze overdue and today's tasks to a target date.

    Presets:
        tomorrow   - Move to tomorrow
        weekend    - Move to Saturday
        monday     - Move to next Monday
        next week  - Move to next Monday

    Examples:
        td snooze tomorrow           # All overdue + today → tomorrow
        td snooze weekend            # → Saturday
        td snooze monday             # → Next Monday
        td snooze tomorrow --overdue-only  # Only overdue tasks
        td snooze tomorrow --dry-run       # Preview without changing
    """
    api = get_api()

    # Map presets to natural language strings
    target_lower = target.lower().strip()
    preset_map = {
        "weekend": "saturday",
        "next week": "next monday",
    }
    due_string = preset_map.get(target_lower, target_lower)

    # Build filter - Todoist REST API doesn't support filter param directly
    # We need to fetch all tasks and filter locally
    tasks = []
    for page in api.get_tasks():
        tasks.extend(page)

    # Filter for overdue and today tasks
    today_str = date.today().isoformat()
    tasks_to_snooze = []

    for task in tasks:
        if not task.due:
            continue

        # Get the due date
        due_date = None
        if hasattr(task.due, "date"):
            due_date = task.due.date

        if not due_date:
            continue

        # Check if overdue or today
        is_overdue = due_date < today_str
        is_today = due_date == today_str

        if overdue_only:
            if is_overdue:
                tasks_to_snooze.append((task, "overdue"))
        else:
            if is_overdue:
                tasks_to_snooze.append((task, "overdue"))
            elif is_today:
                tasks_to_snooze.append((task, "today"))

    if not tasks_to_snooze:
        scope = "overdue" if overdue_only else "overdue or due today"
        console.print(f"[dim]No {scope} tasks to snooze[/dim]")
        return

    # Show preview
    console.print(f"\n[bold]Tasks to snooze → {due_string}:[/bold]")
    for task, status in tasks_to_snooze:
        status_style = "red" if status == "overdue" else "yellow"
        console.print(f"  [{status_style}]{status}[/{status_style}] {task.content} (due: {task.due.date})")

    console.print(f"\n[bold]{len(tasks_to_snooze)} task(s) will be snoozed to {due_string}[/bold]")

    if dry_run:
        console.print("[yellow]Dry run - no changes made[/yellow]")
        return

    # Actually snooze the tasks
    success_count = 0
    fail_count = 0
    for task, _ in tasks_to_snooze:
        try:
            api.update_task(task.id, due_string=due_string)
            success_count += 1
        except Exception as e:
            console.print(f"[red]Failed to snooze {task.id}: {e}[/red]")
            fail_count += 1

    if success_count > 0:
        console.print(f"[green]Snoozed {success_count} task(s) to {due_string}[/green]")
    if fail_count > 0:
        console.print(f"[red]Failed to snooze {fail_count} task(s)[/red]")


# --- Inbox Command ---
@app.command()
def inbox(
    count_only: bool = typer.Option(False, "--count", "-c", help="Only show count of inbox tasks"),
    show_description: bool = typer.Option(False, "--description", "-d", help="Show task descriptions"),
):
    """List tasks in the Inbox (no project assigned).

    In GTD, the inbox contains unprocessed items that need to be
    organized into projects, given due dates, or acted upon.

    Examples:
        td inbox              # List all inbox tasks
        td inbox --count      # Just show the count
        td inbox -d           # Show with descriptions
    """
    api = get_api()

    # Find the Inbox project ID
    inbox_project_id = None
    for page in api.get_projects():
        for p in page:
            if p.inbox_project:
                inbox_project_id = p.id
                break
        if inbox_project_id:
            break

    if not inbox_project_id:
        console.print("[red]Could not find Inbox project[/red]")
        raise typer.Exit(1)

    # Get tasks in inbox
    tasks = []
    for page in api.get_tasks(project_id=inbox_project_id):
        tasks.extend(page)

    if count_only:
        console.print(f"[bold]{len(tasks)}[/bold] task(s) in inbox")
        return

    if not tasks:
        console.print("[green]Inbox is empty![/green]")
        return

    console.print(f"\n[bold]Inbox ({len(tasks)} tasks):[/bold]\n")
    for task in tasks:
        print_task(task, show_description=show_description)


# --- Move Command ---
@app.command()
def move(
    task_id: str = typer.Argument(..., help="Task ID to move"),
    project_name: str = typer.Argument(..., help="Target project name"),
):
    """Move a task to a different project.

    Useful for GTD inbox processing - quickly assign tasks to projects.

    Examples:
        td move 12345 "Work"
        td move 12345 "Someday/Maybe"
        td move 12345 "Personal"
    """
    api = get_api()

    # Find the target project ID
    project_map = get_project_map(api)
    target_project_id = None
    for pid, pname in project_map.items():
        if pname.lower() == project_name.lower():
            target_project_id = pid
            break

    if not target_project_id:
        console.print(f"[red]Project '{project_name}' not found[/red]")
        console.print("\n[dim]Available projects:[/dim]")
        for pname in sorted(project_map.values()):
            console.print(f"  {pname}")
        raise typer.Exit(1)

    try:
        task_content = None
        try:
            existing = api.get_task(task_id)
            task_content = getattr(existing, "content", None)
        except Exception:
            pass

        moved = api.move_task(task_id=task_id, project_id=target_project_id)
        if task_content is None:
            if isinstance(moved, dict):
                task_content = moved.get("content")
            else:
                task_content = getattr(moved, "content", None)
        if not task_content:
            task_content = task_id

        console.print(f"[green]Moved task to {project_name}:[/green] {task_content}")
    except Exception as e:
        console.print(f"[red]Failed to move task: {e}[/red]")
        raise typer.Exit(1)


# --- Today Command ---
@app.command()
def today(
    include_overdue: bool = typer.Option(True, "--overdue/--no-overdue", "-o/-O", help="Include overdue tasks"),
    show_description: bool = typer.Option(False, "--description", "-d", help="Show task descriptions"),
):
    """Show tasks due today (and optionally overdue).

    Perfect for daily review - see what needs attention today.

    Examples:
        td today              # Today + overdue tasks
        td today --no-overdue # Only today's tasks
        td today -d           # With descriptions
    """
    api = get_api()
    project_map = get_project_map(api)

    # Fetch all tasks
    tasks = []
    for page in api.get_tasks():
        tasks.extend(page)

    today_str = date.today().isoformat()
    tasks_to_show = []

    for task in tasks:
        if not task.due:
            continue

        due_date = task.due.date if hasattr(task.due, "date") else None
        if not due_date:
            continue

        is_overdue = due_date < today_str
        is_today = due_date == today_str

        if is_today:
            tasks_to_show.append((task, "today"))
        elif is_overdue and include_overdue:
            tasks_to_show.append((task, "overdue"))

    # Sort: overdue first (by date), then today
    tasks_to_show.sort(key=lambda x: (x[1] != "overdue", x[0].due.date))

    if not tasks_to_show:
        console.print("[green]Nothing due today![/green]")
        return

    overdue_count = sum(1 for _, status in tasks_to_show if status == "overdue")
    today_count = sum(1 for _, status in tasks_to_show if status == "today")

    header = f"[bold]Today ({today_count} tasks)"
    if overdue_count > 0:
        header += f" + {overdue_count} overdue"
    header += ":[/bold]\n"
    console.print(f"\n{header}")

    for task, status in tasks_to_show:
        project_name = project_map.get(task.project_id, "")
        if status == "overdue":
            console.print("[red]overdue[/red] ", end="")
        print_task(task, show_description=show_description, project_name=project_name)


# --- Upcoming Command ---
@app.command()
def upcoming(
    days: int = typer.Argument(7, help="Number of days to look ahead"),
    show_description: bool = typer.Option(False, "--description", "-d", help="Show task descriptions"),
):
    """Show tasks due in the next N days.

    Great for weekly planning - see what's coming up.

    Examples:
        td upcoming           # Next 7 days (default)
        td upcoming 3         # Next 3 days
        td upcoming 14        # Next 2 weeks
        td upcoming 7 -d      # With descriptions
    """
    api = get_api()
    project_map = get_project_map(api)

    # Fetch all tasks
    tasks = []
    for page in api.get_tasks():
        tasks.extend(page)

    today_date = date.today()
    today_str = today_date.isoformat()
    end_date = today_date + timedelta(days=days)
    end_str = end_date.isoformat()

    tasks_to_show = []

    for task in tasks:
        if not task.due:
            continue

        due_date = task.due.date if hasattr(task.due, "date") else None
        if not due_date:
            continue

        # Include tasks from today through end_date
        if today_str <= due_date <= end_str:
            tasks_to_show.append(task)

    # Sort by due date
    tasks_to_show.sort(key=lambda t: t.due.date)

    if not tasks_to_show:
        console.print(f"[green]Nothing due in the next {days} days![/green]")
        return

    console.print(f"\n[bold]Upcoming ({len(tasks_to_show)} tasks in next {days} days):[/bold]\n")

    # Group by date for readability
    current_date = None
    for task in tasks_to_show:
        task_date = task.due.date
        if task_date != current_date:
            current_date = task_date
            # Format date header
            try:
                dt = datetime.strptime(task_date, "%Y-%m-%d")
                day_name = dt.strftime("%A")
                if task_date == today_str:
                    day_label = "Today"
                elif task_date == (today_date + timedelta(days=1)).isoformat():
                    day_label = "Tomorrow"
                else:
                    day_label = day_name
                console.print(f"\n[bold cyan]{day_label} ({task_date}):[/bold cyan]")
            except ValueError:
                console.print(f"\n[bold cyan]{task_date}:[/bold cyan]")

        project_name = project_map.get(task.project_id, "")
        console.print("  ", end="")
        print_task(task, show_description=show_description, project_name=project_name)


# --- Recent Command ---
@app.command()
def recent(
    limit: int = typer.Option(10, "--limit", "-n", help="Number of tasks to show"),
    show_description: bool = typer.Option(False, "--description", "-d", help="Show task descriptions"),
):
    """Show recently created tasks.

    Lists tasks sorted by creation date (newest first).
    Useful for seeing what you've added recently.

    Examples:
        td recent              # Show 10 most recent tasks
        td recent -n 20        # Show 20 most recent
        td recent -d           # Show with descriptions
    """
    api = get_api()
    project_map = get_project_map(api)

    # Fetch all tasks
    tasks = []
    for page in api.get_tasks():
        tasks.extend(page)

    # Sort by created_at (newest first)
    tasks_sorted = sorted(tasks, key=lambda t: t.created_at, reverse=True)

    # Limit results
    tasks_to_show = tasks_sorted[:limit]

    if not tasks_to_show:
        console.print("[dim]No tasks found[/dim]")
        return

    console.print(f"\n[bold]Recently created tasks ({len(tasks_to_show)} of {len(tasks)}):[/bold]\n")
    for task in tasks_to_show:
        project_name = project_map.get(task.project_id, "")
        # Show created date
        created = task.created_at[:10] if task.created_at else ""
        console.print(f"[dim]{created}[/dim] ", end="")
        print_task(task, show_description=show_description, project_name=project_name)


# --- Suggest Time Command ---
@app.command(name="suggest-time")
def suggest_time(
    task_id: Optional[str] = typer.Argument(None, help="Task ID to suggest slot for (omit for auto day-plan mode)"),
    day: str = typer.Option("today", "--day", help="Target day: today | tomorrow | YYYY-MM-DD"),
    timezone: str = typer.Option("America/Chicago", "--timezone", help="IANA timezone (e.g., America/Chicago)"),
    work_start: str = typer.Option("09:00", "--work-start", help="Start of planning window (HH:MM)"),
    work_end: str = typer.Option("18:00", "--work-end", help="End of planning window (HH:MM)"),
    default_duration: int = typer.Option(30, "--default-duration", min=5, help="Default duration minutes when task has no duration"),
    busy_default_duration: int = typer.Option(30, "--busy-default-duration", min=5, help="Default block minutes for timed tasks with no duration"),
    top: int = typer.Option(3, "--top", "-n", min=1, max=10, help="Max suggestions"),
):
    """Suggest schedule slots using current due-times + duration constraints.

    Modes:
    - With task_id: suggest best slot(s) for that task.
    - Without task_id: auto-assign slots for overdue/today unscheduled tasks.
    """
    api = get_api()

    try:
        tz = ZoneInfo(timezone)
    except Exception:
        console.print(f"[red]Invalid timezone:[/red] {timezone}")
        raise typer.Exit(1)

    start_parts = _parse_hhmm(work_start)
    end_parts = _parse_hhmm(work_end)
    if start_parts is None or end_parts is None:
        console.print("[red]Invalid work window. Use HH:MM for --work-start/--work-end[/red]")
        raise typer.Exit(1)
    if start_parts >= end_parts:
        console.print("[red]--work-start must be earlier than --work-end[/red]")
        raise typer.Exit(1)

    now_local = datetime.now(tz)
    day_lower = day.strip().lower()
    if day_lower == "today":
        target_day = now_local.date()
    elif day_lower == "tomorrow":
        target_day = now_local.date() + timedelta(days=1)
    else:
        parsed_day = _parse_iso_date(day)
        if parsed_day is None:
            console.print("[red]Invalid --day value. Use today, tomorrow, or YYYY-MM-DD[/red]")
            raise typer.Exit(1)
        target_day = parsed_day

    day_start = datetime(target_day.year, target_day.month, target_day.day, start_parts[0], start_parts[1], tzinfo=tz)
    day_end = datetime(target_day.year, target_day.month, target_day.day, end_parts[0], end_parts[1], tzinfo=tz)

    tasks = []
    for page in api.get_tasks():
        tasks.extend(page)

    busy_intervals: list[tuple[datetime, datetime]] = []
    for task in tasks:
        due_dt = _task_due_datetime_local(task, timezone)
        if due_dt is None or due_dt.date() != target_day:
            continue
        duration_minutes = _task_duration_minutes(task, default_minutes=busy_default_duration)
        busy_intervals.append((due_dt, due_dt + timedelta(minutes=duration_minutes)))

    free_intervals = _compute_free_intervals(busy_intervals, day_start, day_end)

    if task_id:
        try:
            target_task = api.get_task(task_id)
        except Exception:
            console.print(f"[red]Task not found:[/red] {task_id}")
            raise typer.Exit(1)

        needed_minutes = _task_duration_minutes(target_task, default_minutes=default_duration)
        suggestions: list[datetime] = []
        for start, end in free_intervals:
            if int((end - start).total_seconds() // 60) >= needed_minutes:
                suggestions.append(start)
                if len(suggestions) >= top:
                    break

        due_dt_existing = _task_due_datetime_local(target_task, timezone)
        due_date_existing = _task_due_date(target_task)
        due_status = "none"
        if due_dt_existing is not None:
            due_status = due_dt_existing.strftime("%Y-%m-%d %H:%M")
        elif due_date_existing is not None:
            due_status = due_date_existing.isoformat()

        console.print(f"[bold]Task:[/bold] {target_task.content} ({task_id})")
        console.print(f"[bold]Target day:[/bold] {target_day.isoformat()} [{timezone}]")
        console.print(f"[bold]Current due:[/bold] {due_status}")
        console.print(f"[bold]Duration used:[/bold] {needed_minutes}m")
        if not suggestions:
            console.print("[yellow]No slot available in the selected window.[/yellow]")
            raise typer.Exit(0)

        console.print("\n[bold green]Suggested start times:[/bold green]")
        for i, slot in enumerate(suggestions, start=1):
            console.print(f"{i}. {slot.strftime('%Y-%m-%d')} {_format_slot(slot)}")
        return

    # Auto day-plan mode: prioritize overdue first, then today/no-time tasks.
    unscheduled = []
    for task in tasks:
        due_dt = _task_due_datetime_local(task, timezone)
        if due_dt is not None:
            continue
        due_date = _task_due_date(task)
        if due_date is None:
            continue
        if due_date > target_day:
            continue
        overdue_days = max(0, (now_local.date() - due_date).days)
        labels = set(getattr(task, "labels", []) or [])
        unscheduled.append(
            (
                task,
                overdue_days,
                getattr(task, "priority", 1),
                "focus" in labels,
                "next_action" in labels,
                due_date,
            )
        )

    if not unscheduled:
        console.print("[dim]No overdue/today unscheduled tasks to auto-slot.[/dim]")
        return

    unscheduled.sort(
        key=lambda row: (
            -int(row[3]),  # focus first
            -row[1],       # more overdue first
            row[5],        # earlier due date first
            -row[2],       # higher priority first
            -int(row[4]),  # next_action bias
            str(row[0].content).lower(),
        )
    )

    remaining = free_intervals[:]
    plan_rows = []
    for task, overdue_days, priority, is_focus, is_next, due_date in unscheduled:
        needed = _task_duration_minutes(task, default_minutes=default_duration)
        assigned = None
        for idx, (slot_start, slot_end) in enumerate(remaining):
            minutes_available = int((slot_end - slot_start).total_seconds() // 60)
            if minutes_available < needed:
                continue
            assigned = slot_start
            new_start = slot_start + timedelta(minutes=needed)
            if new_start >= slot_end:
                remaining.pop(idx)
            else:
                remaining[idx] = (new_start, slot_end)
            break
        if assigned is None:
            continue
        plan_rows.append((task, assigned, needed, overdue_days, is_focus, is_next, due_date))
        if len(plan_rows) >= top:
            break

    if not plan_rows:
        console.print("[yellow]No available slot for overdue/today unscheduled tasks.[/yellow]")
        return

    console.print(f"[bold]Auto day-plan suggestions:[/bold] {target_day.isoformat()} [{timezone}]")
    for i, (task, start, minutes, overdue_days, is_focus, is_next, due_date) in enumerate(plan_rows, start=1):
        flags = []
        if is_focus:
            flags.append("focus")
        if is_next:
            flags.append("next_action")
        if overdue_days > 0:
            flags.append(f"overdue:{overdue_days}d")
        flag_text = f" [{' '.join(flags)}]" if flags else ""
        console.print(
            f"{i}. {_format_slot(start)} ({minutes}m) {task.content}{flag_text} (due {due_date.isoformat()})"
        )


# --- Delete Command ---
@app.command()
def delete(
    task_id: str = typer.Argument(..., help="Task ID to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Delete a task."""
    api = get_api()

    if not force:
        try:
            task = api.get_task(task_id)
            confirm = typer.confirm(f"Delete task '{task.content}'?")
            if not confirm:
                raise typer.Abort()
        except Exception:
            pass

    try:
        api.delete_task(task_id)
        console.print(f"[green]Deleted task:[/green] {task_id}")
    except Exception as e:
        console.print(f"[red]Failed to delete task: {e}[/red]")
        raise typer.Exit(1)


# --- Modify Command ---
@app.command()
def modify(
    task_id: str = typer.Argument(..., help="Task ID to modify"),
    content: Optional[str] = typer.Option(None, "--content", "-c", help="New content"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="New description"),
    parent_id: Optional[str] = typer.Option(None, "--parent-id", "--parent", help="New parent task ID (reparent task as subtask)"),
    priority: Optional[int] = typer.Option(None, "--priority", "-P", help="New priority (1-4)"),
    due: Optional[str] = typer.Option(None, "--due", "--do", "-D", help="New do date - when to work on it"),
    no_due: bool = typer.Option(False, "--no-due", "-N", help="Clear the due date"),
    deadline: Optional[str] = typer.Option(None, "--deadline", help="New deadline date (YYYY-MM-DD format)"),
    duration: Optional[int] = typer.Option(None, "--duration", help="Task duration amount"),
    duration_unit: Optional[str] = typer.Option(None, "--duration-unit", help="Duration unit: 'minute' or 'day'"),
    labels: Optional[str] = typer.Option(None, "--labels", "-l", help="New labels (comma-separated)"),
):
    """Modify an existing task."""
    api = get_api()

    # Validate conflicting options
    if due and no_due:
        console.print("[red]Cannot specify both --due and --no-due[/red]")
        raise typer.Exit(1)

    kwargs = {}
    if content:
        kwargs["content"] = content
    if description is not None:
        kwargs["description"] = _normalize_description(description)
    if parent_id is not None:
        kwargs["parent_id"] = parent_id
    if priority:
        kwargs["priority"] = priority
    if no_due:
        kwargs["due_string"] = "no date"
    elif due:
        kwargs["due_string"] = due
    if deadline:
        try:
            kwargs["deadline_date"] = datetime.strptime(deadline, "%Y-%m-%d").date()
        except ValueError:
            console.print("[red]Invalid deadline format. Use YYYY-MM-DD (e.g., 2025-02-15)[/red]")
            raise typer.Exit(1)
    if duration is not None or duration_unit is not None:
        if duration is None or duration_unit is None:
            console.print("[red]Both --duration and --duration-unit must be specified together[/red]")
            raise typer.Exit(1)
        if duration_unit not in ("minute", "day"):
            console.print("[red]Duration unit must be 'minute' or 'day'[/red]")
            raise typer.Exit(1)
        kwargs["duration"] = duration
        kwargs["duration_unit"] = duration_unit
    if labels is not None:
        kwargs["labels"] = [l.strip() for l in labels.split(",")] if labels else []

    if not kwargs:
        console.print("[yellow]No modifications specified[/yellow]")
        raise typer.Exit(1)

    try:
        task = api.update_task(task_id, **kwargs)
        console.print(f"[green]Updated task:[/green] {task_id}")
    except Exception as e:
        console.print(f"[red]Failed to update task: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def reparent(
    task_id: str = typer.Argument(..., help="Task ID to reparent"),
    parent_id: str = typer.Argument(..., help="New parent task ID"),
):
    """Move an existing task under another task as a subtask."""
    api = get_api()
    try:
        api.update_task(task_id, parent_id=parent_id)
        console.print(f"[green]Reparented task:[/green] {task_id} -> parent {parent_id}")
    except Exception as e:
        console.print(f"[red]Failed to reparent task: {e}[/red]")
        raise typer.Exit(1)


# --- Comment Commands ---
@app.command()
def comment(
    task_id: str = typer.Argument(..., help="Task ID"),
    text: str = typer.Argument(..., help="Comment text"),
    mode: str = typer.Option(
        "append",
        "--mode",
        help="Write mode: append | update-last | overwrite-latest-plan",
    ),
    dedupe: bool = typer.Option(True, "--dedupe/--no-dedupe", help="Skip near-duplicate comment writes"),
    recent: int = typer.Option(5, "--recent", min=1, max=20, help="Number of recent comments to check for dedupe"),
    force: bool = typer.Option(False, "--force", help="Bypass dedupe checks"),
):
    """Add or update a comment on a task with optional dedupe safeguards."""
    api = get_api()
    mode = mode.strip().lower()
    valid_modes = {"append", "update-last", "overwrite-latest-plan"}
    if mode not in valid_modes:
        console.print(f"[red]Invalid --mode '{mode}'. Use one of: {', '.join(sorted(valid_modes))}[/red]")
        raise typer.Exit(1)

    if force:
        dedupe = False

    try:
        action, comment_id = _write_task_comment(api, task_id, text, mode=mode, dedupe=dedupe, recent=recent)
        if action == "skipped_duplicate":
            console.print(f"[yellow]Skipped duplicate comment:[/yellow] {comment_id}")
        elif action == "added":
            console.print(f"[green]Added comment:[/green] {comment_id}")
        elif action == "updated_latest":
            console.print(f"[green]Updated latest comment:[/green] {comment_id}")
        elif action == "overwrote_plan":
            console.print(f"[green]Overwrote plan comment:[/green] {comment_id}")
    except Exception as e:
        console.print(f"[red]Failed to write comment: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def progress(
    task_id: str = typer.Argument(..., help="Task ID"),
    text: str = typer.Argument(..., help="Progress or plan text"),
    entry_type: str = typer.Option("auto", "--type", help="Entry type: auto | plan | progress"),
    mode: Optional[str] = typer.Option(None, "--mode", help="Override write mode: append | update-last | overwrite-latest-plan"),
    dedupe: bool = typer.Option(True, "--dedupe/--no-dedupe", help="Skip near-duplicate comment writes"),
    recent: int = typer.Option(5, "--recent", min=1, max=20, help="Number of recent comments to check for dedupe"),
    force: bool = typer.Option(False, "--force", help="Bypass dedupe checks"),
    close: bool = typer.Option(False, "--close", help="Close task after successful write"),
):
    """Write a smart plan/progress comment with optional close-after-comment."""
    api = get_api()
    valid_types = {"auto", "plan", "progress"}
    valid_modes = {"append", "update-last", "overwrite-latest-plan"}
    entry_type = entry_type.strip().lower()
    if entry_type not in valid_types:
        console.print(f"[red]Invalid --type '{entry_type}'. Use one of: {', '.join(sorted(valid_types))}[/red]")
        raise typer.Exit(1)
    if mode is not None:
        mode = mode.strip().lower()
        if mode not in valid_modes:
            console.print(f"[red]Invalid --mode '{mode}'. Use one of: {', '.join(sorted(valid_modes))}[/red]")
            raise typer.Exit(1)
    if force:
        dedupe = False

    inferred_type = _infer_progress_type(text) if entry_type == "auto" else entry_type
    marker = "[openclaw:plan]" if inferred_type == "plan" else "[openclaw:progress]"
    content = _ensure_comment_marker(text, marker)
    write_mode = mode or ("overwrite-latest-plan" if inferred_type == "plan" else "append")

    try:
        action, comment_id = _write_task_comment(api, task_id, content, mode=write_mode, dedupe=dedupe, recent=recent)
        console.print(
            f"[green]Progress write:[/green] action={action} type={inferred_type} mode={write_mode} comment_id={comment_id}"
        )
        if close and action != "skipped_duplicate":
            api.complete_task(task_id)
            console.print(f"[green]Closed task:[/green] {task_id}")
        elif close and action == "skipped_duplicate":
            console.print("[yellow]Task left open:[/yellow] skipped duplicate comment")
    except Exception as e:
        console.print(f"[red]Failed to write progress: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def comments(
    task_id: str = typer.Argument(..., help="Task ID"),
):
    """List comments for a task."""
    api = get_api()

    try:
        task_comments = []
        for page in api.get_comments(task_id=task_id):
            task_comments.extend(page)
        if not task_comments:
            console.print("[dim]No comments[/dim]")
            return
        print_comments(task_comments)
    except Exception as e:
        console.print(f"[red]Failed to get comments: {e}[/red]")
        raise typer.Exit(1)


@app.command(name="comments-clear")
def comments_clear(
    task_id: str = typer.Argument(..., help="Task ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    keep_plan: bool = typer.Option(False, "--keep-plan", help="Keep [openclaw:plan] comments"),
):
    """Delete comments for a task (optionally keep rolling plan comments)."""
    api = get_api()

    if not yes:
        prompt = f"Delete comments for task {task_id}?"
        if keep_plan:
            prompt += " (plan comments will be kept)"
        if not typer.confirm(prompt):
            raise typer.Abort()

    try:
        deleted, kept = _clear_task_comments(api, task_id, keep_plan=keep_plan)
        if keep_plan:
            console.print(f"[green]Cleared comments:[/green] deleted={deleted} kept_plan={kept}")
        else:
            console.print(f"[green]Cleared comments:[/green] deleted={deleted}")
    except Exception as e:
        console.print(f"[red]Failed to clear comments: {e}[/red]")
        raise typer.Exit(1)


# --- Projects Command ---
@app.command()
def projects():
    """List all projects."""
    api = get_api()
    project_list = []
    for page in api.get_projects():
        project_list.extend(page)
    print_projects(project_list)


# --- Next Actions Command ---
@app.command(name="next")
def next_actions(
    label_name: str = typer.Option("next_action", "--label", "-l", help="Label name for next actions"),
    show_description: bool = typer.Option(False, "--description", "-d", help="Show task descriptions"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """List tasks with the next_action label (GTD next actions).

    Shows all tasks that have been marked as "next actions" by Autodoist
    or manually labeled. These are the tasks you should focus on.

    Examples:
        td next                    # List all next action tasks
        td next -d                 # With descriptions
        td next --table            # Table format
        td next -l my_label        # Use different label name
    """
    api = get_api()
    project_map = get_project_map(api)

    # Fetch tasks with the next_action label
    tasks = []
    for page in api.get_tasks(label=label_name):
        tasks.extend(page)

    if not tasks:
        console.print(f"[dim]No tasks with '{label_name}' label[/dim]")
        return

    console.print(f"\n[bold green]Next Actions ({len(tasks)} tasks):[/bold green]\n")

    if table:
        print_tasks_table(tasks, project_map)
    else:
        for task in tasks:
            project_name = project_map.get(task.project_id, "")
            print_task(task, show_description=show_description, project_name=project_name)


# --- Reorder Command ---
@app.command()
def reorder(
    task_id: str = typer.Argument(..., help="Task ID to reorder"),
    position: str = typer.Argument(..., help="Target position: 'top', 'bottom', or number (1-based)"),
    show: bool = typer.Option(False, "--show", "-s", help="Show project tasks after reorder"),
):
    """Reorder a task within its project.

    Controls which task is "first" in sequential projects (ending with -),
    which determines what gets the next_action label from Autodoist.

    Positions:
        top     - Move to first position (gets next_action in sequential)
        bottom  - Move to last position
        N       - Move to position N (1-based)

    Examples:
        td reorder 12345 top       # Make this the next action
        td reorder 12345 bottom    # Push to end of list
        td reorder 12345 2         # Move to second position
        td reorder 12345 top -s    # Reorder and show new order
    """
    api = get_api()
    token = require_token()

    # Get the task to find its project
    try:
        task = api.get_task(task_id)
    except Exception:
        console.print(f"[red]Task not found: {task_id}[/red]")
        raise typer.Exit(1)

    # Get all tasks in the same project to determine order
    project_tasks = []
    for page in api.get_tasks(project_id=task.project_id):
        project_tasks.extend(page)

    # Filter to same level (same parent_id) and sort by current order
    parent_id = getattr(task, 'parent_id', None)
    sibling_tasks = [t for t in project_tasks if getattr(t, 'parent_id', None) == parent_id]

    # Sort by child_order (need to fetch via API since SDK might not expose it)
    # Use requests to get full task data with child_order
    response = requests.get(
        f"https://api.todoist.com/api/v1/tasks",
        headers={"Authorization": f"Bearer {token}"},
        params={"project_id": task.project_id},
    )
    response.raise_for_status()
    task_data = response.json().get("results", [])

    # Filter siblings and sort
    sibling_data = [t for t in task_data if t.get("parent_id") == parent_id]
    sibling_data.sort(key=lambda t: t.get("child_order", 0))

    if not sibling_data:
        console.print("[red]No tasks found in project[/red]")
        raise typer.Exit(1)

    # Determine target child_order
    position_lower = position.lower().strip()
    if position_lower == "top":
        # Move to position 0 (before all other tasks)
        target_order = 0
    elif position_lower == "bottom":
        # Move after the last task
        max_order = max(t.get("child_order", 0) for t in sibling_data)
        target_order = max_order + 1
    else:
        try:
            pos_num = int(position)
            if pos_num < 1:
                console.print("[red]Position must be >= 1[/red]")
                raise typer.Exit(1)
            # Get the child_order of the task at that position
            if pos_num == 1:
                target_order = 1
            elif pos_num > len(sibling_data):
                max_order = max(t.get("child_order", 0) for t in sibling_data)
                target_order = max_order + 1
            else:
                # Place at the position of the Nth task
                target_order = sibling_data[pos_num - 1].get("child_order", pos_num)
        except ValueError:
            console.print(f"[red]Invalid position: {position}. Use 'top', 'bottom', or a number.[/red]")
            raise typer.Exit(1)

    # Execute reorder via Sync API
    try:
        result = sync_api_command(
            token,
            "item_reorder",
            {"items": [{"id": task_id, "child_order": target_order}]}
        )
        sync_status = result.get("sync_status", {})
        if all(s == "ok" for s in sync_status.values()):
            console.print(f"[green]Reordered task to position {position}:[/green] {task.content}")
        else:
            console.print(f"[yellow]Reorder may have failed:[/yellow] {sync_status}")
    except Exception as e:
        console.print(f"[red]Failed to reorder task: {e}[/red]")
        raise typer.Exit(1)

    # Optionally show new order
    if show:
        console.print(f"\n[bold]New order in project:[/bold]")
        # Refresh task list
        response = requests.get(
            f"https://api.todoist.com/api/v1/tasks",
            headers={"Authorization": f"Bearer {token}"},
            params={"project_id": task.project_id},
        )
        if response.ok:
            new_data = response.json().get("results", [])
            new_siblings = [t for t in new_data if t.get("parent_id") == parent_id]
            new_siblings.sort(key=lambda t: t.get("child_order", 0))
            for i, t in enumerate(new_siblings, 1):
                marker = "→" if t["id"] == task_id else " "
                labels = t.get("labels", [])
                next_marker = "⭐" if "next_action" in labels else "  "
                console.print(f"  {next_marker} {i}. {marker} {t['content'][:60]}")


# --- Labels Command ---
@app.command()
def labels():
    """List all labels."""
    api = get_api()
    label_list = []
    for page in api.get_labels():
        label_list.extend(page)
    print_labels(label_list)


# --- Autodoist Commands ---
@autodoist_app.command("health")
def autodoist_health(
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON"),
):
    """Check Autodoist API health."""
    client = get_autodoist_client()
    try:
        payload = client.health()
    except AutodoistClientError as exc:
        console.print(f"[red]Autodoist health check failed:[/red] {exc}")
        raise typer.Exit(1)

    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    console.print(f"[green]ok[/green] generated_at={payload.get('generated_at', 'n/a')}")


@autodoist_app.command("state")
def autodoist_state(
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON"),
):
    """Show Autodoist state summary."""
    client = get_autodoist_client()
    try:
        payload = client.state()
    except AutodoistClientError as exc:
        console.print(f"[red]Failed to fetch Autodoist state:[/red] {exc}")
        raise typer.Exit(1)

    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return

    summary = payload.get("summary", {})
    labels = payload.get("labels", {})
    console.print(f"generated_at: {payload.get('generated_at', 'n/a')}")
    console.print(f"open_tasks: {summary.get('open_tasks', 0)}")
    console.print(f"{labels.get('next_action_label', 'next_action')}: {summary.get('next_action_count', 0)}")
    focus_label = labels.get("focus_label") or labels.get("doing_now_label", "focus")
    focus_count = summary.get("focus_count", summary.get("doing_now_count", 0))
    focus_conflicts = summary.get("focus_conflicts", summary.get("doing_now_conflicts", 0))
    console.print(f"{focus_label}: {focus_count}")
    console.print(f"focus_conflicts: {focus_conflicts}")


@autodoist_app.command("tasks")
def autodoist_tasks(
    label: Optional[str] = typer.Option(None, "--label", "-l", help="Filter by label"),
    contains: Optional[str] = typer.Option(None, "--contains", "-c", help="Filter content contains"),
    limit: Optional[int] = typer.Option(None, "--limit", "-n", help="Limit tasks"),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON"),
):
    """List tasks from Autodoist API state."""
    client = get_autodoist_client()
    try:
        payload = client.tasks(label=label, contains=contains)
    except AutodoistClientError as exc:
        console.print(f"[red]Failed to fetch Autodoist tasks:[/red] {exc}")
        raise typer.Exit(1)

    tasks = payload.get("tasks", [])
    if limit is not None and limit >= 0:
        tasks = tasks[:limit]

    if json_output:
        out = dict(payload)
        out["tasks"] = tasks
        out["count"] = len(tasks)
        typer.echo(json.dumps(out, indent=2, sort_keys=True))
        return

    if not tasks:
        console.print("[dim]No tasks found[/dim]")
        return

    for task in tasks:
        labels = ",".join(task.get("labels", []))
        updated = task.get("updated_at", "n/a")
        console.print(f"{task.get('id', '')} [{updated}] @{labels} {task.get('content', '')}")


@autodoist_app.command("checkin")
def autodoist_checkin(
    limit: int = typer.Option(3, "--limit", "-n", min=1, max=10, help="Max candidate tasks when no focus"),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON"),
):
    """Ad-hoc focus check-in: show current focus, or suggest next-action candidates."""
    client = get_autodoist_client()
    api = get_api()
    try:
        state = client.state()
    except AutodoistClientError as exc:
        console.print(f"[red]Failed to fetch Autodoist state:[/red] {exc}")
        raise typer.Exit(1)

    labels = state.get("labels", {}) or {}
    next_action_label = labels.get("next_action_label", "next_action")
    focus_label = labels.get("focus_label") or labels.get("doing_now_label", "focus")

    try:
        focus_payload = client.tasks(label=focus_label, contains=None)
    except AutodoistClientError as exc:
        console.print(f"[red]Failed to fetch focus tasks:[/red] {exc}")
        raise typer.Exit(1)

    focus_tasks = focus_payload.get("tasks", []) or []
    focus_ids = {str(t.get("id")) for t in focus_tasks if t.get("id") is not None}

    next_tasks = []
    for page in api.get_tasks(label=next_action_label):
        next_tasks.extend(page)

    today = date.today()
    next_candidates = [task for task in next_tasks if str(getattr(task, "id", "")) not in focus_ids]
    ranked_contexts = rank_next_action_candidates(tuple(_to_task_context(task) for task in next_candidates), today)
    rank_order = {ctx.id: idx for idx, ctx in enumerate(ranked_contexts)}
    next_candidates.sort(
        key=lambda task: rank_order.get(str(getattr(task, "id", "")), 9999)
    )

    if json_output:
        payload = {
            "focus_label": focus_label,
            "next_action_label": next_action_label,
            "focus_tasks": focus_tasks,
            "candidate_tasks": [
                {
                    "id": str(task.id),
                    "content": task.content,
                    "priority": int(getattr(task, "priority", 1) or 1),
                    "due": getattr(getattr(task, "due", None), "date", None),
                    "url": canonical_task_url(str(task.id)),
                }
                for task in next_candidates[:limit]
            ],
        }
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return

    if focus_tasks:
        focus = focus_tasks[0]
        focus_id = str(focus.get("id", ""))
        focus_content = focus.get("content", "")
        console.print(f"[bold]Current focus:[/bold] {focus_content}")
        console.print(canonical_task_url(focus_id))
        if next_candidates:
            best = next_candidates[0]
            console.print(
                f"\n[bold]Best next after focus:[/bold] {best.content} ({best.id})"
            )
            console.print(canonical_task_url(str(best.id)))
        return

    console.print("[yellow]No current @focus task.[/yellow]")
    if not next_candidates:
        console.print("[dim]No @next_action candidates found.[/dim]")
        return

    console.print(f"[bold]Suggested {next_action_label} candidates:[/bold]")
    for idx, task in enumerate(next_candidates[:limit], start=1):
        due = getattr(task, "due", None)
        due_date = getattr(due, "date", None) if due else None
        reason = "unscheduled"
        if due_date:
            if str(due_date) < today.isoformat():
                reason = "overdue"
            elif str(due_date) == today.isoformat():
                reason = "due today"
            else:
                reason = f"due {due_date}"
        console.print(f"{idx}. {task.content} ({task.id}) [{reason}]")
        console.print(f"   {canonical_task_url(str(task.id))}")


@autodoist_app.command("focus")
@autodoist_app.command("doing-now", hidden=True)
def autodoist_focus(
    apply: bool = typer.Option(False, "--apply", help="Apply reconcile (default is dry-run)"),
    winner_task_id: Optional[str] = typer.Option(None, "--winner-task-id", help="Prefer specific winner task id"),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON"),
):
    """Reconcile singleton focus label via Autodoist."""
    client = get_autodoist_client()
    try:
        payload = client.reconcile_focus(apply=apply, winner_task_id=winner_task_id)
    except AutodoistClientError as exc:
        console.print(f"[red]Failed to reconcile focus:[/red] {exc}")
        raise typer.Exit(1)

    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return

    mode = "applied" if payload.get("applied") else "dry-run"
    console.print(f"mode: {mode}")
    console.print(f"winner_task_id: {payload.get('winner_task_id')}")
    console.print(f"removed_count: {payload.get('removed_count', 0)}")
    if payload.get("message"):
        console.print(payload["message"])


@autodoist_app.command("set-focus")
@autodoist_app.command("set-doing-now", hidden=True)
def autodoist_set_focus(
    task_id: str = typer.Argument(..., help="Task ID to force as focus winner"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview only, do not apply"),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON"),
):
    """Set focus winner task through reconcile override."""
    client = get_autodoist_client()
    try:
        payload = client.reconcile_focus(apply=not dry_run, winner_task_id=task_id)
    except AutodoistClientError as exc:
        console.print(f"[red]Failed to set focus winner:[/red] {exc}")
        raise typer.Exit(1)

    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return

    mode = "applied" if payload.get("applied") else "dry-run"
    console.print(f"mode: {mode}")
    console.print(f"winner_task_id: {payload.get('winner_task_id')}")
    console.print(f"removed_count: {payload.get('removed_count', 0)}")


@autodoist_app.command("action")
def autodoist_action(
    task_id: str = typer.Argument(..., help="Task ID"),
    action: str = typer.Argument(
        ..., help="One of: set-focus, clear-focus, remove-next-action, make-winner"
    ),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON"),
):
    """Apply a row-level label action to a task in Autodoist."""
    normalized = action.strip().lower().replace("-", "_")
    allowed = {"set_focus", "clear_focus", "remove_next_action", "make_winner"}
    if normalized not in allowed:
        console.print(
            "[red]Invalid action.[/red] Use one of: set-focus, clear-focus, remove-next-action, make-winner"
        )
        raise typer.Exit(1)

    client = get_autodoist_client()
    try:
        payload = client.task_label_action(task_id=task_id, action=normalized)
    except AutodoistClientError as exc:
        console.print(f"[red]Failed to apply action:[/red] {exc}")
        raise typer.Exit(1)

    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return

    if payload.get("message"):
        console.print(payload["message"])
    else:
        console.print(f"action: {payload.get('action', normalized)} task_id: {payload.get('task_id', task_id)}")


# --- Config Command ---
@app.command()
def config(
    token: Optional[str] = typer.Option(None, "--token", "-t", help="Set API token"),
    autodoist_url: Optional[str] = typer.Option(
        None, "--autodoist-url", help="Set Autodoist base URL (e.g. https://autodoist.erauner.dev)"
    ),
    show: bool = typer.Option(False, "--show", "-s", help="Show current config (redacted)"),
):
    """Manage CLI configuration."""
    if show:
        cfg = get_config()
        if cfg.get("token"):
            cfg["token"] = cfg["token"][:8] + "..." + cfg["token"][-4:]
        console.print(cfg)
        return

    if token:
        cfg = get_config()
        cfg["token"] = token
        save_config(cfg)
        console.print("[green]Token saved to ~/.config/todoist/config.json[/green]")
        return

    if autodoist_url:
        cfg = get_config()
        cfg["autodoist_url"] = autodoist_url.rstrip("/")
        save_config(cfg)
        console.print("[green]Autodoist URL saved to ~/.config/todoist/config.json[/green]")
        return

    console.print("Use --token, --autodoist-url, or --show")


# --- Audit ---
@app.command()
def audit(
    stale: int = typer.Option(
        14, "--stale", "-s", help="Days before a next action is considered stale"
    ),
    label_name: str = typer.Option(
        "next_action", "--label", "-l", help="Label name for next actions"
    ),
):
    """Audit GTD project health.

    Checks for projects without next actions and stale next action tasks.
    GTD projects are identified by Autodoist-style suffixes (- or =).

    The health score is computed as:
    - 70% weight: project coverage (GTD projects with next actions)
    - 30% weight: task freshness (next actions not stale)
    """
    api = get_api()
    try:
        result = run_audit(api, label_name, stale)
    except Exception as e:
        console.print(f"[red]Audit failed:[/red] {e}")
        raise typer.Exit(1)
    print_audit(result, stale, console)


# --- Version ---
@app.command()
def version():
    """Show CLI version."""
    console.print(f"todoist-cli v{__version__}")


if __name__ == "__main__":
    app()
