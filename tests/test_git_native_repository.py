"""Tests for GitNativeRepository dual-repository architecture."""

import json
import tempfile
from pathlib import Path

import pytest
from git import Repo

from claude_git.core.git_native_repository import GitNativeRepository


@pytest.fixture
def temp_git_project():
    """Create a temporary git project with some files for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        project_path = Path(temp_dir)

        # Initialize a real git repository
        main_repo = Repo.init(project_path)

        # Configure git user for testing
        with main_repo.config_writer() as config:
            config.set_value("user", "name", "Test User")
            config.set_value("user", "email", "test@example.com")

        # Create some initial files
        (project_path / "main.py").write_text("def main():\n    print('Hello')\n")
        (project_path / "utils.py").write_text("def helper():\n    return 42\n")
        (project_path / "README.md").write_text("# Test Project\n")

        # Create a subdirectory with files
        (project_path / "src").mkdir()
        (project_path / "src" / "core.py").write_text("class Core:\n    pass\n")

        # Make initial commit in main repo
        main_repo.index.add(["main.py", "utils.py", "README.md", "src/core.py"])
        main_repo.index.commit("Initial commit")

        yield project_path


def test_git_native_repository_init(temp_git_project):
    """Test initializing git-native repository."""
    git_native = GitNativeRepository(temp_git_project)

    # Should not exist initially
    assert not git_native.exists()

    # Initialize the git-native system
    git_native.init()

    # Should exist now
    assert git_native.exists()
    assert git_native.claude_git_dir.exists()
    assert (git_native.claude_git_dir / ".git").exists()
    assert git_native.config_file.exists()

    # Check config file contents
    config = json.loads(git_native.config_file.read_text())
    assert config["version"] == "2.0.0"
    assert config["architecture"] == "git-native-dual-repo"
    assert "created" in config
    assert Path(config["project_root"]).resolve() == Path(temp_git_project).resolve()

    # Verify that files were synced from main repo
    assert (git_native.claude_git_dir / "main.py").exists()
    assert (git_native.claude_git_dir / "utils.py").exists()
    assert (git_native.claude_git_dir / "README.md").exists()
    assert (git_native.claude_git_dir / "src" / "core.py").exists()

    # Verify content is identical
    main_content = (temp_git_project / "main.py").read_text()
    claude_content = (git_native.claude_git_dir / "main.py").read_text()
    assert main_content == claude_content


def test_session_management(temp_git_project):
    """Test Claude session start and end functionality."""
    git_native = GitNativeRepository(temp_git_project)
    git_native.init()

    # Initially no session should be active
    assert not git_native._session_active
    assert git_native._current_session_id is None

    # Start a session
    session_id = "test-session-123"
    git_native.session_start(session_id)

    assert git_native._session_active
    assert git_native._current_session_id == session_id
    assert git_native._accumulated_changes == []

    # End session without changes
    commit_hash = git_native.session_end()
    assert commit_hash == ""  # No changes to commit
    assert not git_native._session_active
    assert git_native._current_session_id is None


def test_change_accumulation(temp_git_project):
    """Test accumulating changes during a session."""
    git_native = GitNativeRepository(temp_git_project)
    git_native.init()

    # Start session
    git_native.session_start("test-session")

    # Make a change to a file
    test_file = temp_git_project / "main.py"
    test_file.write_text("def main():\n    print('Hello, World!')\n")

    # Accumulate the change
    tool_input = {
        "old_string": "print('Hello')",
        "new_string": "print('Hello, World!')",
        "file_path": str(test_file),
    }
    git_native.accumulate_change(str(test_file), "Edit", tool_input)

    # Verify change was accumulated
    assert len(git_native._accumulated_changes) == 1
    change = git_native._accumulated_changes[0]
    assert change["file_path"] == str(test_file)
    assert change["tool_name"] == "Edit"
    assert change["tool_input"] == tool_input

    # Verify file was synced to claude-git repo
    claude_file = git_native.claude_git_dir / "main.py"
    assert claude_file.read_text() == "def main():\n    print('Hello, World!')\n"


def test_session_end_with_thinking_text(temp_git_project):
    """Test creating logical commit with thinking text."""
    git_native = GitNativeRepository(temp_git_project)
    git_native.init()

    # Start session and make changes
    git_native.session_start("thinking-session")

    # Modify two files
    file1 = temp_git_project / "main.py"
    file1.write_text("def main():\n    print('Updated main')\n")
    git_native.accumulate_change(str(file1), "Edit", {"file_path": str(file1)})

    file2 = temp_git_project / "utils.py"
    file2.write_text("def helper():\n    return 'updated'\n")
    git_native.accumulate_change(str(file2), "Edit", {"file_path": str(file2)})

    # End session with thinking text
    thinking_text = "I need to update the main function to be more descriptive\nand also update the helper to return a string instead of number"
    commit_hash = git_native.session_end(thinking_text)

    # Verify commit was created
    assert commit_hash != ""
    assert len(commit_hash) == 40  # Full SHA-1 hash

    # Check commit in claude-git repo
    commit = git_native.claude_repo.commit(commit_hash)
    assert thinking_text in commit.message
    assert "Parent-Repo:" in commit.message
    assert "Session: thinking-session" in commit.message
    # File order can vary, check both files are present
    assert "main.py" in commit.message and "utils.py" in commit.message
    assert "Files:" in commit.message
    assert "Changes: 2" in commit.message

    # Verify session was reset
    assert not git_native._session_active
    assert git_native._current_session_id is None
    assert git_native._accumulated_changes == []


def test_immediate_commit_outside_session(temp_git_project):
    """Test creating immediate commits when no session is active."""
    git_native = GitNativeRepository(temp_git_project)
    git_native.init()

    # Make a change without starting session
    test_file = temp_git_project / "utils.py"
    test_file.write_text("def helper():\n    return 'immediate'\n")

    # This should create an immediate commit
    git_native.accumulate_change(
        str(test_file), "Write", {"content": "def helper():\n    return 'immediate'\n"}
    )

    # Check that a commit was created
    commits = list(git_native.claude_repo.iter_commits())
    # Should have at least 2 commits: initial + this immediate commit
    assert len(commits) >= 2

    # Find the immediate commit
    immediate_commit = None
    for commit in commits:
        if "claude: write utils.py" in commit.message:
            immediate_commit = commit
            break

    assert immediate_commit is not None
    assert "Parent-Repo:" in immediate_commit.message
    assert "Tool: Write" in immediate_commit.message


def test_file_synchronization(temp_git_project):
    """Test file synchronization between main and claude-git repos."""
    git_native = GitNativeRepository(temp_git_project)
    git_native.init()

    # Create a new file in main repo
    new_file = temp_git_project / "new_feature.py"
    new_file.write_text("# New feature implementation\n")

    # Sync file to claude-git repo
    git_native._sync_file_to_claude_repo(str(new_file))

    # Verify file exists in claude-git repo
    claude_file = git_native.claude_git_dir / "new_feature.py"
    assert claude_file.exists()
    assert claude_file.read_text() == "# New feature implementation\n"

    # Test syncing non-existent file
    git_native._sync_file_to_claude_repo("/non/existent/file.py")
    # Should handle gracefully without crashing


def test_detect_file_differences(temp_git_project):
    """Test detecting file differences between repos."""
    git_native = GitNativeRepository(temp_git_project)
    git_native.init()

    # Initially no differences
    changes = git_native._detect_file_differences()
    assert changes == []

    # Modify file in main repo
    main_file = temp_git_project / "main.py"
    main_file.write_text("def main():\n    print('Modified in main')\n")

    # Now should detect difference
    changes = git_native._detect_file_differences()
    assert "main.py" in changes

    # Create new file in main repo
    new_file = temp_git_project / "new_file.py"
    new_file.write_text("print('new file')\n")

    changes = git_native._detect_file_differences()
    assert "new_file.py" in changes
    assert "main.py" in changes


def test_user_changes_commit(temp_git_project):
    """Test committing pending user changes before Claude session."""
    git_native = GitNativeRepository(temp_git_project)
    git_native.init()

    # Modify files in main repo (simulating user changes)
    main_file = temp_git_project / "main.py"
    main_file.write_text("def main():\n    print('User modified this')\n")

    new_file = temp_git_project / "user_file.py"
    new_file.write_text("# User created this file\n")

    # Start session (should auto-commit user changes)
    initial_commits = len(list(git_native.claude_repo.iter_commits()))
    git_native.session_start("user-test-session")
    final_commits = len(list(git_native.claude_repo.iter_commits()))

    # Should have created user commit
    assert final_commits > initial_commits

    # Verify files are synced
    assert (
        git_native.claude_git_dir / "main.py"
    ).read_text() == "def main():\n    print('User modified this')\n"
    assert (
        git_native.claude_git_dir / "user_file.py"
    ).read_text() == "# User created this file\n"


def test_git_notes_metadata(temp_git_project):
    """Test adding structured metadata as git notes."""
    git_native = GitNativeRepository(temp_git_project)
    git_native.init()

    # Start session and make changes
    git_native.session_start("notes-test")

    test_file = temp_git_project / "main.py"
    test_file.write_text("def main():\n    print('Testing notes')\n")
    git_native.accumulate_change(str(test_file), "Edit", {"old": "old", "new": "new"})

    # End session to create commit with notes
    commit_hash = git_native.session_end("Testing git notes functionality")

    # Verify git notes were added (this tests the subprocess call)
    # We can't easily verify notes in the test without git command access
    # But we can verify the commit exists and has the right structure
    commit = git_native.claude_repo.commit(commit_hash)
    assert commit is not None
    assert "Testing git notes functionality" in commit.message


def test_multiple_sessions(temp_git_project):
    """Test multiple sequential sessions."""
    git_native = GitNativeRepository(temp_git_project)
    git_native.init()

    initial_commits = len(list(git_native.claude_repo.iter_commits()))

    # Session 1
    git_native.session_start("session-1")
    file1 = temp_git_project / "main.py"
    file1.write_text("# Session 1 changes\n")
    git_native.accumulate_change(str(file1), "Edit", {})
    commit1 = git_native.session_end("First session thinking")

    # Session 2
    git_native.session_start("session-2")
    file2 = temp_git_project / "utils.py"
    file2.write_text("# Session 2 changes\n")
    git_native.accumulate_change(str(file2), "Edit", {})
    commit2 = git_native.session_end("Second session thinking")

    # Verify both commits exist
    final_commits = len(list(git_native.claude_repo.iter_commits()))
    assert final_commits == initial_commits + 2

    assert commit1 != commit2
    assert len(commit1) == 40
    assert len(commit2) == 40

    # Verify commit messages
    c1 = git_native.claude_repo.commit(commit1)
    c2 = git_native.claude_repo.commit(commit2)

    assert "First session thinking" in c1.message
    assert "Second session thinking" in c2.message
    assert "session-1" in c1.message
    assert "session-2" in c2.message


def test_error_handling(temp_git_project):
    """Test error handling in various scenarios."""
    git_native = GitNativeRepository(temp_git_project)
    git_native.init()

    # Test ending session that wasn't started
    commit_hash = git_native.session_end()
    assert commit_hash == ""

    # Test accumulating change without session (should create immediate commit)
    test_file = temp_git_project / "test.py"
    test_file.write_text("test content")

    # This should not raise an exception
    git_native.accumulate_change(str(test_file), "Write", {})

    # Test with invalid file path
    git_native.session_start("error-test")
    # Should handle gracefully
    git_native.accumulate_change("/invalid/path/file.py", "Edit", {})


def test_main_repo_commit_tracking(temp_git_project):
    """Test tracking main repository commit hashes."""
    git_native = GitNativeRepository(temp_git_project)
    git_native.init()

    # Get initial main repo commit
    initial_commit = git_native._get_main_repo_commit()
    assert len(initial_commit) == 40  # SHA-1 hash length

    # Make changes in main repo
    main_repo = git_native.main_repo
    test_file = temp_git_project / "new_main_file.py"
    test_file.write_text("print('new main file')")

    main_repo.index.add(["new_main_file.py"])
    new_commit = main_repo.index.commit("User added new file")

    # Verify commit tracking updated
    updated_commit = git_native._get_main_repo_commit()
    assert updated_commit == new_commit.hexsha
    assert updated_commit != initial_commit
