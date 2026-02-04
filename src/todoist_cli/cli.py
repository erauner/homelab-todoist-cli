"""Todoist CLI - Main command-line interface."""

from datetime import date, datetime, timedelta
from typing import Optional
import typer
from rich.console import Console
from todoist_api_python.api import TodoistAPI

from . import __version__
from .config import require_token, get_config, save_config
from .formatting import (
    print_task,
    print_tasks_table,
    print_projects,
    print_labels,
    print_comments,
    print_task_detail,
    console,
)

app = typer.Typer(
    name="td",
    help="Todoist CLI - Full-featured command-line interface with description and comment support.",
    no_args_is_help=True,
)


def get_api() -> TodoistAPI:
    """Get configured API client."""
    return TodoistAPI(require_token())


def get_project_map(api: TodoistAPI) -> dict[str, str]:
    """Get mapping of project ID to name."""
    result = {}
    for page in api.get_projects():
        for p in page:
            result[p.id] = p.name
    return result


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
    api = get_api()
    project_map = get_project_map(api)

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

    # Flatten paginated results
    tasks = []
    for page in api.get_tasks(**kwargs):
        tasks.extend(page)

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


# --- Add Command ---
@app.command()
def add(
    content: str = typer.Argument(..., help="Task content"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Task description"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name"),
    priority: int = typer.Option(1, "--priority", "-P", help="Priority (1=p4 lowest, 4=p1 highest)"),
    due: Optional[str] = typer.Option(None, "--due", "-D", help="Due date (e.g., 'today', 'tomorrow', '2024-12-31')"),
    deadline: Optional[str] = typer.Option(None, "--deadline", help="Hard deadline date (YYYY-MM-DD format)"),
    duration: Optional[int] = typer.Option(None, "--duration", help="Task duration amount"),
    duration_unit: Optional[str] = typer.Option(None, "--duration-unit", help="Duration unit: 'minute' or 'day'"),
    labels: Optional[str] = typer.Option(None, "--labels", "-l", help="Labels (comma-separated)"),
):
    """Add a new task."""
    api = get_api()

    kwargs = {"content": content, "priority": priority}

    if description:
        kwargs["description"] = description

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
    if task.description:
        console.print(f"[dim]Description: {task.description}[/dim]")
    if task.deadline:
        console.print(f"[dim]Deadline: {task.deadline.date}[/dim]")
    if task.duration:
        console.print(f"[dim]Duration: {task.duration.amount} {task.duration.unit}(s)[/dim]")


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
):
    """Complete/close a task."""
    api = get_api()

    try:
        api.close_task(task_id)
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
        task = api.move_task(task_id=task_id, project_id=target_project_id)
        console.print(f"[green]Moved task to {project_name}:[/green] {task.content}")
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
    priority: Optional[int] = typer.Option(None, "--priority", "-P", help="New priority (1-4)"),
    due: Optional[str] = typer.Option(None, "--due", "-D", help="New due date"),
    deadline: Optional[str] = typer.Option(None, "--deadline", help="New deadline date (YYYY-MM-DD format)"),
    duration: Optional[int] = typer.Option(None, "--duration", help="Task duration amount"),
    duration_unit: Optional[str] = typer.Option(None, "--duration-unit", help="Duration unit: 'minute' or 'day'"),
    labels: Optional[str] = typer.Option(None, "--labels", "-l", help="New labels (comma-separated)"),
):
    """Modify an existing task."""
    api = get_api()

    kwargs = {}
    if content:
        kwargs["content"] = content
    if description is not None:
        kwargs["description"] = description
    if priority:
        kwargs["priority"] = priority
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


# --- Comment Commands ---
@app.command()
def comment(
    task_id: str = typer.Argument(..., help="Task ID"),
    text: str = typer.Argument(..., help="Comment text"),
):
    """Add a comment to a task."""
    api = get_api()

    try:
        comment = api.add_comment(task_id=task_id, content=text)
        console.print(f"[green]Added comment:[/green] {comment.id}")
    except Exception as e:
        console.print(f"[red]Failed to add comment: {e}[/red]")
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


# --- Projects Command ---
@app.command()
def projects():
    """List all projects."""
    api = get_api()
    project_list = []
    for page in api.get_projects():
        project_list.extend(page)
    print_projects(project_list)


# --- Labels Command ---
@app.command()
def labels():
    """List all labels."""
    api = get_api()
    label_list = []
    for page in api.get_labels():
        label_list.extend(page)
    print_labels(label_list)


# --- Config Command ---
@app.command()
def config(
    token: Optional[str] = typer.Option(None, "--token", "-t", help="Set API token"),
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

    console.print("Use --token to set token or --show to view config")


# --- Version ---
@app.command()
def version():
    """Show CLI version."""
    console.print(f"todoist-cli v{__version__}")


if __name__ == "__main__":
    app()
