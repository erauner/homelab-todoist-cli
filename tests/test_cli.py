"""Tests for CLI commands."""

from unittest.mock import MagicMock, patch
from typer.testing import CliRunner
import pytest

from todoist_cli.cli import app


runner = CliRunner()


def make_mock_task(
    id: str = "123",
    content: str = "Test task",
    description: str = "",
    priority: int = 1,
    project_id: str = "proj1",
    labels: list = None,
    due = None,
    url: str = "https://todoist.com/task/123",
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
    task.url = url
    return task


def make_mock_project(id: str = "proj1", name: str = "Inbox", color: str = "grey"):
    """Create a mock project object."""
    project = MagicMock()
    project.id = id
    project.name = name
    project.color = color
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


class TestComment:
    """Tests for comment command."""

    def test_add_comment(self, mock_api, mock_token):
        """Comment adds comment to task."""
        mock_api.add_comment.return_value = make_mock_comment(id="c1", content="My comment")

        result = runner.invoke(app, ["comment", "123", "My comment"])
        assert result.exit_code == 0
        assert "Added comment" in result.output
        mock_api.add_comment.assert_called_once_with(task_id="123", content="My comment")


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


class TestClose:
    """Tests for close command."""

    def test_close_task(self, mock_api, mock_token):
        """Close completes task."""
        result = runner.invoke(app, ["close", "123"])
        assert result.exit_code == 0
        assert "Completed task" in result.output
        mock_api.close_task.assert_called_once_with("123")


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
