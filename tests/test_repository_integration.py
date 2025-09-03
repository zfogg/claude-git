"""Integration tests for Claude Git repository functionality."""

import json
import tempfile
import time
from datetime import datetime
from pathlib import Path

import pytest

from claude_git.core.repository import ClaudeGitRepository
from claude_git.models.change import Change, ChangeType


@pytest.fixture 
def sample_project():
    """Create a sample project structure."""
    with tempfile.TemporaryDirectory() as temp_dir:
        project_path = Path(temp_dir)
        (project_path / ".git").mkdir()
        
        # Create realistic project structure
        src_dir = project_path / "src"
        src_dir.mkdir()
        
        (src_dir / "__init__.py").write_text("")
        (src_dir / "main.py").write_text("""
def main():
    print("Hello World")

if __name__ == "__main__":
    main()
""".strip())
        
        (src_dir / "utils.py").write_text("""
def helper_function():
    pass
""".strip())
        
        yield project_path


def test_git_command_passthrough(sample_project):
    """Test that git commands work correctly on Claude repo."""
    claude_repo = ClaudeGitRepository(sample_project)
    claude_repo.init()
    
    # Test basic git status
    result = claude_repo.run_git_command(["status"])
    assert "working tree clean" in result.lower() or "nothing to commit" in result.lower()
    
    # Test git log
    result = claude_repo.run_git_command(["log", "--oneline"])
    assert "Initial Claude Git repository" in result
    
    # Test git branch
    result = claude_repo.run_git_command(["branch"])
    assert "master" in result or "main" in result


def test_session_branch_creation(sample_project):
    """Test that sessions create proper git branches."""
    claude_repo = ClaudeGitRepository(sample_project)
    claude_repo.init()
    
    # Create first session
    session1 = claude_repo.get_or_create_current_session()
    assert session1.branch_name.startswith("session-")
    
    # Verify branch exists in git
    branches = claude_repo.run_git_command(["branch"])
    assert session1.branch_name in branches
    
    # Simulate concurrent session (different minute)
    import time
    time.sleep(0.1)  # Ensure different timestamp
    
    # Force create another session by marking first as ended
    sessions = claude_repo._load_sessions()
    for s in sessions:
        if s.id == session1.id:
            s.end_time = datetime.now()
    claude_repo._save_sessions(sessions)
    
    session2 = claude_repo.get_or_create_current_session()
    assert session2.id != session1.id
    assert session2.branch_name != session1.branch_name
    
    # Verify both branches exist
    branches = claude_repo.run_git_command(["branch"])
    assert session1.branch_name in branches
    assert session2.branch_name in branches


def test_change_to_commit_workflow(sample_project):
    """Test complete workflow from change to git commit."""
    claude_repo = ClaudeGitRepository(sample_project)
    claude_repo.init()
    
    session = claude_repo.get_or_create_current_session()
    
    # Create a realistic edit change
    change = Change(
        id="test-edit-123",
        session_id=session.id,
        timestamp=datetime.now(),
        change_type=ChangeType.EDIT,
        file_path=sample_project / "src" / "main.py",
        old_string='print("Hello World")',
        new_string='print("Hello Claude Git!")',
        new_content="""def main():
    print("Hello Claude Git!")

if __name__ == "__main__":
    main()""",
        tool_input={"tool": "Edit", "file_path": str(sample_project / "src" / "main.py")}
    )
    
    commit_hash = claude_repo.add_change(change)
    
    # Verify commit exists
    commit = claude_repo.repo.commit(commit_hash)
    assert commit is not None
    assert "edit:" in commit.message.lower()
    assert "main.py" in commit.message
    
    # Verify commit contains the right files
    files_in_commit = [item.name for item in commit.tree.traverse()]
    assert any(f.endswith(".json") for f in files_in_commit)
    assert any(f.endswith(".patch") for f in files_in_commit)
    
    # Verify patch content
    patch_files = [f for f in commit.tree.traverse() if f.name.endswith('.patch')]
    patch_content = patch_files[0].data_stream.read().decode('utf-8')
    assert 'Hello World' in patch_content
    assert 'Hello Claude Git!' in patch_content


def test_patch_file_generation(sample_project):
    """Test that patch files are generated correctly."""
    claude_repo = ClaudeGitRepository(sample_project)
    claude_repo.init()
    
    session = claude_repo.get_or_create_current_session()
    
    # Test EDIT change
    edit_change = Change(
        id="edit-test",
        session_id=session.id,
        timestamp=datetime.now(),
        change_type=ChangeType.EDIT,
        file_path=sample_project / "src" / "utils.py",
        old_string="pass",
        new_string="return 42",
        new_content="def helper_function():\n    return 42",
        tool_input={"tool": "Edit"}
    )
    
    claude_repo.add_change(edit_change)
    
    # Test WRITE change (new file)
    write_change = Change(
        id="write-test",
        session_id=session.id,
        timestamp=datetime.now(),
        change_type=ChangeType.WRITE,
        file_path=sample_project / "src" / "new_module.py",
        new_content="# New module\ndef new_function():\n    return 'created by claude'",
        tool_input={"tool": "Write"}
    )
    
    claude_repo.add_change(write_change)
    
    # Verify patch files exist and have correct content
    changes_dir = claude_repo.claude_git_dir / "changes"
    
    edit_patch = changes_dir / "edit-test.patch"
    assert edit_patch.exists()
    patch_content = edit_patch.read_text()
    assert "-pass" in patch_content
    assert "+return 42" in patch_content
    
    write_patch = changes_dir / "write-test.patch"
    assert write_patch.exists()
    patch_content = write_patch.read_text()
    assert "new_module.py" in patch_content
    assert "+# New module" in patch_content


def test_git_history_and_analysis(sample_project):
    """Test that git history can be used for analysis."""
    claude_repo = ClaudeGitRepository(sample_project)
    claude_repo.init()
    
    session = claude_repo.get_or_create_current_session()
    
    # Create multiple changes to build history
    changes_data = [
        ("fix typo", "hello", "Hello"),
        ("add logging", "print", "logging.info"),
        ("improve error handling", "pass", "raise NotImplementedError"),
    ]
    
    for i, (desc, old, new) in enumerate(changes_data):
        change = Change(
            id=f"change-{i}",
            session_id=session.id,
            timestamp=datetime.now(),
            change_type=ChangeType.EDIT,
            file_path=sample_project / "src" / "main.py",
            old_string=old,
            new_string=new,
            new_content=f"updated content {i}",
            tool_input={"tool": "Edit"}
        )
        claude_repo.add_change(change)
        time.sleep(0.01)  # Ensure different timestamps
    
    # Test git log analysis
    log_result = claude_repo.run_git_command(["log", "--oneline"])
    lines = log_result.strip().split('\n')
    commit_lines = [line for line in lines if 'edit:' in line.lower()]
    assert len(commit_lines) >= 3
    
    # Test git stats
    stats_result = claude_repo.run_git_command(["log", "--stat", "--oneline"])
    assert "changes/" in stats_result  # Should show changes in the changes/ directory
    
    # Test searching git history
    search_result = claude_repo.run_git_command(["log", "--grep=typo"])
    assert "typo" in search_result.lower() or len(search_result.strip()) > 0


def test_branch_switching_and_merging(sample_project):
    """Test git branch operations work correctly."""
    claude_repo = ClaudeGitRepository(sample_project)
    claude_repo.init()
    
    # Create changes on default session branch
    session1 = claude_repo.get_or_create_current_session()
    change1 = Change(
        id="branch-test-1",
        session_id=session1.id,
        timestamp=datetime.now(),
        change_type=ChangeType.EDIT,
        file_path=sample_project / "src" / "main.py",
        old_string="Hello World",
        new_string="Hello Branch 1",
        new_content="content 1",
        tool_input={"tool": "Edit"}
    )
    claude_repo.add_change(change1)
    
    # Create experimental branch
    claude_repo.run_git_command(["checkout", "-b", "experiment"])
    
    # Make change on experimental branch
    change2 = Change(
        id="branch-test-2",
        session_id="experimental-session",
        timestamp=datetime.now(),
        change_type=ChangeType.EDIT,
        file_path=sample_project / "src" / "main.py",
        old_string="Hello World",
        new_string="Hello Experiment",
        new_content="experimental content",
        tool_input={"tool": "Edit"}
    )
    claude_repo.add_change(change2)
    
    # Verify we're on experimental branch
    branch_result = claude_repo.run_git_command(["branch"])
    assert "* experiment" in branch_result
    
    # Switch back to session branch
    claude_repo.run_git_command(["checkout", session1.branch_name])
    
    # Verify different commit history on each branch
    session_log = claude_repo.run_git_command(["log", "--oneline"])
    assert "branch-test-1" in session_log
    
    experimental_log = claude_repo.run_git_command(["log", "--oneline", "experiment"])
    assert "branch-test-2" in experimental_log


def test_error_handling(sample_project):
    """Test error handling in git operations."""
    claude_repo = ClaudeGitRepository(sample_project)
    claude_repo.init()
    
    # Test invalid git command
    with pytest.raises(RuntimeError, match="Unknown git command"):
        claude_repo.run_git_command(["invalid-command"])
    
    # Test git command that should fail
    with pytest.raises(RuntimeError, match="Git command failed"):
        claude_repo.run_git_command(["checkout", "non-existent-branch"])
    
    # Test empty command
    with pytest.raises(RuntimeError, match="No git command specified"):
        claude_repo.run_git_command([])


def test_concurrent_session_branch_naming(sample_project):
    """Test that concurrent sessions get unique branch names."""
    claude_repo = ClaudeGitRepository(sample_project)
    claude_repo.init()
    
    # Simulate potential branch name collision by creating a branch manually
    timestamp_str = datetime.now().strftime('%Y-%m-%d-%H-%M')
    collision_branch_name = f"session-{timestamp_str}"
    claude_repo.repo.create_head(collision_branch_name)
    
    # Now create a session - it should get a different name
    session = claude_repo.get_or_create_current_session()
    
    # The session should get a different branch name (with seconds or counter)
    assert session.branch_name != collision_branch_name
    assert session.branch_name.startswith("session-")
    
    # Verify both branches exist
    branches = claude_repo.run_git_command(["branch"])
    assert collision_branch_name in branches
    assert session.branch_name in branches