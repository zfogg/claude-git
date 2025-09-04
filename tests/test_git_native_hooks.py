"""Tests for git-native hook handlers."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from git import Repo

from claude_git.hooks.git_native_handler import (
    extract_file_path_from_tool_data,
    extract_latest_tool_from_transcript,
    extract_thinking_text_from_transcript,
    find_git_native_repository,
    handle_pre_tool_use_hook,
    handle_stop_hook,
    handle_tool_completion_hook,
    main,
    parse_hook_input,
)


@pytest.fixture
def temp_transcript_file():
    """Create a temporary transcript file with test data."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        # Write sample transcript entries
        transcript_data = [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "text", "text": "Please modify the main function"}
                ],
            },
            {
                "type": "message",
                "role": "assistant",
                "thinking": True,
                "content": [
                    {
                        "type": "text",
                        "text": "I need to analyze the current main function implementation",
                    }
                ],
            },
            {
                "type": "message",
                "role": "assistant",
                "thinking": True,
                "content": [
                    {
                        "type": "text",
                        "text": "The main function should be updated to handle arguments properly",
                    }
                ],
            },
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I'll modify the main function now."},
                    {
                        "type": "tool_use",
                        "name": "Edit",
                        "input": {
                            "file_path": "/test/main.py",
                            "old_string": "def main():",
                            "new_string": "def main(args):",
                        },
                    },
                ],
            },
        ]

        for entry in transcript_data:
            f.write(json.dumps(entry) + "\n")

        temp_path = Path(f.name)

    yield temp_path

    # Cleanup
    if temp_path.exists():
        temp_path.unlink()


@pytest.fixture
def temp_git_project():
    """Create a temporary git project for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        project_path = Path(temp_dir)

        # Initialize git repo
        main_repo = Repo.init(project_path)
        with main_repo.config_writer() as config:
            config.set_value("user", "name", "Test User")
            config.set_value("user", "email", "test@example.com")

        # Create test file
        (project_path / "main.py").write_text("def main():\n    pass\n")
        main_repo.index.add(["main.py"])
        main_repo.index.commit("Initial commit")

        yield project_path


def test_extract_thinking_text_from_transcript(temp_transcript_file):
    """Test extracting thinking text from transcript file."""
    thinking_text = extract_thinking_text_from_transcript(str(temp_transcript_file))

    assert thinking_text is not None
    assert "I need to analyze the current main function implementation" in thinking_text
    assert (
        "The main function should be updated to handle arguments properly"
        in thinking_text
    )

    # Should combine with proper formatting
    lines = thinking_text.split("\n\n")
    assert len(lines) == 2


def test_extract_thinking_text_empty_file():
    """Test extracting thinking text from empty or non-existent file."""
    # Non-existent file
    thinking_text = extract_thinking_text_from_transcript("/non/existent/file.jsonl")
    assert thinking_text is None

    # Empty file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        temp_path = Path(f.name)

    try:
        thinking_text = extract_thinking_text_from_transcript(str(temp_path))
        assert thinking_text is None
    finally:
        temp_path.unlink()


def test_extract_thinking_text_no_thinking_messages():
    """Test extracting from transcript with no thinking messages."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        # Write non-thinking entries
        entries = [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "text", "text": "Hello"}],
            },
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "Hi there"}],
            },
        ]

        for entry in entries:
            f.write(json.dumps(entry) + "\n")

        temp_path = Path(f.name)

    try:
        thinking_text = extract_thinking_text_from_transcript(str(temp_path))
        assert thinking_text is None
    finally:
        temp_path.unlink()


def test_extract_file_path_from_tool_data():
    """Test extracting file paths from tool data."""
    # Test Edit tool
    tool_data = {
        "name": "Edit",
        "parameters": {
            "file_path": "/test/main.py",
            "old_string": "old",
            "new_string": "new",
        },
    }
    file_path = extract_file_path_from_tool_data(tool_data)
    assert file_path == "/test/main.py"

    # Test Write tool
    tool_data = {
        "name": "Write",
        "parameters": {"file_path": "/test/output.txt", "content": "Hello world"},
    }
    file_path = extract_file_path_from_tool_data(tool_data)
    assert file_path == "/test/output.txt"

    # Test NotebookEdit tool
    tool_data = {
        "name": "NotebookEdit",
        "parameters": {"notebook_path": "/test/notebook.ipynb", "cell_number": 0},
    }
    file_path = extract_file_path_from_tool_data(tool_data)
    assert file_path == "/test/notebook.ipynb"

    # Test MultiEdit tool
    tool_data = {
        "name": "MultiEdit",
        "parameters": {"file_path": "/test/multi.py", "edits": []},
    }
    file_path = extract_file_path_from_tool_data(tool_data)
    assert file_path == "/test/multi.py"

    # Test empty/invalid tool data
    assert extract_file_path_from_tool_data({}) is None
    assert extract_file_path_from_tool_data({"parameters": {}}) is None


def test_extract_latest_tool_from_transcript(temp_transcript_file):
    """Test extracting latest tool call from transcript."""
    tool_data = extract_latest_tool_from_transcript(str(temp_transcript_file))

    assert tool_data is not None
    assert tool_data["name"] == "Edit"
    assert tool_data["parameters"]["file_path"] == "/test/main.py"
    assert tool_data["parameters"]["old_string"] == "def main():"
    assert tool_data["parameters"]["new_string"] == "def main(args):"


def test_extract_latest_tool_no_tools():
    """Test extracting from transcript with no tool calls."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        entries = [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "text", "text": "Hello"}],
            },
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "Hi"}],
            },
        ]

        for entry in entries:
            f.write(json.dumps(entry) + "\n")

        temp_path = Path(f.name)

    try:
        tool_data = extract_latest_tool_from_transcript(str(temp_path))
        assert tool_data is None
    finally:
        temp_path.unlink()


def test_find_git_native_repository(temp_git_project):
    """Test finding git-native repository."""
    # Should return None initially (no claude-git initialized)
    git_repo = find_git_native_repository(temp_git_project)

    # Should initialize and return repository
    assert git_repo is not None
    assert git_repo.exists()
    assert git_repo.project_root.resolve() == temp_git_project.resolve()


def test_find_git_native_repository_no_git():
    """Test finding git-native repository in non-git directory."""
    with tempfile.TemporaryDirectory() as temp_dir:
        non_git_path = Path(temp_dir)
        git_repo = find_git_native_repository(non_git_path)
        assert git_repo is None


@patch("claude_git.hooks.git_native_handler.find_git_native_repository")
def test_handle_pre_tool_use_hook(mock_find_repo):
    """Test PreToolUse hook handler."""
    # Mock git repository
    mock_repo = MagicMock()
    mock_repo._session_active = False
    mock_find_repo.return_value = mock_repo

    with tempfile.NamedTemporaryFile() as debug_log:
        hook_data = {"session_id": "test-session-123", "tool": {"name": "Edit"}}

        handle_pre_tool_use_hook(hook_data, Path(debug_log.name))

        # Verify session was started
        mock_repo.session_start.assert_called_once_with("test-session-123")


@patch("claude_git.hooks.git_native_handler.find_git_native_repository")
def test_handle_pre_tool_use_hook_no_repo(mock_find_repo):
    """Test PreToolUse hook when no repository found."""
    mock_find_repo.return_value = None

    with tempfile.NamedTemporaryFile() as debug_log:
        hook_data = {"session_id": "test-session"}

        # Should handle gracefully without crashing
        handle_pre_tool_use_hook(hook_data, Path(debug_log.name))


@patch("claude_git.hooks.git_native_handler.find_git_native_repository")
@patch("claude_git.hooks.git_native_handler.extract_thinking_text_from_transcript")
def test_handle_stop_hook(mock_extract_thinking, mock_find_repo, temp_transcript_file):
    """Test Stop hook handler."""
    # Mock repository
    mock_repo = MagicMock()
    mock_repo._session_active = True
    mock_repo.session_end.return_value = "abc12345"
    mock_find_repo.return_value = mock_repo

    # Mock thinking text extraction
    mock_extract_thinking.return_value = "Extracted thinking text"

    with tempfile.NamedTemporaryFile() as debug_log:
        hook_data = {"transcript_path": str(temp_transcript_file)}

        handle_stop_hook(hook_data, Path(debug_log.name))

        # Verify thinking text was extracted
        mock_extract_thinking.assert_called_once_with(str(temp_transcript_file))

        # Verify session was ended with thinking text
        mock_repo.session_end.assert_called_once_with("Extracted thinking text")


@patch("claude_git.hooks.git_native_handler.find_git_native_repository")
def test_handle_stop_hook_no_active_session(mock_find_repo):
    """Test Stop hook when no active session."""
    mock_repo = MagicMock()
    mock_repo._session_active = False
    mock_find_repo.return_value = mock_repo

    with tempfile.NamedTemporaryFile() as debug_log:
        hook_data = {"transcript_path": "/dummy/path"}

        handle_stop_hook(hook_data, Path(debug_log.name))

        # Should not call session_end
        mock_repo.session_end.assert_not_called()


@patch("claude_git.hooks.git_native_handler.find_git_native_repository")
def test_handle_tool_completion_hook(mock_find_repo):
    """Test tool completion hook handler."""
    mock_repo = MagicMock()
    mock_find_repo.return_value = mock_repo

    with tempfile.NamedTemporaryFile() as debug_log:
        hook_data = {
            "tool": {
                "name": "Edit",
                "parameters": {
                    "file_path": "/test/main.py",
                    "old_string": "old",
                    "new_string": "new",
                },
            }
        }

        handle_tool_completion_hook(hook_data, Path(debug_log.name))

        # Verify change was accumulated
        mock_repo.accumulate_change.assert_called_once_with(
            "/test/main.py", "Edit", hook_data["tool"]
        )


@patch("claude_git.hooks.git_native_handler.find_git_native_repository")
@patch("claude_git.hooks.git_native_handler.extract_latest_tool_from_transcript")
def test_handle_tool_completion_hook_from_transcript(
    mock_extract_tool, mock_find_repo, temp_transcript_file
):
    """Test tool completion hook extracting tool data from transcript."""
    mock_repo = MagicMock()
    mock_find_repo.return_value = mock_repo

    # Mock tool extraction
    tool_data = {"name": "Edit", "parameters": {"file_path": "/test/main.py"}}
    mock_extract_tool.return_value = tool_data

    with tempfile.NamedTemporaryFile() as debug_log:
        hook_data = {"transcript_path": str(temp_transcript_file)}

        handle_tool_completion_hook(hook_data, Path(debug_log.name))

        # Verify tool was extracted from transcript
        mock_extract_tool.assert_called_once_with(str(temp_transcript_file))

        # Verify change was accumulated
        mock_repo.accumulate_change.assert_called_once_with(
            "/test/main.py", "Edit", tool_data
        )


def test_parse_hook_input():
    """Test parsing hook input JSON."""
    # Valid JSON
    test_input = '{"session_id": "test", "tool": {"name": "Edit"}}'
    result = parse_hook_input()

    # Mock stdin
    with patch("sys.stdin.read", return_value=test_input):
        result = parse_hook_input()
        expected = {"session_id": "test", "tool": {"name": "Edit"}}
        assert result == expected

    # Invalid JSON
    with patch("sys.stdin.read", return_value="invalid json"):
        result = parse_hook_input()
        assert result == {}

    # Empty input
    with patch("sys.stdin.read", return_value=""):
        result = parse_hook_input()
        assert result == {}


@patch("claude_git.hooks.git_native_handler.handle_pre_tool_use_hook")
@patch("claude_git.hooks.git_native_handler.parse_hook_input")
def test_main_pre_tool_use_hook(mock_parse_input, mock_handle_pre):
    """Test main function routing to PreToolUse handler."""
    mock_parse_input.return_value = {
        "hook_type": "PreToolUse",
        "session_id": "test-session",
    }

    main()

    # Verify correct handler was called
    mock_handle_pre.assert_called_once()


@patch("claude_git.hooks.git_native_handler.handle_stop_hook")
@patch("claude_git.hooks.git_native_handler.parse_hook_input")
def test_main_stop_hook(mock_parse_input, mock_handle_stop):
    """Test main function routing to Stop handler."""
    mock_parse_input.return_value = {
        "hook_type": "Stop",
        "transcript_path": "/test/transcript.jsonl",
    }

    main()

    # Verify correct handler was called
    mock_handle_stop.assert_called_once()


@patch("claude_git.hooks.git_native_handler.handle_tool_completion_hook")
@patch("claude_git.hooks.git_native_handler.parse_hook_input")
def test_main_tool_completion_hook(mock_parse_input, mock_handle_tool):
    """Test main function routing to tool completion handler."""
    mock_parse_input.return_value = {
        "hook_type": "ToolCompletion",
        "tool": {"name": "Edit"},
    }

    main()

    # Verify correct handler was called
    mock_handle_tool.assert_called_once()


@patch("claude_git.hooks.git_native_handler.handle_tool_completion_hook")
@patch("claude_git.hooks.git_native_handler.parse_hook_input")
def test_main_generic_tool_hook(mock_parse_input, mock_handle_tool):
    """Test main function routing to tool completion handler for generic tool data."""
    mock_parse_input.return_value = {
        "tool": {"name": "Edit"},  # No explicit hook_type, but has tool data
        "session_id": "test",
    }

    main()

    # Should route to tool completion handler
    mock_handle_tool.assert_called_once()


@patch("claude_git.hooks.git_native_handler.parse_hook_input")
def test_main_unknown_hook_type(mock_parse_input):
    """Test main function handling unknown hook types."""
    mock_parse_input.return_value = {"hook_type": "UnknownHookType"}

    # Should handle gracefully without crashing
    main()


@patch("claude_git.hooks.git_native_handler.parse_hook_input")
def test_main_no_data(mock_parse_input):
    """Test main function with no hook data."""
    mock_parse_input.return_value = {}

    # Should handle gracefully without crashing
    main()
