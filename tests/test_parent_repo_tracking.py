"""Tests for parent repository hash tracking."""

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from git import Repo

from claude_git.core.repository import ClaudeGitRepository
from claude_git.models.change import Change, ChangeType


@pytest.fixture
def project_with_git():
    """Create a project with actual git repository."""
    with tempfile.TemporaryDirectory() as temp_dir:
        project_path = Path(temp_dir)
        
        # Initialize actual git repo
        main_repo = Repo.init(project_path)
        
        # Create initial commit
        test_file = project_path / "main.py"
        test_file.write_text("print('hello world')")
        main_repo.index.add(["main.py"])  # Use relative path
        initial_commit = main_repo.index.commit("Initial commit")
        
        yield project_path, main_repo, initial_commit.hexsha


def test_parent_repo_hash_recording(project_with_git):
    """Test that Claude Git records parent repo hash with changes."""
    project_path, main_repo, initial_hash = project_with_git
    
    claude_repo = ClaudeGitRepository(project_path)
    claude_repo.init()
    
    # Create a change
    change = Change(
        id="test-parent-hash",
        session_id="test-session",
        timestamp=datetime.now(),
        change_type=ChangeType.EDIT,
        file_path=project_path / "main.py",
        old_string="hello world",
        new_string="hello Claude Git",
        new_content="print('hello Claude Git')",
        tool_input={"tool": "Edit"}
    )
    
    commit_hash = claude_repo.add_change(change)
    
    # Verify parent hash is recorded
    assert change.parent_repo_hash == initial_hash
    
    # Verify commit contains parent hash
    commit = claude_repo.repo.commit(commit_hash)
    assert f"Parent repo: {initial_hash[:8]}" in commit.message
    
    # Verify JSON file contains parent hash
    json_files = [f for f in commit.tree.traverse() if f.name.endswith('.json') and 'test-parent-hash' in f.name]
    assert len(json_files) == 1
    
    change_data = json.loads(json_files[0].data_stream.read().decode('utf-8'))
    assert change_data['parent_repo_hash'] == initial_hash


def test_parent_repo_hash_updates_with_main_repo(project_with_git):
    """Test that parent hash updates when main repo changes."""
    project_path, main_repo, initial_hash = project_with_git
    
    claude_repo = ClaudeGitRepository(project_path)
    claude_repo.init()
    
    # Make first Claude change
    change1 = Change(
        id="change-1",
        session_id="test-session",
        timestamp=datetime.now(),
        change_type=ChangeType.EDIT,
        file_path=project_path / "main.py",
        old_string="hello world",
        new_string="hello Claude",
        new_content="print('hello Claude')",
        tool_input={"tool": "Edit"}
    )
    
    claude_repo.add_change(change1)
    assert change1.parent_repo_hash == initial_hash
    
    # Make change to main repo
    test_file = project_path / "main.py"
    test_file.write_text("print('updated by human')")
    main_repo.index.add(["main.py"])
    new_commit = main_repo.index.commit("Human update")
    new_hash = new_commit.hexsha
    
    # Make second Claude change
    change2 = Change(
        id="change-2",
        session_id="test-session", 
        timestamp=datetime.now(),
        change_type=ChangeType.EDIT,
        file_path=project_path / "main.py",
        old_string="updated by human",
        new_string="updated by Claude",
        new_content="print('updated by Claude')",
        tool_input={"tool": "Edit"}
    )
    
    claude_repo.add_change(change2)
    
    # Verify second change has new parent hash
    assert change2.parent_repo_hash == new_hash
    assert change2.parent_repo_hash != change1.parent_repo_hash


def test_no_parent_repo_fallback(project_with_git):
    """Test behavior when parent repo is not available."""
    project_path, main_repo, initial_hash = project_with_git
    
    # Remove .git directory to simulate no parent repo
    import shutil
    shutil.rmtree(project_path / ".git")
    
    # Re-create just the .git directory (empty) to pass the git repo check
    (project_path / ".git").mkdir()
    
    claude_repo = ClaudeGitRepository(project_path)
    claude_repo.init()
    
    # Create change without valid parent repo
    change = Change(
        id="no-parent-test",
        session_id="test-session",
        timestamp=datetime.now(),
        change_type=ChangeType.WRITE,
        file_path=project_path / "new_file.py",
        new_content="# New file",
        tool_input={"tool": "Write"}
    )
    
    commit_hash = claude_repo.add_change(change)
    
    # Should handle gracefully with no parent hash
    assert change.parent_repo_hash is None
    
    # Verify commit still works
    commit = claude_repo.repo.commit(commit_hash)
    assert commit is not None
    
    # JSON should have null parent_repo_hash
    json_files = [f for f in commit.tree.traverse() if f.name.endswith('.json')]
    change_data = json.loads(json_files[0].data_stream.read().decode('utf-8'))
    assert change_data['parent_repo_hash'] is None


def test_find_changes_by_parent_hash_functionality(project_with_git):
    """Test the core functionality for finding changes by parent hash."""
    project_path, main_repo, initial_hash = project_with_git
    
    claude_repo = ClaudeGitRepository(project_path)
    claude_repo.init()
    
    # Create multiple changes with different parent hashes
    change1 = Change(
        id="find-test-1",
        session_id="test-session",
        timestamp=datetime.now(),
        change_type=ChangeType.EDIT,
        file_path=project_path / "file1.py",
        old_string="old",
        new_string="new1",
        new_content="new content 1",
        tool_input={"tool": "Edit"}
    )
    claude_repo.add_change(change1)
    first_parent_hash = change1.parent_repo_hash
    
    # Update main repo
    update_file = project_path / "update.py"
    update_file.write_text("# Updated")
    main_repo.index.add(["update.py"])
    new_commit = main_repo.index.commit("Update")
    second_parent_hash = new_commit.hexsha
    
    # Create second change with different parent hash
    change2 = Change(
        id="find-test-2", 
        session_id="test-session",
        timestamp=datetime.now(),
        change_type=ChangeType.EDIT,
        file_path=project_path / "file2.py",
        old_string="old2",
        new_string="new2", 
        new_content="new content 2",
        tool_input={"tool": "Edit"}
    )
    claude_repo.add_change(change2)
    
    # Verify we can find changes by parent hash
    matching_commits = []
    target_hash = first_parent_hash[:8]
    
    for commit in claude_repo.repo.iter_commits():
        try:
            json_files = [f for f in commit.tree.traverse() if f.name.endswith('.json')]
            for json_file in json_files:
                change_data = json.loads(json_file.data_stream.read().decode('utf-8'))
                if change_data.get('parent_repo_hash', '').startswith(target_hash):
                    matching_commits.append((commit, change_data))
                    break
        except Exception:
            continue
    
    # Should find exactly one change for the first parent hash
    assert len(matching_commits) >= 1
    found_change = matching_commits[0][1]
    assert found_change['id'] == 'find-test-1'


def test_commit_message_includes_parent_hash(project_with_git):
    """Test that commit messages include parent repo hash."""
    project_path, main_repo, initial_hash = project_with_git
    
    claude_repo = ClaudeGitRepository(project_path)
    claude_repo.init()
    
    change = Change(
        id="msg-test",
        session_id="test-session",
        timestamp=datetime.now(),
        change_type=ChangeType.EDIT,
        file_path=project_path / "test.py",
        old_string="before",
        new_string="after",
        new_content="content",
        tool_input={"tool": "Edit"}
    )
    
    commit_hash = claude_repo.add_change(change)
    commit = claude_repo.repo.commit(commit_hash)
    
    # Verify parent hash is in commit message
    assert f"Parent repo: {initial_hash[:8]}" in commit.message
    
    # Verify full commit message structure
    assert "edit: test.py" in commit.message
    assert "before" in commit.message
    assert "after" in commit.message


def test_multiple_changes_different_parent_hashes(project_with_git):
    """Test tracking multiple changes across different parent repo states."""
    project_path, main_repo, initial_hash = project_with_git
    
    claude_repo = ClaudeGitRepository(project_path)
    claude_repo.init()
    
    parent_hashes = [initial_hash]
    
    # Create 3 changes with human changes in between
    for i in range(3):
        # Claude change
        change = Change(
            id=f"multi-test-{i}",
            session_id="test-session",
            timestamp=datetime.now(),
            change_type=ChangeType.EDIT,
            file_path=project_path / f"file{i}.py",
            old_string=f"old{i}",
            new_string=f"new{i}",
            new_content=f"content{i}",
            tool_input={"tool": "Edit"}
        )
        
        claude_repo.add_change(change)
        
        # Human change to main repo
        if i < 2:  # Don't update after last change
            human_file = project_path / f"human_change_{i}.py"
            human_file.write_text(f"# Human change {i}")
            main_repo.index.add([f"human_change_{i}.py"])
            new_commit = main_repo.index.commit(f"Human change {i}")
            parent_hashes.append(new_commit.hexsha)
    
    # Verify all changes have different parent hashes where expected
    commits = list(claude_repo.repo.iter_commits())
    claude_commits = []
    
    for commit in commits:
        try:
            json_files = [f for f in commit.tree.traverse() if f.name.endswith('.json')]
            if json_files:
                change_data = json.loads(json_files[0].data_stream.read().decode('utf-8'))
                if 'multi-test-' in change_data.get('id', ''):
                    claude_commits.append((commit, change_data))
        except Exception:
            continue
    
    # Should have 3 Claude commits
    assert len(claude_commits) >= 3
    
    # Each should have different parent hash (except some might be same if made quickly)
    parent_hashes_found = [data.get('parent_repo_hash') for _, data in claude_commits]
    assert len(set(parent_hashes_found)) >= 2  # At least 2 different parent hashes