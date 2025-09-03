"""Tests for intelligent conflict detection and analysis features."""

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from git import Repo

from claude_git.core.repository import ClaudeGitRepository
from claude_git.models.change import Change, ChangeType


@pytest.fixture
def sample_project_with_human_changes():
    """Create a project with both git repo and human modifications."""
    with tempfile.TemporaryDirectory() as temp_dir:
        project_path = Path(temp_dir)
        
        # Initialize git repo
        git_repo = Repo.init(project_path)
        
        # Create initial files
        src_dir = project_path / "src"
        src_dir.mkdir()
        
        main_py = src_dir / "main.py"
        main_py.write_text("""def main():
    print("Hello World")
    
if __name__ == "__main__":
    main()
""")
        
        utils_py = src_dir / "utils.py"
        utils_py.write_text("""def helper_function():
    return "original"
    
def another_function():
    pass
""")
        
        # Initial commit
        git_repo.index.add([str(main_py.relative_to(project_path)), 
                           str(utils_py.relative_to(project_path))])
        git_repo.index.commit("Initial commit")
        
        # Simulate human modifications (staged but not committed)
        main_py.write_text("""def main():
    print("Hello World - Modified by Human")
    
if __name__ == "__main__":
    main()
""")
        
        # Create new file that human added
        new_file = src_dir / "new_module.py" 
        new_file.write_text("""# New module added by human
def new_function():
    return "human created"
""")
        
        # Stage human changes
        git_repo.index.add([str(main_py.relative_to(project_path)),
                           str(new_file.relative_to(project_path))])
        
        yield project_path


def test_parent_repo_status_capture(sample_project_with_human_changes):
    """Test that parent repository status is correctly captured."""
    claude_repo = ClaudeGitRepository(sample_project_with_human_changes)
    claude_repo.init()
    
    # Get parent repo status
    status = claude_repo._get_parent_repo_status()
    
    assert status is not None
    assert status["has_changes"] is True
    assert "src/main.py" in status["modified_files"]
    assert "src/new_module.py" in status["added_files"]
    assert len(status["file_hashes"]) > 0
    assert "src/main.py" in status["file_hashes"]


def test_conflict_detection_same_file(sample_project_with_human_changes):
    """Test conflict detection when Claude and human modify the same file."""
    claude_repo = ClaudeGitRepository(sample_project_with_human_changes)
    claude_repo.init()
    
    session = claude_repo.get_or_create_current_session()
    
    # Claude modifies the same file that human modified
    change = Change(
        id="test-conflict",
        session_id=session.id,
        timestamp=datetime.now(),
        change_type=ChangeType.EDIT,
        file_path=sample_project_with_human_changes / "src" / "main.py",
        old_string='print("Hello World")',
        new_string='print("Hello Claude!")',
        new_content='def main():\n    print("Hello Claude!")\n\nif __name__ == "__main__":\n    main()',
        tool_input={"tool": "Edit"}
    )
    
    # Add the change (this will trigger status capture and conflict analysis)
    commit_hash = claude_repo.add_change(change)
    
    # Verify conflict was detected
    commit = claude_repo.repo.commit(commit_hash)
    json_files = [f for f in commit.tree.traverse() 
                  if f.name.endswith('.json') and 'changes/' in str(f.path)]
    
    assert len(json_files) == 1
    change_data = json.loads(json_files[0].data_stream.read().decode('utf-8'))
    
    conflict_analysis = change_data["conflict_analysis"]
    assert conflict_analysis["has_conflicts"] is True
    assert conflict_analysis["same_file_modified"] is True
    assert "Both you and Claude modified" in conflict_analysis["recommendations"][0]


def test_conflict_detection_related_files(sample_project_with_human_changes):
    """Test conflict detection for related files (same directory).""" 
    claude_repo = ClaudeGitRepository(sample_project_with_human_changes)
    claude_repo.init()
    
    session = claude_repo.get_or_create_current_session()
    
    # Claude modifies a different file in the same directory
    change = Change(
        id="test-related",
        session_id=session.id,
        timestamp=datetime.now(),
        change_type=ChangeType.EDIT,
        file_path=sample_project_with_human_changes / "src" / "utils.py",
        old_string='return "original"',
        new_string='return "updated by claude"',
        new_content='def helper_function():\n    return "updated by claude"',
        tool_input={"tool": "Edit"}
    )
    
    commit_hash = claude_repo.add_change(change)
    
    # Check conflict analysis
    commit = claude_repo.repo.commit(commit_hash)
    json_files = [f for f in commit.tree.traverse() 
                  if f.name.endswith('.json') and 'changes/' in str(f.path)]
    
    change_data = json.loads(json_files[0].data_stream.read().decode('utf-8'))
    conflict_analysis = change_data["conflict_analysis"]
    
    assert conflict_analysis["has_conflicts"] is True
    assert len(conflict_analysis["related_files_modified"]) > 0
    assert "src/main.py" in conflict_analysis["related_files_modified"]


def test_human_modifications_tracking(sample_project_with_human_changes):
    """Test that human modifications are properly tracked and analyzed."""
    claude_repo = ClaudeGitRepository(sample_project_with_human_changes)
    claude_repo.init()
    
    session = claude_repo.get_or_create_current_session()
    
    change = Change(
        id="test-human-tracking",
        session_id=session.id,
        timestamp=datetime.now(),
        change_type=ChangeType.WRITE,
        file_path=sample_project_with_human_changes / "src" / "claude_file.py",
        new_content="# File created by Claude\ndef claude_function():\n    pass",
        tool_input={"tool": "Write"}
    )
    
    commit_hash = claude_repo.add_change(change)
    
    # Analyze human modifications
    commit = claude_repo.repo.commit(commit_hash)
    json_files = [f for f in commit.tree.traverse() 
                  if f.name.endswith('.json') and 'changes/' in str(f.path)]
    
    change_data = json.loads(json_files[0].data_stream.read().decode('utf-8'))
    conflict_analysis = change_data["conflict_analysis"]
    
    human_mods = conflict_analysis["human_modifications"]
    assert len(human_mods) >= 2  # main.py (modified) + new_module.py (added)
    
    # Check that we captured different types of human changes
    mod_types = {mod["type"] for mod in human_mods}
    assert "modified" in mod_types
    assert "added" in mod_types


def test_no_conflicts_when_clean_repo():
    """Test that no conflicts are detected when parent repo is clean."""
    with tempfile.TemporaryDirectory() as temp_dir:
        project_path = Path(temp_dir)
        
        # Create clean git repo
        git_repo = Repo.init(project_path)
        test_file = project_path / "test.py"
        test_file.write_text("# Clean file")
        git_repo.index.add(["test.py"])
        git_repo.index.commit("Clean commit")
        
        claude_repo = ClaudeGitRepository(project_path)
        claude_repo.init()
        
        session = claude_repo.get_or_create_current_session()
        
        change = Change(
            id="test-no-conflict",
            session_id=session.id,
            timestamp=datetime.now(),
            change_type=ChangeType.EDIT,
            file_path=project_path / "test.py",
            old_string="# Clean file",
            new_string="# Updated by Claude",
            new_content="# Updated by Claude",
            tool_input={"tool": "Edit"}
        )
        
        commit_hash = claude_repo.add_change(change)
        
        # Check that no conflicts were detected
        commit = claude_repo.repo.commit(commit_hash)
        json_files = [f for f in commit.tree.traverse() 
                      if f.name.endswith('.json') and 'changes/' in str(f.path)]
        
        change_data = json.loads(json_files[0].data_stream.read().decode('utf-8'))
        conflict_analysis = change_data["conflict_analysis"]
        
        assert conflict_analysis["has_conflicts"] is False
        assert conflict_analysis["same_file_modified"] is False
        assert len(conflict_analysis["human_modifications"]) == 0


def test_conflict_analysis_recommendations(sample_project_with_human_changes):
    """Test that appropriate recommendations are generated."""
    claude_repo = ClaudeGitRepository(sample_project_with_human_changes)
    claude_repo.init()
    
    session = claude_repo.get_or_create_current_session()
    
    # Create a change that conflicts with human modifications
    change = Change(
        id="test-recommendations",
        session_id=session.id,
        timestamp=datetime.now(),
        change_type=ChangeType.EDIT,
        file_path=sample_project_with_human_changes / "src" / "main.py",
        old_string="Hello World",
        new_string="Hello Claude",
        new_content="updated content",
        tool_input={"tool": "Edit"}
    )
    
    commit_hash = claude_repo.add_change(change)
    
    # Check recommendations
    commit = claude_repo.repo.commit(commit_hash)
    json_files = [f for f in commit.tree.traverse() 
                  if f.name.endswith('.json') and 'changes/' in str(f.path)]
    
    change_data = json.loads(json_files[0].data_stream.read().decode('utf-8'))
    conflict_analysis = change_data["conflict_analysis"]
    
    recommendations = conflict_analysis["recommendations"]
    assert len(recommendations) > 0
    
    # Should have recommendation about both parties modifying same file
    same_file_rec = any("Both you and Claude modified" in rec for rec in recommendations)
    assert same_file_rec is True
    
    # Should have recommendation about human modifications count
    human_mod_rec = any("files modified by human" in rec for rec in recommendations)
    assert human_mod_rec is True


def test_file_hash_tracking(sample_project_with_human_changes):
    """Test that file content hashes are tracked for modified files."""
    claude_repo = ClaudeGitRepository(sample_project_with_human_changes)
    claude_repo.init()
    
    status = claude_repo._get_parent_repo_status()
    
    assert "file_hashes" in status
    assert "src/main.py" in status["file_hashes"]
    
    # Verify hash is reasonable length (16 char truncated SHA256)
    hash_value = status["file_hashes"]["src/main.py"]
    assert len(hash_value) == 16
    assert all(c in "0123456789abcdef" for c in hash_value)


def test_porcelain_status_parsing():
    """Test parsing of git porcelain status output."""
    with tempfile.TemporaryDirectory() as temp_dir:
        project_path = Path(temp_dir)
        
        # Create git repo with various file states
        git_repo = Repo.init(project_path)
        
        # Tracked file
        tracked_file = project_path / "tracked.py"
        tracked_file.write_text("original")
        git_repo.index.add(["tracked.py"])
        git_repo.index.commit("Initial")
        
        # Modified tracked file
        tracked_file.write_text("modified")
        git_repo.index.add(["tracked.py"])
        
        # New untracked file
        new_file = project_path / "untracked.py"
        new_file.write_text("new file")
        
        claude_repo = ClaudeGitRepository(project_path)
        claude_repo.init()
        
        status = claude_repo._get_parent_repo_status()
        
        assert status["has_changes"] is True
        assert "tracked.py" in status["added_files"]  # Staged change
        assert "untracked.py" in status["untracked_files"]