"""Todoist CLI - Main command-line interface."""

from datetime import date, datetime
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
