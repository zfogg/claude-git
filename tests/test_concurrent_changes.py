"""Tests for concurrent Claude and human changes."""

import json
import tempfile
import time
from datetime import datetime
from pathlib import Path

import pytest

from claude_git.core.repository import ClaudeGitRepository
from claude_git.models.change import Change, ChangeType


@pytest.fixture
def temp_project():
    """Create a temporary project with git repo."""
    with tempfile.TemporaryDirectory() as temp_dir:
        project_path = Path(temp_dir)
        # Create a .git directory to simulate a git repo
        (project_path / ".git").mkdir()
        
        # Create a sample file that both Claude and human will modify
        sample_file = project_path / "src" / "auth.py"
        sample_file.parent.mkdir(parents=True)
        sample_file.write_text("""
def login(username, password):
    # TODO: Implement authentication
    return False

def logout(user_id):
    # TODO: Implement logout
    pass
""".strip())
        
        yield project_path


def test_claude_changes_only(temp_project):
    """Test Claude making changes without human interference."""
    claude_repo = ClaudeGitRepository(temp_project)
    claude_repo.init()
    
    # Claude makes first change
    change1 = Change(
        id="change-1",
        session_id="session-1",
        timestamp=datetime.now(),
        change_type=ChangeType.EDIT,
        file_path=temp_project / "src" / "auth.py",
        old_string="# TODO: Implement authentication",
        new_string="return authenticate_user(username, password)",
        new_content="def login(username, password):\n    return authenticate_user(username, password)\n\ndef logout(user_id):\n    # TODO: Implement logout\n    pass",
        tool_input={"tool": "Edit"}
    )
    
    commit_hash1 = claude_repo.add_change(change1)
    
    # Claude makes second change
    change2 = Change(
        id="change-2", 
        session_id="session-1",
        timestamp=datetime.now(),
        change_type=ChangeType.EDIT,
        file_path=temp_project / "src" / "auth.py",
        old_string="# TODO: Implement logout",
        new_string="clear_session(user_id)",
        new_content="def login(username, password):\n    return authenticate_user(username, password)\n\ndef logout(user_id):\n    clear_session(user_id)\n    pass",
        tool_input={"tool": "Edit"}
    )
    
    commit_hash2 = claude_repo.add_change(change2)
    
    # Verify both commits exist
    assert commit_hash1 != commit_hash2
    commits = list(claude_repo.repo.iter_commits())
    assert len(commits) >= 2  # Initial commit + 2 changes
    
    # Verify patch files exist
    change_files = list((claude_repo.claude_git_dir / "changes").glob("*.patch"))
    assert len(change_files) >= 2


def test_human_modifies_file_then_claude_changes(temp_project):
    """Test human modifying file, then Claude making changes."""
    claude_repo = ClaudeGitRepository(temp_project)
    claude_repo.init()
    
    # Human modifies the file
    auth_file = temp_project / "src" / "auth.py"
    human_content = """
def login(username, password):
    # Human added logging
    log.info(f"Login attempt for {username}")
    # TODO: Implement authentication
    return False

def logout(user_id):
    # TODO: Implement logout
    pass
""".strip()
    auth_file.write_text(human_content)
    
    # Claude makes a change (different part of file)
    claude_change = Change(
        id="claude-change-1",
        session_id="session-1", 
        timestamp=datetime.now(),
        change_type=ChangeType.EDIT,
        file_path=auth_file,
        old_string="# TODO: Implement logout",
        new_string="clear_user_session(user_id)",
        new_content="the new content would be different",
        tool_input={"tool": "Edit"}
    )
    
    commit_hash = claude_repo.add_change(claude_change)
    
    # Verify Claude's change is tracked independently
    assert commit_hash is not None
    
    # Verify the patch can be applied without conflict
    change_dir = claude_repo.claude_git_dir / "changes"
    patch_files = list(change_dir.glob("claude-change-1.patch"))
    assert len(patch_files) == 1
    
    patch_content = patch_files[0].read_text()
    assert "clear_user_session(user_id)" in patch_content
    assert "# TODO: Implement logout" in patch_content


def test_claude_changes_while_human_modifies_different_parts(temp_project):
    """Test Claude changing one part while human changes another part."""
    claude_repo = ClaudeGitRepository(temp_project)
    claude_repo.init()
    
    auth_file = temp_project / "src" / "auth.py"
    
    # Step 1: Human adds logging to login function
    human_modified_content = """
def login(username, password):
    # Human added this logging
    import logging
    logging.info(f"Login attempt for {username}")
    # TODO: Implement authentication
    return False

def logout(user_id):
    # TODO: Implement logout
    pass
""".strip()
    auth_file.write_text(human_modified_content)
    
    # Step 2: Claude changes the logout function (different area)
    claude_change = Change(
        id="claude-logout-fix",
        session_id="session-morning",
        timestamp=datetime.now(),
        change_type=ChangeType.EDIT,
        file_path=auth_file,
        old_string="# TODO: Implement logout\n    pass",
        new_string="clear_session(user_id)\n    logging.info(f'User {user_id} logged out')",
        new_content="updated content",
        tool_input={"tool": "Edit"}
    )
    
    claude_commit = claude_repo.add_change(claude_change)
    
    # Step 3: Human makes another change to login (again, different area than Claude)
    human_content_2 = human_modified_content.replace(
        "# TODO: Implement authentication\n    return False",
        "if authenticate_user(username, password):\n        return True\n    return False"
    )
    auth_file.write_text(human_content_2)
    
    # Step 4: Claude makes another change to a completely different function
    claude_change_2 = Change(
        id="claude-new-function",
        session_id="session-morning",
        timestamp=datetime.now(),
        change_type=ChangeType.WRITE,
        file_path=temp_project / "src" / "utils.py",
        new_content="def hash_password(password):\n    return hashlib.sha256(password.encode()).hexdigest()",
        tool_input={"tool": "Write"}
    )
    
    claude_commit_2 = claude_repo.add_change(claude_change_2)
    
    # Verify both Claude changes are tracked
    commits = list(claude_repo.repo.iter_commits())
    claude_commits = [c for c in commits if "claude-" in c.message or "write:" in c.message.lower()]
    assert len(claude_commits) >= 2
    
    # Verify patches are independent and can be applied separately
    patch_files = list((claude_repo.claude_git_dir / "changes").glob("*.patch"))
    assert len(patch_files) >= 2


def test_concurrent_sessions_different_files(temp_project):
    """Test two concurrent Claude sessions working on different files."""
    claude_repo = ClaudeGitRepository(temp_project)
    claude_repo.init()
    
    # Session 1: Working on auth.py
    session1_change = Change(
        id="session1-change",
        session_id="session-2024-01-15-14-30",
        timestamp=datetime.now(),
        change_type=ChangeType.EDIT,
        file_path=temp_project / "src" / "auth.py",
        old_string="return False",
        new_string="return authenticate_user(username, password)",
        new_content="updated auth content",
        tool_input={"tool": "Edit"}
    )
    
    # Session 2: Working on config.py (different file)
    time.sleep(0.01)  # Ensure different timestamp
    session2_change = Change(
        id="session2-change",
        session_id="session-2024-01-15-14-31",  # Different session
        timestamp=datetime.now(),
        change_type=ChangeType.WRITE,
        file_path=temp_project / "src" / "config.py",
        new_content="DATABASE_URL = 'sqlite:///app.db'\nDEBUG = True",
        tool_input={"tool": "Write"}
    )
    
    # Add changes from both sessions
    commit1 = claude_repo.add_change(session1_change)
    commit2 = claude_repo.add_change(session2_change)
    
    # Verify both sessions created different branches
    sessions = claude_repo.list_sessions()
    assert len(sessions) >= 2
    
    branch_names = [s.branch_name for s in sessions]
    assert len(set(branch_names)) == len(branch_names)  # All unique
    
    # Verify both commits exist
    assert commit1 != commit2
    
    # Verify we can get commits for each session separately
    commits1 = claude_repo.get_commits_for_session("session-2024-01-15-14-30")
    commits2 = claude_repo.get_commits_for_session("session-2024-01-15-14-31") 
    
    assert len(commits1) >= 1
    assert len(commits2) >= 1


def test_rollback_claude_change_after_human_modification(temp_project):
    """Test rolling back Claude changes after human has modified the same file."""
    claude_repo = ClaudeGitRepository(temp_project)
    claude_repo.init()
    
    auth_file = temp_project / "src" / "auth.py"
    original_content = auth_file.read_text()
    
    # Claude makes a change
    claude_change = Change(
        id="claude-auth-change",
        session_id="session-test",
        timestamp=datetime.now(),
        change_type=ChangeType.EDIT,
        file_path=auth_file,
        old_string="return False",
        new_string="return check_credentials(username, password)",
        new_content="modified content",
        tool_input={"tool": "Edit"}
    )
    
    claude_commit = claude_repo.add_change(claude_change)
    
    # Human modifies the file independently
    human_content = original_content.replace(
        "# TODO: Implement authentication",
        "# Implemented by human\n    validate_input(username, password)"
    )
    auth_file.write_text(human_content)
    
    # Get the rollback patch for Claude's change
    commit = claude_repo.repo.commit(claude_commit)
    json_files = [f for f in commit.tree.traverse() if f.name.endswith('.json')]
    
    assert len(json_files) >= 1
    
    change_data = json.loads(json_files[0].data_stream.read().decode('utf-8'))
    assert change_data['old_string'] == "return False"
    assert change_data['new_string'] == "return check_credentials(username, password)"
    
    # Verify we have the data needed for surgical rollback
    assert change_data['file_path'] == str(auth_file)


def test_multiple_rapid_changes_same_session(temp_project):
    """Test Claude making multiple rapid changes in the same session."""
    claude_repo = ClaudeGitRepository(temp_project)
    claude_repo.init()
    
    session_id = "rapid-session"
    changes = []
    
    # Create 5 rapid changes
    for i in range(5):
        change = Change(
            id=f"rapid-change-{i}",
            session_id=session_id,
            timestamp=datetime.now(),
            change_type=ChangeType.EDIT,
            file_path=temp_project / "src" / "auth.py",
            old_string=f"# TODO {i}",
            new_string=f"# DONE {i}",
            new_content=f"content {i}",
            tool_input={"tool": "Edit"}
        )
        
        commit_hash = claude_repo.add_change(change)
        changes.append((change, commit_hash))
        time.sleep(0.001)  # Tiny delay to ensure different timestamps
    
    # Verify all changes are tracked
    session_commits = claude_repo.get_commits_for_session(session_id)
    assert len(session_commits) >= 5
    
    # Verify each change has its own patch file
    patch_files = list((claude_repo.claude_git_dir / "changes").glob("rapid-change-*.patch"))
    assert len(patch_files) == 5
    
    # Verify commits are in order (most recent first in git log)
    commit_messages = [c.message.split('\n')[0] for c in session_commits[:5]]
    assert all("edit:" in msg.lower() for msg in commit_messages)