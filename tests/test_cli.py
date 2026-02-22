"""Tests for CLI commands."""

from unittest.mock import MagicMock, patch
from typer.testing import CliRunner
import pytest

from todoist_cli.cli import app
from todoist_cli.autodoist import AutodoistClientError


runner = CliRunner()


def make_mock_task(
    id: str = "123",
    content: str = "Test task",
    description: str = "",
    priority: int = 1,
    project_id: str = "proj1",
    labels: list = None,
    due = None,
    deadline = None,
    duration = None,
    url: str = "https://todoist.com/task/123",
    created_at: str = "2025-01-15T10:00:00Z",
):
    """Create a mock task object."""
    task = MagicMock()
    task.id = id
    task.content = content
    task.description = description
    task.priority = priority
    task.project_id = project_id
    task.labels = labels or []
    task.due = due
    task.deadline = deadline
    task.duration = duration
    task.url = url
    task.created_at = created_at
    return task


def make_mock_due(date: str, string: str = None, datetime: str = None):
    """Create a mock due object."""
    due = MagicMock()
    due.date = date
    due.string = string or date
    due.datetime = datetime
    return due


def make_mock_project(id: str = "proj1", name: str = "Inbox", color: str = "grey", inbox_project: bool = False):
    """Create a mock project object."""
    project = MagicMock()
    project.id = id
    project.name = name
    project.color = color
    project.inbox_project = inbox_project
    return project


def make_mock_label(id: str = "label1", name: str = "urgent", color: str = "red"):
    """Create a mock label object."""
    label = MagicMock()
    label.id = id
    label.name = name
    label.color = color
    return label


def make_mock_comment(id: str = "comment1", content: str = "Test comment", posted_at: str = "2024-01-01"):
    """Create a mock comment object."""
    comment = MagicMock()
    comment.id = id
    comment.content = content
    comment.posted_at = posted_at
    return comment


@pytest.fixture
def mock_api():
    """Create a mock API with common setup."""
    with patch("todoist_cli.cli.TodoistAPI") as MockAPI:
        api = MagicMock()
        MockAPI.return_value = api

        # Default: return empty paginated results
        api.get_projects.return_value = iter([[make_mock_project()]])
        api.get_tasks.return_value = iter([[]])
        api.get_labels.return_value = iter([[]])
        api.get_comments.return_value = iter([[]])

        yield api


@pytest.fixture
def mock_token():
    """Mock the token requirement."""
    with patch("todoist_cli.cli.require_token", return_value="test_token"):
        yield


class TestVersion:
    """Tests for version command."""

    def test_version(self):
        """Version command shows version."""
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "todoist-cli v" in result.output


class TestList:
    """Tests for list command."""

    def test_list_empty(self, mock_api, mock_token):
        """List with no tasks shows message."""
        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "No tasks found" in result.output

    def test_list_with_tasks(self, mock_api, mock_token):
        """List shows tasks."""
        mock_api.get_tasks.return_value = iter([[
            make_mock_task(id="1", content="Task 1"),
            make_mock_task(id="2", content="Task 2"),
        ]])

        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "Task 1" in result.output
        assert "Task 2" in result.output

    def test_list_with_project_filter(self, mock_api, mock_token):
        """List filters by project."""
        mock_api.get_projects.return_value = iter([[
            make_mock_project(id="proj1", name="Work"),
        ]])
        mock_api.get_tasks.return_value = iter([[
            make_mock_task(content="Work task", project_id="proj1"),
        ]])

        result = runner.invoke(app, ["list", "--project", "Work"])
        assert result.exit_code == 0
        mock_api.get_tasks.assert_called_once()
        call_kwargs = mock_api.get_tasks.call_args[1]
        assert call_kwargs.get("project_id") == "proj1"

    def test_list_project_not_found(self, mock_api, mock_token):
        """List with invalid project shows error."""
        result = runner.invoke(app, ["list", "--project", "NonExistent"])
        assert result.exit_code == 1
        assert "not found" in result.output


class TestAdd:
    """Tests for add command."""

    def test_add_basic(self, mock_api, mock_token):
        """Add creates task with content."""
        mock_api.add_task.return_value = make_mock_task(content="New task")

        result = runner.invoke(app, ["add", "New task"])
        assert result.exit_code == 0
        assert "Created task" in result.output
        mock_api.add_task.assert_called_once()
        call_kwargs = mock_api.add_task.call_args[1]
        assert call_kwargs["content"] == "New task"

    def test_add_with_description(self, mock_api, mock_token):
        """Add creates task with description."""
        mock_api.add_task.return_value = make_mock_task(
            content="Task with desc",
            description="This is the description"
        )

        result = runner.invoke(app, ["add", "Task with desc", "-d", "This is the description"])
        assert result.exit_code == 0
        assert "Created task" in result.output
        assert "Description" in result.output
        call_kwargs = mock_api.add_task.call_args[1]
        assert call_kwargs["description"] == "This is the description"

    def test_add_normalizes_multiline_description(self, mock_api, mock_token):
        """Add preserves paragraph breaks while normalizing whitespace."""
        mock_api.add_task.return_value = make_mock_task(content="Task with desc")

        result = runner.invoke(
            app,
            ["add", "Task with desc", "-d", "Line one\n\n  Line two\tLine three"],
        )
        assert result.exit_code == 0
        call_kwargs = mock_api.add_task.call_args[1]
        assert call_kwargs["description"] == "Line one\n\nLine two Line three"

    def test_add_with_due_date(self, mock_api, mock_token):
        """Add creates task with due date."""
        mock_api.add_task.return_value = make_mock_task(content="Task with due")

        result = runner.invoke(app, ["add", "Task with due", "--due", "tomorrow"])
        assert result.exit_code == 0
        call_kwargs = mock_api.add_task.call_args[1]
        assert call_kwargs["due_string"] == "tomorrow"

    def test_add_with_priority(self, mock_api, mock_token):
        """Add creates task with priority."""
        mock_api.add_task.return_value = make_mock_task(content="High priority", priority=4)

        result = runner.invoke(app, ["add", "High priority", "--priority", "4"])
        assert result.exit_code == 0
        call_kwargs = mock_api.add_task.call_args[1]
        assert call_kwargs["priority"] == 4

    def test_add_with_labels(self, mock_api, mock_token):
        """Add creates task with labels."""
        mock_api.add_task.return_value = make_mock_task(content="Labeled task", labels=["work", "urgent"])

        result = runner.invoke(app, ["add", "Labeled task", "--labels", "work,urgent"])
        assert result.exit_code == 0
        call_kwargs = mock_api.add_task.call_args[1]
        assert call_kwargs["labels"] == ["work", "urgent"]

    def test_add_with_project(self, mock_api, mock_token):
        """Add creates task in project."""
        mock_api.get_projects.return_value = iter([[
            make_mock_project(id="proj1", name="Work"),
        ]])
        mock_api.add_task.return_value = make_mock_task(content="Work task", project_id="proj1")

        result = runner.invoke(app, ["add", "Work task", "--project", "Work"])
        assert result.exit_code == 0
        call_kwargs = mock_api.add_task.call_args[1]
        assert call_kwargs["project_id"] == "proj1"

    def test_add_with_parent_id_creates_subtask(self, mock_api, mock_token):
        """Add passes parent_id so task is created as subtask."""
        mock_api.add_task.return_value = make_mock_task(content="Subtask")

        result = runner.invoke(app, ["add", "Subtask", "--parent-id", "parent123"])
        assert result.exit_code == 0
        call_kwargs = mock_api.add_task.call_args[1]
        assert call_kwargs["parent_id"] == "parent123"

    def test_add_focus_sets_focus_winner(self, mock_api, mock_token):
        """add-focus creates task and applies make_winner action."""
        mock_api.add_task.return_value = make_mock_task(id="new123", content="Focus task")
        mock_auto = MagicMock()
        mock_auto.task_label_action.return_value = {
            "ok": True,
            "action": "make_winner",
            "task_id": "new123",
            "message": "Task new123 is now focus winner.",
        }

        with patch("todoist_cli.cli.get_autodoist_client", return_value=mock_auto):
            result = runner.invoke(app, ["add-focus", "Focus task"])

        assert result.exit_code == 0
        assert "Created task" in result.output
        assert "Set focus" in result.output
        mock_auto.task_label_action.assert_called_once_with(task_id="new123", action="make_winner")

    def test_add_focus_fails_when_focus_action_fails(self, mock_api, mock_token):
        """add-focus exits non-zero when focus action fails."""
        mock_api.add_task.return_value = make_mock_task(id="new123", content="Focus task")
        mock_auto = MagicMock()
        mock_auto.task_label_action.side_effect = AutodoistClientError("boom")

        with patch("todoist_cli.cli.get_autodoist_client", return_value=mock_auto):
            result = runner.invoke(app, ["add-focus", "Focus task"])

        assert result.exit_code == 1
        assert "Failed to set focus for new task" in result.output

    def test_add_focus_normalizes_multiline_description(self, mock_api, mock_token):
        """add-focus preserves paragraph breaks while cleaning line whitespace."""
        mock_api.add_task.return_value = make_mock_task(id="new123", content="Focus task")
        mock_auto = MagicMock()
        mock_auto.task_label_action.return_value = {
            "ok": True,
            "action": "make_winner",
            "task_id": "new123",
            "message": "Task new123 is now focus winner.",
        }

        with patch("todoist_cli.cli.get_autodoist_client", return_value=mock_auto):
            result = runner.invoke(
                app,
                ["add-focus", "Focus task", "-d", "Do this\n\n  right\taway"],
            )

        assert result.exit_code == 0
        call_kwargs = mock_api.add_task.call_args[1]
        assert call_kwargs["description"] == "Do this\n\nright away"

    def test_add_focus_with_parent_id_creates_subtask(self, mock_api, mock_token):
        """add-focus passes parent_id so focused task can be a subtask."""
        mock_api.add_task.return_value = make_mock_task(id="new123", content="Focus subtask")
        mock_auto = MagicMock()
        mock_auto.task_label_action.return_value = {
            "ok": True,
            "action": "make_winner",
            "task_id": "new123",
            "message": "Task new123 is now focus winner.",
        }

        with patch("todoist_cli.cli.get_autodoist_client", return_value=mock_auto):
            result = runner.invoke(app, ["add-focus", "Focus subtask", "--parent-id", "parent123"])

        assert result.exit_code == 0
        call_kwargs = mock_api.add_task.call_args[1]
        assert call_kwargs["parent_id"] == "parent123"


class TestQuery:
    """Tests for query command."""

    def test_query_json(self, mock_token):
        mock_client = MagicMock()
        mock_client.list_tasks_by_filter.return_value = [
            {"id": "1", "content": "Task 1", "priority": 1, "due": None},
            {"id": "2", "content": "Task 2", "priority": 2, "due": {"date": "2026-02-15"}},
        ]

        with patch("todoist_cli.cli.get_client", return_value=mock_client):
            result = runner.invoke(app, ["query", "today", "--json"])

        assert result.exit_code == 0
        assert "\"content\": \"Task 1\"" in result.output
        assert "\"content\": \"Task 2\"" in result.output
        mock_client.list_tasks_by_filter.assert_called_once_with("today")

    def test_query_limit(self, mock_token):
        mock_client = MagicMock()
        mock_client.list_tasks_by_filter.return_value = [
            {"id": "1", "content": "Task 1", "priority": 1},
            {"id": "2", "content": "Task 2", "priority": 1},
            {"id": "3", "content": "Task 3", "priority": 1},
        ]

        with patch("todoist_cli.cli.get_client", return_value=mock_client):
            result = runner.invoke(app, ["query", "today", "--limit", "2"])

        assert result.exit_code == 0
        assert "Task 1" in result.output
        assert "Task 2" in result.output
        assert "Task 3" not in result.output


class TestShow:
    """Tests for show command."""

    def test_show_task(self, mock_api, mock_token):
        """Show displays task details."""
        mock_api.get_task.return_value = make_mock_task(
            id="123",
            content="Test task",
            description="Task description",
        )

        result = runner.invoke(app, ["show", "123"])
        assert result.exit_code == 0
        assert "Test task" in result.output
        assert "Task description" in result.output

    def test_show_task_with_comments(self, mock_api, mock_token):
        """Show displays task with comments."""
        mock_api.get_task.return_value = make_mock_task(content="Task with comments")
        mock_api.get_comments.return_value = iter([[
            make_mock_comment(content="First comment"),
            make_mock_comment(content="Second comment"),
        ]])

        result = runner.invoke(app, ["show", "123"])
        assert result.exit_code == 0
        assert "First comment" in result.output
        assert "Second comment" in result.output

    def test_show_task_not_found(self, mock_api, mock_token):
        """Show handles missing task."""
        mock_api.get_task.side_effect = Exception("Not found")

        result = runner.invoke(app, ["show", "nonexistent"])
        assert result.exit_code == 1
        assert "not found" in result.output


class TestModify:
    """Tests for modify command."""

    def test_modify_content(self, mock_api, mock_token):
        """Modify updates task content."""
        mock_api.update_task.return_value = make_mock_task(content="Updated content")

        result = runner.invoke(app, ["modify", "123", "--content", "Updated content"])
        assert result.exit_code == 0
        assert "Updated task" in result.output
        call_kwargs = mock_api.update_task.call_args[1]
        assert call_kwargs["content"] == "Updated content"

    def test_modify_description(self, mock_api, mock_token):
        """Modify updates task description."""
        mock_api.update_task.return_value = make_mock_task(description="New description")

        result = runner.invoke(app, ["modify", "123", "--description", "New description"])
        assert result.exit_code == 0
        call_kwargs = mock_api.update_task.call_args[1]
        assert call_kwargs["description"] == "New description"

    def test_modify_normalizes_multiline_description(self, mock_api, mock_token):
        """Modify preserves paragraph breaks while normalizing whitespace."""
        mock_api.update_task.return_value = make_mock_task(description="New description")

        result = runner.invoke(
            app,
            ["modify", "123", "--description", "New\n\n  description\tvalue"],
        )
        assert result.exit_code == 0
        call_kwargs = mock_api.update_task.call_args[1]
        assert call_kwargs["description"] == "New\n\ndescription value"

    def test_modify_priority(self, mock_api, mock_token):
        """Modify updates task priority."""
        mock_api.update_task.return_value = make_mock_task(priority=3)

        result = runner.invoke(app, ["modify", "123", "--priority", "3"])
        assert result.exit_code == 0
        call_kwargs = mock_api.update_task.call_args[1]
        assert call_kwargs["priority"] == 3

    def test_modify_due(self, mock_api, mock_token):
        """Modify updates task due date."""
        mock_api.update_task.return_value = make_mock_task()

        result = runner.invoke(app, ["modify", "123", "--due", "next monday"])
        assert result.exit_code == 0
        call_kwargs = mock_api.update_task.call_args[1]
        assert call_kwargs["due_string"] == "next monday"

    def test_modify_no_changes(self, mock_api, mock_token):
        """Modify with no options shows error."""
        result = runner.invoke(app, ["modify", "123"])
        assert result.exit_code == 1
        assert "No modifications" in result.output

    def test_modify_no_due(self, mock_api, mock_token):
        """Modify with --no-due clears due date."""
        mock_api.update_task.return_value = make_mock_task()

        result = runner.invoke(app, ["modify", "123", "--no-due"])
        assert result.exit_code == 0
        call_kwargs = mock_api.update_task.call_args[1]
        assert call_kwargs["due_string"] == "no date"

    def test_modify_no_due_short_flag(self, mock_api, mock_token):
        """Modify with -N clears due date."""
        mock_api.update_task.return_value = make_mock_task()

        result = runner.invoke(app, ["modify", "123", "-N"])
        assert result.exit_code == 0
        call_kwargs = mock_api.update_task.call_args[1]
        assert call_kwargs["due_string"] == "no date"

    def test_modify_due_and_no_due_conflict(self, mock_api, mock_token):
        """Modify with both --due and --no-due shows error."""
        result = runner.invoke(app, ["modify", "123", "--due", "tomorrow", "--no-due"])
        assert result.exit_code == 1
        assert "Cannot specify both --due and --no-due" in result.output


class TestComment:
    """Tests for comment command."""

    def test_add_comment(self, mock_api, mock_token):
        """Comment adds comment to task."""
        mock_api.add_comment.return_value = make_mock_comment(id="c1", content="My comment")

        result = runner.invoke(app, ["comment", "123", "My comment"])
        assert result.exit_code == 0
        assert "Added comment" in result.output
        mock_api.add_comment.assert_called_once_with(task_id="123", content="My comment")

    def test_add_comment_preserves_paragraph_breaks(self, mock_api, mock_token):
        """Comment keeps readable paragraph breaks instead of one giant line."""
        mock_api.add_comment.return_value = make_mock_comment(id="c1", content="My comment")

        result = runner.invoke(app, ["comment", "123", "Line one\n\n  Line two\tline three"])
        assert result.exit_code == 0
        mock_api.add_comment.assert_called_once_with(
            task_id="123",
            content="Line one\n\nLine two line three",
        )

    def test_comment_dedupe_skips_similar(self, mock_api, mock_token):
        """Comment skips near-duplicate writes by default."""
        mock_api.get_comments.return_value = iter([[
            make_mock_comment(id="c1", content="My comment"),
        ]])

        result = runner.invoke(app, ["comment", "123", "My   comment"])
        assert result.exit_code == 0
        assert "Skipped duplicate comment" in result.output
        mock_api.add_comment.assert_not_called()

    def test_comment_force_bypasses_dedupe(self, mock_api, mock_token):
        """Comment writes when --force is supplied."""
        mock_api.get_comments.return_value = iter([[
            make_mock_comment(id="c1", content="My comment"),
        ]])
        mock_api.add_comment.return_value = make_mock_comment(id="c2", content="My comment")

        result = runner.invoke(app, ["comment", "123", "My comment", "--force"])
        assert result.exit_code == 0
        assert "Added comment" in result.output
        mock_api.add_comment.assert_called_once_with(task_id="123", content="My comment")

    def test_comment_update_last_mode(self, mock_api, mock_token):
        """Comment updates latest comment with update-last mode."""
        mock_api.get_comments.return_value = iter([[
            make_mock_comment(id="c-old", content="Old", posted_at="2026-02-22T10:00:00Z"),
            make_mock_comment(id="c-new", content="New", posted_at="2026-02-22T11:00:00Z"),
        ]])
        mock_api.update_comment.return_value = make_mock_comment(id="c-new", content="Updated")

        result = runner.invoke(
            app,
            ["comment", "123", "Updated text", "--mode", "update-last", "--no-dedupe"],
        )
        assert result.exit_code == 0
        assert "Updated latest comment" in result.output
        mock_api.update_comment.assert_called_once_with(comment_id="c-new", content="Updated text")

    def test_comment_overwrite_latest_plan_mode(self, mock_api, mock_token):
        """Comment overwrites latest plan-like comment when present."""
        mock_api.get_comments.return_value = iter([[
            make_mock_comment(id="c1", content="General update", posted_at="2026-02-22T12:00:00Z"),
            make_mock_comment(id="c2", content="NEXT ACTION (10 min): do thing", posted_at="2026-02-22T11:00:00Z"),
        ]])
        mock_api.update_comment.return_value = make_mock_comment(id="c2", content="NEXT ACTION: replacement")

        result = runner.invoke(
            app,
            ["comment", "123", "NEXT ACTION: replacement", "--mode", "overwrite-latest-plan", "--no-dedupe"],
        )
        assert result.exit_code == 0
        assert "Overwrote plan comment" in result.output
        mock_api.update_comment.assert_called_once_with(comment_id="c2", content="NEXT ACTION: replacement")

    def test_comment_overwrite_latest_plan_falls_back_to_append(self, mock_api, mock_token):
        """Plan overwrite mode appends when no plan-like comment exists."""
        mock_api.get_comments.return_value = iter([[
            make_mock_comment(id="c1", content="General update"),
        ]])
        mock_api.add_comment.return_value = make_mock_comment(id="c2", content="Plan comment")

        result = runner.invoke(
            app,
            ["comment", "123", "Plan comment", "--mode", "overwrite-latest-plan", "--no-dedupe"],
        )
        assert result.exit_code == 0
        assert "Added comment" in result.output
        mock_api.add_comment.assert_called_once_with(task_id="123", content="Plan comment")


class TestComments:
    """Tests for comments command."""

    def test_list_comments(self, mock_api, mock_token):
        """Comments lists task comments."""
        mock_api.get_comments.return_value = iter([[
            make_mock_comment(content="Comment 1"),
            make_mock_comment(content="Comment 2"),
        ]])

        result = runner.invoke(app, ["comments", "123"])
        assert result.exit_code == 0
        assert "Comment 1" in result.output
        assert "Comment 2" in result.output

    def test_list_comments_empty(self, mock_api, mock_token):
        """Comments shows message when empty."""
        mock_api.get_comments.return_value = iter([[]])

        result = runner.invoke(app, ["comments", "123"])
        assert result.exit_code == 0
        assert "No comments" in result.output

    def test_comments_clear_yes(self, mock_api, mock_token):
        """comments-clear deletes all comments."""
        mock_api.get_comments.return_value = iter([[
            make_mock_comment(id="c1", content="one"),
            make_mock_comment(id="c2", content="two"),
        ]])

        result = runner.invoke(app, ["comments-clear", "123", "--yes"])
        assert result.exit_code == 0
        assert "Cleared comments" in result.output
        mock_api.delete_comment.assert_any_call("c1")
        mock_api.delete_comment.assert_any_call("c2")

    def test_comments_clear_keep_plan(self, mock_api, mock_token):
        """comments-clear with --keep-plan retains plan comments."""
        mock_api.get_comments.return_value = iter([[
            make_mock_comment(id="c1", content="[openclaw:plan] current plan"),
            make_mock_comment(id="c2", content="[openclaw:progress] did thing"),
        ]])

        result = runner.invoke(app, ["comments-clear", "123", "--yes", "--keep-plan"])
        assert result.exit_code == 0
        assert "kept_plan=1" in result.output
        mock_api.delete_comment.assert_called_once_with("c2")


class TestProgress:
    """Tests for progress command."""

    def test_progress_auto_plan_overwrites_latest_plan(self, mock_api, mock_token):
        """Auto mode infers plan and overwrites latest plan comment."""
        mock_api.get_comments.return_value = iter([[
            make_mock_comment(id="c-plan", content="[openclaw:plan] old plan", posted_at="2026-02-22T12:00:00Z"),
        ]])
        mock_api.update_comment.return_value = make_mock_comment(id="c-plan", content="[openclaw:plan] new")

        result = runner.invoke(app, ["progress", "123", "Check DECOMM ticket status"])
        assert result.exit_code == 0
        assert "action=overwrote_plan" in result.output
        mock_api.update_comment.assert_called_once()
        assert mock_api.update_comment.call_args.kwargs["comment_id"] == "c-plan"
        assert mock_api.update_comment.call_args.kwargs["content"].startswith("[openclaw:plan]")

    def test_progress_normalizes_multiline_text(self, mock_api, mock_token):
        """Progress preserves paragraph breaks while cleaning whitespace."""
        mock_api.get_comments.return_value = iter([[]])
        mock_api.add_comment.return_value = make_mock_comment(id="c2", content="[openclaw:progress] done")

        result = runner.invoke(
            app,
            ["progress", "123", "Done: posted update\n\n  Shared link\tin thread", "--type", "progress"],
        )
        assert result.exit_code == 0
        content = mock_api.add_comment.call_args.kwargs["content"]
        assert content.startswith("[openclaw:progress] ")
        assert "Done: posted update\n\nShared link in thread" in content

    def test_progress_auto_infers_progress_and_appends(self, mock_api, mock_token):
        """Auto mode infers progress from status wording and appends."""
        mock_api.get_comments.return_value = iter([[]])
        mock_api.add_comment.return_value = make_mock_comment(id="c2", content="[openclaw:progress] done")

        result = runner.invoke(app, ["progress", "123", "Done: created DECOMM-42 and shared link"])
        assert result.exit_code == 0
        assert "action=added" in result.output
        mock_api.add_comment.assert_called_once()
        assert mock_api.add_comment.call_args.kwargs["content"].startswith("[openclaw:progress]")

    def test_progress_force_with_close(self, mock_api, mock_token):
        """Force bypasses dedupe and close completes task after write."""
        mock_api.get_comments.return_value = iter([[
            make_mock_comment(id="c1", content="[openclaw:progress] sent update"),
        ]])
        mock_api.add_comment.return_value = make_mock_comment(id="c2", content="[openclaw:progress] sent update")

        result = runner.invoke(app, ["progress", "123", "sent update", "--type", "progress", "--force", "--close"])
        assert result.exit_code == 0
        assert "Closed task" in result.output
        mock_api.complete_task.assert_called_once_with("123")

    def test_progress_skip_duplicate_does_not_close(self, mock_api, mock_token):
        """Skipped duplicate leaves task open even with --close."""
        mock_api.get_comments.return_value = iter([[
            make_mock_comment(id="c1", content="[openclaw:progress] sent update"),
        ]])

        result = runner.invoke(app, ["progress", "123", "sent update", "--type", "progress", "--close"])
        assert result.exit_code == 0
        assert "action=skipped_duplicate" in result.output
        assert "Task left open" in result.output
        mock_api.complete_task.assert_not_called()

class TestClose:
    """Tests for close command."""

    def test_close_task(self, mock_api, mock_token):
        """Close completes task and keeps comments for non-recurring tasks by default."""
        mock_api.get_task.return_value = make_mock_task(id="123", due=None)
        result = runner.invoke(app, ["close", "123"])
        assert result.exit_code == 0
        assert "Completed task" in result.output
        mock_api.complete_task.assert_called_once_with("123")
        mock_api.delete_comment.assert_not_called()

    def test_close_auto_clears_for_recurring_task(self, mock_api, mock_token):
        """Close auto-clears comments when task is recurring."""
        due = make_mock_due(date="2026-02-23")
        due.is_recurring = True
        mock_api.get_task.return_value = make_mock_task(id="123", due=due)
        mock_api.get_comments.return_value = iter([[
            make_mock_comment(id="c1", content="log one"),
            make_mock_comment(id="c2", content="log two"),
        ]])

        result = runner.invoke(app, ["close", "123"])
        assert result.exit_code == 0
        assert "Auto-clear enabled for recurring task comments" in result.output
        assert "Cleared comments" in result.output
        mock_api.delete_comment.assert_any_call("c1")
        mock_api.delete_comment.assert_any_call("c2")
        mock_api.complete_task.assert_called_once_with("123")

    def test_close_clear_comments(self, mock_api, mock_token):
        """Close can clear comments before completing."""
        mock_api.get_task.return_value = make_mock_task(id="123", due=None)
        mock_api.get_comments.return_value = iter([[
            make_mock_comment(id="c1", content="one"),
            make_mock_comment(id="c2", content="two"),
        ]])

        result = runner.invoke(app, ["close", "123", "--clear-comments"])
        assert result.exit_code == 0
        assert "Cleared comments" in result.output
        assert "Completed task" in result.output
        mock_api.delete_comment.assert_any_call("c1")
        mock_api.delete_comment.assert_any_call("c2")
        mock_api.complete_task.assert_called_once_with("123")

    def test_close_clear_comments_keep_plan(self, mock_api, mock_token):
        """Close with keep-plan keeps rolling plan comments."""
        mock_api.get_task.return_value = make_mock_task(id="123", due=None)
        mock_api.get_comments.return_value = iter([[
            make_mock_comment(id="c1", content="[openclaw:plan] plan"),
            make_mock_comment(id="c2", content="[openclaw:progress] log"),
        ]])

        result = runner.invoke(app, ["close", "123", "--clear-comments", "--keep-plan"])
        assert result.exit_code == 0
        assert "kept_plan=1" in result.output
        mock_api.delete_comment.assert_called_once_with("c2")
        mock_api.complete_task.assert_called_once_with("123")

    def test_close_keep_plan_conflicts_with_no_clear_comments(self, mock_api, mock_token):
        """keep-plan cannot be combined with explicit no-clear override."""
        result = runner.invoke(app, ["close", "123", "--keep-plan", "--no-clear-comments"])
        assert result.exit_code == 1
        assert "--keep-plan cannot be used with --no-clear-comments" in result.output


class TestDelete:
    """Tests for delete command."""

    def test_delete_task_force(self, mock_api, mock_token):
        """Delete with force skips confirmation."""
        result = runner.invoke(app, ["delete", "123", "--force"])
        assert result.exit_code == 0
        assert "Deleted task" in result.output
        mock_api.delete_task.assert_called_once_with("123")


class TestProjects:
    """Tests for projects command."""

    def test_list_projects(self, mock_api, mock_token):
        """Projects lists all projects."""
        mock_api.get_projects.return_value = iter([[
            make_mock_project(name="Inbox"),
            make_mock_project(name="Work"),
        ]])

        result = runner.invoke(app, ["projects"])
        assert result.exit_code == 0
        assert "Inbox" in result.output
        assert "Work" in result.output


class TestLabels:
    """Tests for labels command."""

    def test_list_labels(self, mock_api, mock_token):
        """Labels lists all labels."""
        mock_api.get_labels.return_value = iter([[
            make_mock_label(name="urgent"),
            make_mock_label(name="work"),
        ]])

        result = runner.invoke(app, ["labels"])
        assert result.exit_code == 0
        assert "urgent" in result.output
        assert "work" in result.output


class TestWorkflows:
    """Tests for key workflows mentioned in skill documentation."""

    def test_workflow_add_task_with_description(self, mock_api, mock_token):
        """Workflow: Add task with description (key feature)."""
        mock_api.add_task.return_value = make_mock_task(
            content="Follow up with kkantar",
            description="Discuss updatecli transition to express-yaml-manager"
        )

        result = runner.invoke(app, [
            "add", "Follow up with kkantar",
            "--description", "Discuss updatecli transition to express-yaml-manager"
        ])
        assert result.exit_code == 0
        call_kwargs = mock_api.add_task.call_args[1]
        assert call_kwargs["content"] == "Follow up with kkantar"
        assert call_kwargs["description"] == "Discuss updatecli transition to express-yaml-manager"

    def test_workflow_add_comment_for_update(self, mock_api, mock_token):
        """Workflow: Add comment for progress update (key feature)."""
        mock_api.add_comment.return_value = make_mock_comment(
            content="Left remark in thread: identified what's needed for transition"
        )

        result = runner.invoke(app, [
            "comment", "123",
            "Left remark in thread: identified what's needed for transition"
        ])
        assert result.exit_code == 0
        mock_api.add_comment.assert_called_once_with(
            task_id="123",
            content="Left remark in thread: identified what's needed for transition"
        )

    def test_workflow_update_description_not_title(self, mock_api, mock_token):
        """Workflow: Update description without changing title."""
        mock_api.update_task.return_value = make_mock_task(
            content="Original title",
            description="New context added"
        )

        # Only update description, not content
        result = runner.invoke(app, [
            "modify", "123",
            "--description", "New context added"
        ])
        assert result.exit_code == 0
        call_kwargs = mock_api.update_task.call_args[1]
        assert "content" not in call_kwargs
        assert call_kwargs["description"] == "New context added"

    def test_workflow_full_task_creation(self, mock_api, mock_token):
        """Workflow: Create fully specified task."""
        mock_api.get_projects.return_value = iter([[
            make_mock_project(id="work_proj", name="Work"),
        ]])
        mock_api.add_task.return_value = make_mock_task(
            content="Complete quarterly report",
            description="Include Q4 revenue and projections",
            priority=3,
            labels=["reports"]
        )

        result = runner.invoke(app, [
            "add", "Complete quarterly report",
            "--description", "Include Q4 revenue and projections",
            "--priority", "3",
            "--due", "next friday",
            "--project", "Work",
            "--labels", "reports"
        ])
        assert result.exit_code == 0
        call_kwargs = mock_api.add_task.call_args[1]
        assert call_kwargs["content"] == "Complete quarterly report"
        assert call_kwargs["description"] == "Include Q4 revenue and projections"
        assert call_kwargs["priority"] == 3
        assert call_kwargs["due_string"] == "next friday"
        assert call_kwargs["project_id"] == "work_proj"
        assert call_kwargs["labels"] == ["reports"]


class TestReopen:
    """Tests for reopen command."""

    def test_reopen_task(self, mock_api, mock_token):
        """Reopen uncompletes task."""
        result = runner.invoke(app, ["reopen", "123"])
        assert result.exit_code == 0
        assert "Reopened task" in result.output
        mock_api.uncomplete_task.assert_called_once_with("123")

    def test_reopen_task_not_found(self, mock_api, mock_token):
        """Reopen handles missing task."""
        mock_api.uncomplete_task.side_effect = Exception("Not found")

        result = runner.invoke(app, ["reopen", "nonexistent"])
        assert result.exit_code == 1
        assert "Failed to reopen" in result.output


class TestPostpone:
    """Tests for postpone command."""

    def test_postpone_with_relative_time(self, mock_api, mock_token):
        """Postpone updates due date with relative time."""
        mock_due = make_mock_due(date="2025-02-05", string="in 2 days")
        mock_api.update_task.return_value = make_mock_task(due=mock_due)

        result = runner.invoke(app, ["postpone", "123", "2 days"])
        assert result.exit_code == 0
        assert "Postponed task" in result.output
        call_kwargs = mock_api.update_task.call_args[1]
        assert call_kwargs["due_string"] == "in 2 days"

    def test_postpone_with_tomorrow(self, mock_api, mock_token):
        """Postpone with 'tomorrow' uses natural language."""
        mock_due = make_mock_due(date="2025-02-04", string="tomorrow")
        mock_api.update_task.return_value = make_mock_task(due=mock_due)

        result = runner.invoke(app, ["postpone", "123", "tomorrow"])
        assert result.exit_code == 0
        call_kwargs = mock_api.update_task.call_args[1]
        assert call_kwargs["due_string"] == "tomorrow"

    def test_postpone_failure(self, mock_api, mock_token):
        """Postpone handles API error."""
        mock_api.update_task.side_effect = Exception("API error")

        result = runner.invoke(app, ["postpone", "123", "2 days"])
        assert result.exit_code == 1
        assert "Failed to postpone" in result.output


class TestSnooze:
    """Tests for snooze command."""

    def test_snooze_no_tasks(self, mock_api, mock_token):
        """Snooze with no overdue/today tasks shows message."""
        mock_api.get_tasks.return_value = iter([[]])

        result = runner.invoke(app, ["snooze", "tomorrow"])
        assert result.exit_code == 0
        assert "No" in result.output and "tasks to snooze" in result.output

    def test_snooze_dry_run(self, mock_api, mock_token):
        """Snooze dry-run shows preview without changes."""
        from datetime import date
        today = date.today().isoformat()
        mock_due = make_mock_due(date=today)
        mock_api.get_tasks.return_value = iter([[
            make_mock_task(id="1", content="Today task", due=mock_due),
        ]])

        result = runner.invoke(app, ["snooze", "tomorrow", "--dry-run"])
        assert result.exit_code == 0
        assert "Today task" in result.output
        assert "Dry run" in result.output
        mock_api.update_task.assert_not_called()

    def test_snooze_overdue_tasks(self, mock_api, mock_token):
        """Snooze updates overdue tasks."""
        mock_due = make_mock_due(date="2020-01-01")  # In the past
        mock_api.get_tasks.return_value = iter([[
            make_mock_task(id="1", content="Overdue task", due=mock_due),
        ]])

        result = runner.invoke(app, ["snooze", "tomorrow"])
        assert result.exit_code == 0
        assert "Snoozed" in result.output
        mock_api.update_task.assert_called_once()

    def test_snooze_overdue_only(self, mock_api, mock_token):
        """Snooze with --overdue-only excludes today's tasks."""
        from datetime import date
        today = date.today().isoformat()
        overdue_due = make_mock_due(date="2020-01-01")
        today_due = make_mock_due(date=today)
        mock_api.get_tasks.return_value = iter([[
            make_mock_task(id="1", content="Overdue task", due=overdue_due),
            make_mock_task(id="2", content="Today task", due=today_due),
        ]])

        result = runner.invoke(app, ["snooze", "tomorrow", "--overdue-only", "--dry-run"])
        assert result.exit_code == 0
        assert "Overdue task" in result.output
        assert "Today task" not in result.output


class TestInbox:
    """Tests for inbox command."""

    def test_inbox_empty(self, mock_api, mock_token):
        """Inbox shows message when empty."""
        mock_api.get_projects.return_value = iter([[
            make_mock_project(id="inbox_id", name="Inbox", inbox_project=True),
        ]])
        mock_api.get_tasks.return_value = iter([[]])

        result = runner.invoke(app, ["inbox"])
        assert result.exit_code == 0
        assert "empty" in result.output.lower()

    def test_inbox_with_tasks(self, mock_api, mock_token):
        """Inbox lists tasks in inbox project."""
        mock_api.get_projects.return_value = iter([[
            make_mock_project(id="inbox_id", name="Inbox", inbox_project=True),
        ]])
        mock_api.get_tasks.return_value = iter([[
            make_mock_task(id="1", content="Inbox task 1", project_id="inbox_id"),
            make_mock_task(id="2", content="Inbox task 2", project_id="inbox_id"),
        ]])

        result = runner.invoke(app, ["inbox"])
        assert result.exit_code == 0
        assert "Inbox task 1" in result.output
        assert "Inbox task 2" in result.output

    def test_inbox_count_only(self, mock_api, mock_token):
        """Inbox --count shows only count."""
        mock_api.get_projects.return_value = iter([[
            make_mock_project(id="inbox_id", name="Inbox", inbox_project=True),
        ]])
        mock_api.get_tasks.return_value = iter([[
            make_mock_task(id="1", content="Task 1", project_id="inbox_id"),
            make_mock_task(id="2", content="Task 2", project_id="inbox_id"),
        ]])

        result = runner.invoke(app, ["inbox", "--count"])
        assert result.exit_code == 0
        assert "2" in result.output
        assert "task(s) in inbox" in result.output


class TestMove:
    """Tests for move command."""

    def test_move_task(self, mock_api, mock_token):
        """Move moves task to project."""
        mock_api.get_projects.return_value = iter([[
            make_mock_project(id="work_id", name="Work"),
        ]])
        mock_api.move_task.return_value = make_mock_task(content="Moved task", project_id="work_id")

        result = runner.invoke(app, ["move", "123", "Work"])
        assert result.exit_code == 0
        assert "Moved task to Work" in result.output
        mock_api.move_task.assert_called_once_with(task_id="123", project_id="work_id")

    def test_move_project_not_found(self, mock_api, mock_token):
        """Move shows error when project not found."""
        mock_api.get_projects.return_value = iter([[
            make_mock_project(id="proj1", name="Inbox"),
        ]])

        result = runner.invoke(app, ["move", "123", "NonExistent"])
        assert result.exit_code == 1
        assert "not found" in result.output


class TestToday:
    """Tests for today command."""

    def test_today_no_tasks(self, mock_api, mock_token):
        """Today shows message when no tasks due."""
        mock_api.get_tasks.return_value = iter([[]])

        result = runner.invoke(app, ["today"])
        assert result.exit_code == 0
        assert "Nothing due today" in result.output

    def test_today_with_tasks(self, mock_api, mock_token):
        """Today shows tasks due today."""
        from datetime import date
        today = date.today().isoformat()
        mock_due = make_mock_due(date=today)
        mock_api.get_tasks.return_value = iter([[
            make_mock_task(id="1", content="Today task", due=mock_due),
        ]])

        result = runner.invoke(app, ["today"])
        assert result.exit_code == 0
        assert "Today task" in result.output

    def test_today_includes_overdue(self, mock_api, mock_token):
        """Today includes overdue tasks by default."""
        from datetime import date
        today = date.today().isoformat()
        overdue_due = make_mock_due(date="2020-01-01")
        today_due = make_mock_due(date=today)
        mock_api.get_tasks.return_value = iter([[
            make_mock_task(id="1", content="Overdue task", due=overdue_due),
            make_mock_task(id="2", content="Today task", due=today_due),
        ]])

        result = runner.invoke(app, ["today"])
        assert result.exit_code == 0
        assert "Overdue task" in result.output
        assert "Today task" in result.output
        assert "overdue" in result.output.lower()

    def test_today_no_overdue_flag(self, mock_api, mock_token):
        """Today with --no-overdue excludes overdue tasks."""
        from datetime import date
        today = date.today().isoformat()
        overdue_due = make_mock_due(date="2020-01-01")
        today_due = make_mock_due(date=today)
        mock_api.get_tasks.return_value = iter([[
            make_mock_task(id="1", content="Overdue task", due=overdue_due),
            make_mock_task(id="2", content="Today task", due=today_due),
        ]])

        result = runner.invoke(app, ["today", "--no-overdue"])
        assert result.exit_code == 0
        assert "Overdue task" not in result.output
        assert "Today task" in result.output


class TestNextActions:
    """Tests for next command."""

    def test_next_table_handles_date_due(self, mock_api, mock_token):
        """Next table renders when due.date is a Python date instance."""
        from datetime import date

        due_obj = MagicMock()
        due_obj.datetime = None
        due_obj.date = date(2026, 2, 24)

        mock_api.get_projects.return_value = iter([[
            make_mock_project(id="proj1", name="Work"),
        ]])
        mock_api.get_tasks.return_value = iter([[
            make_mock_task(id="1", content="Focused task", project_id="proj1", due=due_obj, labels=["next_action"]),
        ]])

        result = runner.invoke(app, ["next", "--table"])
        assert result.exit_code == 0
        assert "2026-02-24" in result.output
        assert "NotRenderableError" not in result.output


class TestUpcoming:
    """Tests for upcoming command."""

    def test_upcoming_no_tasks(self, mock_api, mock_token):
        """Upcoming shows message when no tasks."""
        mock_api.get_tasks.return_value = iter([[]])

        result = runner.invoke(app, ["upcoming"])
        assert result.exit_code == 0
        assert "Nothing due" in result.output

    def test_upcoming_default_7_days(self, mock_api, mock_token):
        """Upcoming shows tasks in next 7 days by default."""
        from datetime import date, timedelta
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        mock_due = make_mock_due(date=tomorrow)
        mock_api.get_tasks.return_value = iter([[
            make_mock_task(id="1", content="Tomorrow task", due=mock_due),
        ]])

        result = runner.invoke(app, ["upcoming"])
        assert result.exit_code == 0
        assert "Tomorrow task" in result.output
        assert "7 days" in result.output

    def test_upcoming_custom_days(self, mock_api, mock_token):
        """Upcoming respects custom days argument."""
        from datetime import date, timedelta
        in_3_days = (date.today() + timedelta(days=3)).isoformat()
        mock_due = make_mock_due(date=in_3_days)
        mock_api.get_tasks.return_value = iter([[
            make_mock_task(id="1", content="Future task", due=mock_due),
        ]])

        result = runner.invoke(app, ["upcoming", "5"])
        assert result.exit_code == 0
        assert "Future task" in result.output
        assert "5 days" in result.output

    def test_upcoming_excludes_far_future(self, mock_api, mock_token):
        """Upcoming excludes tasks beyond the window."""
        far_future = "2099-12-31"
        mock_due = make_mock_due(date=far_future)
        mock_api.get_tasks.return_value = iter([[
            make_mock_task(id="1", content="Far future task", due=mock_due),
        ]])

        result = runner.invoke(app, ["upcoming", "7"])
        assert result.exit_code == 0
        assert "Far future task" not in result.output


class TestRecent:
    """Tests for recent command."""

    def test_recent_no_tasks(self, mock_api, mock_token):
        """Recent shows message when no tasks."""
        mock_api.get_tasks.return_value = iter([[]])

        result = runner.invoke(app, ["recent"])
        assert result.exit_code == 0
        assert "No tasks found" in result.output

    def test_recent_shows_newest_first(self, mock_api, mock_token):
        """Recent sorts by created_at descending."""
        mock_api.get_tasks.return_value = iter([[
            make_mock_task(id="1", content="Older task", created_at="2025-01-01T10:00:00Z"),
            make_mock_task(id="2", content="Newer task", created_at="2025-01-15T10:00:00Z"),
        ]])

        result = runner.invoke(app, ["recent"])
        assert result.exit_code == 0
        # Newer task should appear before older task
        newer_pos = result.output.find("Newer task")
        older_pos = result.output.find("Older task")
        assert newer_pos < older_pos

    def test_recent_respects_limit(self, mock_api, mock_token):
        """Recent limits results with -n."""
        mock_api.get_tasks.return_value = iter([[
            make_mock_task(id="1", content="Task 1", created_at="2025-01-03T10:00:00Z"),
            make_mock_task(id="2", content="Task 2", created_at="2025-01-02T10:00:00Z"),
            make_mock_task(id="3", content="Task 3", created_at="2025-01-01T10:00:00Z"),
        ]])

        result = runner.invoke(app, ["recent", "-n", "2"])
        assert result.exit_code == 0
        assert "Task 1" in result.output
        assert "Task 2" in result.output
        assert "Task 3" not in result.output


class TestAutodoist:
    """Tests for autodoist command group."""

    def test_autodoist_health(self):
        mock_client = MagicMock()
        mock_client.health.return_value = {"ok": True, "generated_at": "2026-01-01T00:00:00Z"}

        with patch("todoist_cli.cli.get_autodoist_client", return_value=mock_client):
            result = runner.invoke(app, ["autodoist", "health"])

        assert result.exit_code == 0
        assert "ok" in result.output
        mock_client.health.assert_called_once_with()

    def test_autodoist_state(self):
        mock_client = MagicMock()
        mock_client.state.return_value = {
            "generated_at": "2026-01-01T00:00:00Z",
            "summary": {
                "open_tasks": 10,
                "next_action_count": 2,
                "focus_count": 1,
                "focus_conflicts": 0,
            },
            "labels": {"next_action_label": "next_action", "focus_label": "focus"},
        }

        with patch("todoist_cli.cli.get_autodoist_client", return_value=mock_client):
            result = runner.invoke(app, ["autodoist", "state"])

        assert result.exit_code == 0
        assert "open_tasks: 10" in result.output
        assert "focus: 1" in result.output
        mock_client.state.assert_called_once_with()

    def test_autodoist_tasks(self):
        mock_client = MagicMock()
        mock_client.tasks.return_value = {
            "tasks": [
                {"id": "1", "content": "First", "labels": ["focus"], "updated_at": "2026-01-01T00:00:00Z"},
            ]
        }

        with patch("todoist_cli.cli.get_autodoist_client", return_value=mock_client):
            result = runner.invoke(app, ["autodoist", "tasks", "--label", "focus"])

        assert result.exit_code == 0
        assert "First" in result.output
        mock_client.tasks.assert_called_once_with(label="focus", contains=None)

    def test_autodoist_focus_apply(self):
        mock_client = MagicMock()
        mock_client.reconcile_focus.return_value = {
            "applied": True,
            "winner_task_id": "task-2",
            "removed_count": 1,
        }

        with patch("todoist_cli.cli.get_autodoist_client", return_value=mock_client):
            result = runner.invoke(app, ["autodoist", "focus", "--apply"])

        assert result.exit_code == 0
        assert "winner_task_id: task-2" in result.output
        mock_client.reconcile_focus.assert_called_once_with(apply=True, winner_task_id=None)

    def test_autodoist_set_focus(self):
        mock_client = MagicMock()
        mock_client.reconcile_focus.return_value = {
            "applied": True,
            "winner_task_id": "task-3",
            "removed_count": 2,
        }

        with patch("todoist_cli.cli.get_autodoist_client", return_value=mock_client):
            result = runner.invoke(app, ["autodoist", "set-focus", "task-3"])

        assert result.exit_code == 0
        assert "winner_task_id: task-3" in result.output
        mock_client.reconcile_focus.assert_called_once_with(apply=True, winner_task_id="task-3")

    def test_autodoist_action_set_focus(self):
        mock_client = MagicMock()
        mock_client.task_label_action.return_value = {
            "ok": True,
            "action": "set_focus",
            "task_id": "task-1",
            "message": "Set @focus on task task-1.",
        }

        with patch("todoist_cli.cli.get_autodoist_client", return_value=mock_client):
            result = runner.invoke(app, ["autodoist", "action", "task-1", "set-focus"])

        assert result.exit_code == 0
        assert "Set @focus on task task-1." in result.output
        mock_client.task_label_action.assert_called_once_with(task_id="task-1", action="set_focus")

    def test_autodoist_action_rejects_invalid_action(self):
        mock_client = MagicMock()

        with patch("todoist_cli.cli.get_autodoist_client", return_value=mock_client):
            result = runner.invoke(app, ["autodoist", "action", "task-1", "invalid-action"])

        assert result.exit_code == 1
        assert "Invalid action" in result.output
        mock_client.task_label_action.assert_not_called()


class TestConfigCommand:
    """Tests for config command options."""

    def test_config_set_autodoist_url(self):
        with patch("todoist_cli.cli.get_config", return_value={}), patch("todoist_cli.cli.save_config") as save:
            result = runner.invoke(app, ["config", "--autodoist-url", "https://autodoist.erauner.dev/"])

        assert result.exit_code == 0
        assert "Autodoist URL saved" in result.output
        save.assert_called_once_with({"autodoist_url": "https://autodoist.erauner.dev"})
