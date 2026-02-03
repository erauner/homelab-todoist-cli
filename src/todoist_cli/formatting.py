"""Output formatting utilities."""

from rich.console import Console
from rich.table import Table
from rich.text import Text
from todoist_api_python.models import Task, Project, Label, Comment

console = Console()

PRIORITY_COLORS = {
    1: "white",      # p4 (lowest)
    2: "blue",       # p3
    3: "yellow",     # p2
    4: "red bold",   # p1 (highest)
}

PRIORITY_LABELS = {
    1: "p4",
    2: "p3",
    3: "p2",
    4: "p1",
}


def format_priority(priority: int) -> Text:
    """Format priority with color."""
    label = PRIORITY_LABELS.get(priority, "p4")
    color = PRIORITY_COLORS.get(priority, "white")
    return Text(label, style=color)


def format_due(due) -> str:
    """Format due date."""
    if not due:
        return ""
    if hasattr(due, "datetime") and due.datetime:
        return due.datetime
    if hasattr(due, "date"):
        return due.date
    return str(due)


def format_deadline(deadline) -> str:
    """Format deadline date."""
    if not deadline:
        return ""
    if hasattr(deadline, "date"):
        return deadline.date
    return str(deadline)


def print_task(task: Task, show_description: bool = False, project_name: str | None = None) -> None:
    """Print a single task."""
    priority = format_priority(task.priority)
    due = format_due(task.due)
    deadline = format_deadline(task.deadline)

    # Build the task line
    line = Text()
    line.append(f"{task.id} ", style="dim cyan")
    line.append_text(priority)
    line.append(" ")
    if due:
        line.append(f"[{due}] ", style="magenta")
    if deadline:
        line.append(f"(deadline: {deadline}) ", style="red")
    if project_name:
        line.append(f"#{project_name} ", style="blue")
    if task.labels:
        line.append(f"@{','.join(task.labels)} ", style="green")
    line.append(task.content)

    console.print(line)

    if show_description and task.description:
        console.print(f"    [dim]{task.description}[/dim]")


def print_tasks_table(tasks: list[Task], projects: dict[str, str] | None = None) -> None:
    """Print tasks in a table format."""
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", style="dim cyan", width=12)
    table.add_column("P", width=3)
    table.add_column("Due", style="magenta", width=12)
    table.add_column("Deadline", style="red", width=12)
    table.add_column("Project", style="blue", width=15)
    table.add_column("Content")

    for task in tasks:
        project_name = ""
        if projects and task.project_id:
            project_name = projects.get(task.project_id, "")

        table.add_row(
            task.id,
            PRIORITY_LABELS.get(task.priority, "p4"),
            format_due(task.due),
            format_deadline(task.deadline),
            project_name,
            task.content,
        )

    console.print(table)


def print_projects(projects: list[Project]) -> None:
    """Print projects."""
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", style="dim cyan")
    table.add_column("Name", style="blue")
    table.add_column("Color")

    for project in projects:
        table.add_row(project.id, project.name, project.color)

    console.print(table)


def print_labels(labels: list[Label]) -> None:
    """Print labels."""
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", style="dim cyan")
    table.add_column("Name", style="green")
    table.add_column("Color")

    for label in labels:
        table.add_row(label.id, label.name, label.color)

    console.print(table)


def print_comments(comments: list[Comment]) -> None:
    """Print comments."""
    for comment in comments:
        console.print(f"[dim cyan]{comment.id}[/dim cyan] [{comment.posted_at}]")
        console.print(f"  {comment.content}")
        console.print()


def print_task_detail(task: Task, comments: list[Comment] | None = None, project_name: str | None = None) -> None:
    """Print detailed task information."""
    console.print(f"[bold]Task:[/bold] {task.content}")
    console.print(f"[bold]ID:[/bold] {task.id}")
    console.print(f"[bold]Priority:[/bold] ", end="")
    console.print(format_priority(task.priority))

    if task.due:
        console.print(f"[bold]Due:[/bold] {format_due(task.due)}")

    if task.deadline:
        console.print(f"[bold]Deadline:[/bold] [red]{format_deadline(task.deadline)}[/red]")

    if project_name:
        console.print(f"[bold]Project:[/bold] {project_name}")

    if task.labels:
        console.print(f"[bold]Labels:[/bold] {', '.join(task.labels)}")

    if task.description:
        console.print(f"\n[bold]Description:[/bold]")
        console.print(f"  {task.description}")

    if comments:
        console.print(f"\n[bold]Comments ({len(comments)}):[/bold]")
        for comment in comments:
            console.print(f"  [{comment.posted_at}] {comment.content}")

    console.print(f"\n[bold]URL:[/bold] {task.url}")
