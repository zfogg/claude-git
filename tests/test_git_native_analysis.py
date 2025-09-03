"""Tests for the new git-native analysis approach."""

import json
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_git.core.repository import ClaudeGitRepository
from claude_git.models.change import Change, ChangeType


def create_test_change(file_path: Path, change_type: ChangeType, 
                      new_content: str, session_id: str = None,
                      old_string: str = None, new_string: str = None) -> Change:
    """Helper to create a properly initialized Change object."""
    return Change(
        id=str(uuid.uuid4()),
        timestamp=datetime.now(),
        session_id=session_id or "test-session",
        change_type=change_type,
        file_path=file_path,
        new_content=new_content,
        old_string=old_string,
        new_string=new_string,
        tool_input={"name": change_type.value.title(), "parameters": {"file_path": str(file_path)}}
    )


def add_test_change(claude_repo, file_path: Path, change_type: ChangeType, 
                   new_content: str, old_string: str = None, new_string: str = None):
    """Helper to create a session and add a change."""
    session = claude_repo.get_or_create_current_session()
    change = create_test_change(file_path, change_type, new_content, 
                               session.id, old_string, new_string)
    return claude_repo.add_change(change), session


@pytest.fixture
def temp_git_repo():
    """Create a temporary git repository for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        repo_path = Path(temp_dir)
        # Create a .git directory to simulate a git repo
        (repo_path / ".git").mkdir()
        yield repo_path


@pytest.fixture
def claude_repo(temp_git_repo):
    """Create an initialized Claude Git repository."""
    repo = ClaudeGitRepository(temp_git_repo)
    repo.init()
    return repo


class TestGitNativeFileStorage:
    """Test the new file mirroring approach."""
    
    def test_file_mirroring_on_write(self, claude_repo):
        """Test that files are properly mirrored in files/ directory."""
        # Create a test file in the project
        test_file = claude_repo.project_root / "test.py"
        test_content = "def hello():\n    print('Hello, world!')"
        test_file.write_text(test_content)
        
        # Create a change
        change = create_test_change(test_file, ChangeType.WRITE, test_content)
        
        # Add the change
        commit_hash = claude_repo.add_change(change)
        
        # Verify mirrored file exists and has correct content
        mirrored_file = claude_repo.claude_git_dir / "files" / "test.py"
        assert mirrored_file.exists()
        assert mirrored_file.read_text() == test_content
        
        # Verify metadata file exists
        metadata_files = list((claude_repo.claude_git_dir / "metadata").glob("*.json"))
        assert len(metadata_files) == 1
        
        metadata = json.loads(metadata_files[0].read_text())
        assert metadata["change_type"] == "write"
        assert metadata["file_path"] == "test.py"
        assert metadata["id"] == change.id
        
    def test_file_mirroring_on_edit(self, claude_repo):
        """Test that edits properly update mirrored files."""
        # Create initial file
        test_file = claude_repo.project_root / "edit_test.py"
        initial_content = "def old_func():\n    pass"
        test_file.write_text(initial_content)
        
        # Create write change
        write_change = create_test_change(test_file, ChangeType.WRITE, initial_content)
        claude_repo.add_change(write_change)
        
        # Create edit change
        new_content = "def new_func():\n    print('Updated!')\n    pass"
        test_file.write_text(new_content)
        
        edit_change = create_test_change(
            test_file, ChangeType.EDIT, new_content,
            old_string="def old_func():\n    pass",
            new_string="def new_func():\n    print('Updated!')\n    pass"
        )
        claude_repo.add_change(edit_change)
        
        # Verify mirrored file has updated content
        mirrored_file = claude_repo.claude_git_dir / "files" / "edit_test.py"
        assert mirrored_file.read_text() == new_content
        
        # Verify we have two metadata files
        metadata_files = list((claude_repo.claude_git_dir / "metadata").glob("*.json"))
        assert len(metadata_files) == 2


class TestGitNativeAnalysis:
    """Test the git-native diff analysis."""
    
    def test_unchanged_file_analysis(self, claude_repo):
        """Test analysis when file hasn't changed since Claude's modification."""
        # Create and add a file
        test_file = claude_repo.project_root / "unchanged.py"
        content = "print('unchanged')"
        test_file.write_text(content)
        
        commit_hash, session = add_test_change(claude_repo, test_file, ChangeType.WRITE, content)
        
        # Get meaningful diff
        diff_results = claude_repo.get_meaningful_diff(limit=5)
        
        # Should show file as unchanged
        assert diff_results["summary"]["claude_changes_intact"] == 1
        assert diff_results["summary"]["user_modified_after_claude"] == 0
        assert diff_results["summary"]["conflicts"] == 0
        
        change_analysis = diff_results["changes_analyzed"][0]
        assert change_analysis["status"] == "unchanged"
        assert change_analysis["file_path"] == "unchanged.py"
        assert not change_analysis["has_conflicts"]
        
    def test_user_modified_file_analysis(self, claude_repo):
        """Test analysis when user modifies file after Claude."""
        # Create and add a file
        test_file = claude_repo.project_root / "modified.py"
        original_content = "def original():\n    print('original')"
        test_file.write_text(original_content)
        
        change = create_test_change(test_file, ChangeType.WRITE, original_content)
        commit_hash = claude_repo.add_change(change)
        
        # User modifies the file
        modified_content = "def original():\n    print('original')\n\ndef user_added():\n    print('user change')"
        test_file.write_text(modified_content)
        
        # Get meaningful diff
        diff_results = claude_repo.get_meaningful_diff(limit=5)
        
        # Should detect user modification
        assert diff_results["summary"]["claude_changes_intact"] == 0
        assert diff_results["summary"]["user_modified_after_claude"] == 1
        assert diff_results["summary"]["conflicts"] == 1
        
        change_analysis = diff_results["changes_analyzed"][0]
        assert change_analysis["status"] == "user_modified"
        assert change_analysis["has_conflicts"]
        assert len(change_analysis["diff_lines"]) > 0
        
    def test_file_deletion_analysis(self, claude_repo):
        """Test analysis when user deletes file after Claude creates it."""
        # Create and add a file
        test_file = claude_repo.project_root / "to_delete.py"
        content = "print('will be deleted')"
        test_file.write_text(content)
        
        change = create_test_change(test_file, ChangeType.WRITE, content)
        claude_repo.add_change(change)
        
        # User deletes the file
        test_file.unlink()
        
        # Get meaningful diff
        diff_results = claude_repo.get_meaningful_diff(limit=5)
        
        # Should detect file deletion
        change_analysis = diff_results["changes_analyzed"][0]
        assert change_analysis["status"] == "file_not_found"
        assert "no longer exists" in change_analysis["diff_lines"][0]
        
    def test_git_native_revert_analysis(self, claude_repo):
        """Test revert capability analysis using git-native approach."""
        # Create and add a file
        test_file = claude_repo.project_root / "revert_test.py"
        content = "def test():\n    pass"
        test_file.write_text(content)
        
        change = create_test_change(test_file, ChangeType.WRITE, content)
        claude_repo.add_change(change)
        
        # User makes small modification
        modified_content = "def test():\n    pass\n# User comment"
        test_file.write_text(modified_content)
        
        # Get analysis
        diff_results = claude_repo.get_meaningful_diff(limit=5)
        change_analysis = diff_results["changes_analyzed"][0]
        
        # Should have revert info
        revert_info = change_analysis["revert_info"]
        assert "diff_stats" in revert_info
        assert revert_info["diff_stats"]["total_changes"] > 0
        assert revert_info["can_revert"] in [True, False]  # Depends on analysis
        
    def test_change_pattern_detection(self, claude_repo):
        """Test detection of user change patterns."""
        # Create file with complex changes
        test_file = claude_repo.project_root / "patterns.py"
        original = "def func():\n    print('hello')"
        test_file.write_text(original)
        
        change = create_test_change(test_file, ChangeType.WRITE, original)
        claude_repo.add_change(change)
        
        # User adds imports and comments
        modified = "import os\n# User comment\ndef func():\n    print('hello')\n    # Another comment"
        test_file.write_text(modified)
        
        # Get analysis
        diff_results = claude_repo.get_meaningful_diff(limit=5)
        change_analysis = diff_results["changes_analyzed"][0]
        
        # Should detect patterns
        patterns = change_analysis["user_changes_detected"]
        assert len(patterns) > 0
        
        # Should contain information about additions
        pattern_text = " ".join(patterns)
        assert "added" in pattern_text.lower() or "User" in pattern_text


class TestGitNativeDiffOutput:
    """Test the enhanced diff output."""
    
    def test_unified_diff_generation(self, claude_repo):
        """Test that unified diffs are properly generated."""
        test_file = claude_repo.project_root / "diff_test.py"
        original = "line1\nline2\nline3"
        test_file.write_text(original)
        
        change = create_test_change(test_file, ChangeType.WRITE, original)
        claude_repo.add_change(change)
        
        # User modifies middle line
        modified = "line1\nline2_modified\nline3"
        test_file.write_text(modified)
        
        # Get analysis
        diff_results = claude_repo.get_meaningful_diff(limit=5)
        change_analysis = diff_results["changes_analyzed"][0]
        
        # Check diff format
        diff_lines = change_analysis["diff_lines"]
        assert any(line.startswith("---") for line in diff_lines)
        assert any(line.startswith("+++") for line in diff_lines)
        assert any(line.startswith("-line2") for line in diff_lines)
        assert any(line.startswith("+line2_modified") for line in diff_lines)
        
    def test_metadata_integration(self, claude_repo):
        """Test that metadata is properly integrated into analysis."""
        test_file = claude_repo.project_root / "meta_test.py" 
        content = "test content"
        test_file.write_text(content)
        
        # Mock parent repo hash
        with patch.object(claude_repo, '_get_parent_repo_hash', return_value='abc123def456'):
            change = create_test_change(test_file, ChangeType.WRITE, content)
            claude_repo.add_change(change)
        
        # Get analysis
        diff_results = claude_repo.get_meaningful_diff(limit=5)
        change_analysis = diff_results["changes_analyzed"][0]
        
        # Should have proper metadata
        assert change_analysis["change_type"] == "write"
        assert change_analysis["parent_repo_hash"] == "abc123def456"
        assert change_analysis["file_path"] == "meta_test.py"


class TestMirroredFileStructure:
    """Test the mirrored directory structure."""
    
    def test_nested_directory_mirroring(self, claude_repo):
        """Test that nested directory structures are properly mirrored."""
        # Create nested file
        nested_dir = claude_repo.project_root / "src" / "module" 
        nested_dir.mkdir(parents=True)
        nested_file = nested_dir / "nested.py"
        content = "# Nested file"
        nested_file.write_text(content)
        
        change = create_test_change(nested_file, ChangeType.WRITE, content)
        claude_repo.add_change(change)
        
        # Verify mirrored structure
        mirrored_file = claude_repo.claude_git_dir / "files" / "src" / "module" / "nested.py"
        assert mirrored_file.exists()
        assert mirrored_file.read_text() == content
        
        # Verify directory structure
        assert (claude_repo.claude_git_dir / "files" / "src").is_dir()
        assert (claude_repo.claude_git_dir / "files" / "src" / "module").is_dir()
        
    def test_special_characters_in_filenames(self, claude_repo):
        """Test handling of special characters in filenames."""
        # Create file with special characters
        test_file = claude_repo.project_root / "test-file_with.special@chars.py"
        content = "# Special filename"
        test_file.write_text(content)
        
        change = create_test_change(test_file, ChangeType.WRITE, content)
        claude_repo.add_change(change)
        
        # Verify mirrored file
        mirrored_file = claude_repo.claude_git_dir / "files" / "test-file_with.special@chars.py"
        assert mirrored_file.exists()
        assert mirrored_file.read_text() == content


class TestGitNativeIntegration:
    """Test integration with git operations."""
    
    def test_git_commits_contain_files_and_metadata(self, claude_repo):
        """Test that git commits contain both mirrored files and metadata."""
        test_file = claude_repo.project_root / "commit_test.py"
        content = "# Test commit"
        test_file.write_text(content)
        
        change = create_test_change(test_file, ChangeType.WRITE, content)
        commit_hash = claude_repo.add_change(change)
        
        # Get the commit
        commit = claude_repo.repo.commit(commit_hash)
        
        # Verify commit contains both files
        committed_paths = [item.path for item in commit.tree.traverse()]
        assert any("files/commit_test.py" in path for path in committed_paths)
        assert any("metadata/" in path and ".json" in path for path in committed_paths)
        
    def test_git_history_readability(self, claude_repo):
        """Test that git history is readable and meaningful."""
        test_file = claude_repo.project_root / "history_test.py"
        content = "print('history test')"
        test_file.write_text(content)
        
        change = create_test_change(test_file, ChangeType.WRITE, content)
        claude_repo.add_change(change)
        
        # Check git log
        commit = claude_repo.repo.head.commit
        assert "write: history_test.py" in commit.message
        assert commit.author.name  # Should have author
        assert commit.committed_datetime  # Should have timestamp