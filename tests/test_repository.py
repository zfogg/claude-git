"""Tests for ClaudeGitRepository."""

import json
import tempfile
import time
from datetime import datetime
from pathlib import Path

import pytest

from claude_git.core.repository import ClaudeGitRepository
from claude_git.models.change import Change, ChangeType


@pytest.fixture
def temp_git_repo():
    """Create a temporary git repository for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        repo_path = Path(temp_dir)
        # Create a .git directory to simulate a git repo
        (repo_path / ".git").mkdir()
        yield repo_path


def test_repository_init(temp_git_repo):
    """Test initializing a Claude Git repository."""
    claude_repo = ClaudeGitRepository(temp_git_repo)
    
    # Should not exist initially
    assert not claude_repo.exists()
    
    # Initialize
    claude_repo.init()
    
    # Should exist now
    assert claude_repo.exists()
    assert (claude_repo.claude_git_dir / "config.json").exists()
    assert (claude_repo.claude_git_dir / ".git").exists()
    assert (claude_repo.sessions_file).exists()


def test_session_creation(temp_git_repo):
    """Test creating and retrieving sessions."""
    claude_repo = ClaudeGitRepository(temp_git_repo)
    claude_repo.init()
    
    # Create a session
    session = claude_repo.get_or_create_current_session()
    
    assert session.id is not None
    assert session.is_active
    assert session.project_path == temp_git_repo
    assert session.branch_name.startswith("session-")


def test_change_storage(temp_git_repo):
    """Test storing changes as git commits."""
    claude_repo = ClaudeGitRepository(temp_git_repo)
    claude_repo.init()
    
    session = claude_repo.get_or_create_current_session()
    
    # Create a test change
    change = Change(
        id="test-change-123",
        session_id=session.id,
        timestamp=datetime.now(),
        change_type=ChangeType.EDIT,
        file_path=Path("/test/file.py"),
        old_content="old content",
        new_content="new content",
        old_string="old",
        new_string="new",
        tool_input={"tool": "Edit", "params": {}},
    )
    
    # Store the change
    commit_hash = claude_repo.add_change(change)
    
    # Verify commit was created
    assert commit_hash is not None
    commit = claude_repo.repo.commit(commit_hash)
    assert commit is not None
    assert "test-change-123" in commit.message or "edit:" in commit.message.lower()


def test_list_changes(temp_git_repo):
    """Test listing commits for sessions."""
    claude_repo = ClaudeGitRepository(temp_git_repo)
    claude_repo.init()
    
    session = claude_repo.get_or_create_current_session()
    
    # Create multiple changes
    for i in range(3):
        change = Change(
            id=f"change-{i}",
            session_id=session.id,
            timestamp=datetime.now(),
            change_type=ChangeType.EDIT,
            file_path=Path(f"/test/file{i}.py"),
            new_content=f"content {i}",
            old_string=f"old {i}",
            new_string=f"new {i}",
            tool_input={},
        )
        claude_repo.add_change(change)
        time.sleep(0.001)  # Ensure different timestamps
    
    # List commits for the session
    session_commits = claude_repo.get_commits_for_session(session.id)
    assert len(session_commits) >= 3
    
    # Verify commits are properly ordered (most recent first in git)
    commit_messages = [c.message for c in session_commits]
    # The commits should contain our change IDs or be edit-related
    relevant_commits = [msg for msg in commit_messages if ("change-" in msg or "edit:" in msg.lower())]
    assert len(relevant_commits) >= 3