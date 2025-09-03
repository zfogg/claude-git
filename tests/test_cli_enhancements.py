"""Tests for the enhanced CLI features with git-native approach."""

import json
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from click.testing import CliRunner

import pytest

from claude_git.core.repository import ClaudeGitRepository
from claude_git.models.change import Change, ChangeType
from claude_git.cli.main import diff as diff_command


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


class TestToolCallDisplayInCLI:
    """Test the enhanced CLI that shows tool call information."""
    
    def test_write_tool_display(self, claude_repo):
        """Test that Write operations are correctly displayed in CLI."""
        # Create a file write operation
        test_file = claude_repo.project_root / "write_test.py"
        content = "print('write test')"
        test_file.write_text(content)
        
        commit_hash, session = add_test_change(claude_repo, test_file, ChangeType.WRITE, content)
        
        # Get diff results
        diff_results = claude_repo.get_meaningful_diff(limit=5)
        
        # Verify tool type is correctly identified
        change_analysis = diff_results["changes_analyzed"][0]
        assert change_analysis["change_type"] == "write"
        
        # Test that it would show correctly in CLI (without actually running CLI)
        # This tests the data structure that the CLI uses
        expected_tool_icon = "📝"
        tool_icons = {
            "write": "📝",
            "edit": "✏️ ",
            "delete": "🗑️ ",
            "unknown": "❓"
        }
        assert tool_icons[change_analysis["change_type"]] == expected_tool_icon
        
    def test_edit_tool_display(self, claude_repo):
        """Test that Edit operations are correctly displayed in CLI."""
        # Create initial file
        test_file = claude_repo.project_root / "edit_test.py"
        initial_content = "def old_function(): pass"
        test_file.write_text(initial_content)
        
        # Create initial write
        add_test_change(claude_repo, test_file, ChangeType.WRITE, initial_content)
        
        # Create an edit
        new_content = "def new_function(): print('updated')"
        test_file.write_text(new_content)
        
        commit_hash, session = add_test_change(
            claude_repo, test_file, ChangeType.EDIT, new_content,
            old_string="def old_function(): pass",
            new_string="def new_function(): print('updated')"
        )
        
        # Get diff results
        diff_results = claude_repo.get_meaningful_diff(limit=5)
        
        # Find the edit change (should be first since it's most recent)
        edit_change = diff_results["changes_analyzed"][0]
        assert edit_change["change_type"] == "edit"
        
        # Verify edit tool icon
        tool_icons = {
            "write": "📝",
            "edit": "✏️ ",
            "delete": "🗑️ ",
            "unknown": "❓"
        }
        assert tool_icons[edit_change["change_type"]] == "✏️ "


class TestGitNativeConflictDetection:
    """Test the git-native conflict detection in CLI."""
    
    def test_unchanged_file_shows_intact_status(self, claude_repo):
        """Test that unchanged files show proper status."""
        test_file = claude_repo.project_root / "intact_file.py"
        content = "# This file won't be changed by user"
        test_file.write_text(content)
        
        commit_hash, session = add_test_change(claude_repo, test_file, ChangeType.WRITE, content)
        
        # Get diff results
        diff_results = claude_repo.get_meaningful_diff(limit=5)
        
        # Should show as intact
        assert diff_results["summary"]["claude_changes_intact"] == 1
        assert diff_results["summary"]["user_modified_after_claude"] == 0
        
        change_analysis = diff_results["changes_analyzed"][0]
        assert change_analysis["status"] == "unchanged"
        assert not change_analysis["has_conflicts"]
        
    def test_user_modified_file_shows_conflict_status(self, claude_repo):
        """Test that user-modified files are detected as conflicts."""
        test_file = claude_repo.project_root / "modified_file.py"
        original_content = "# Original content from Claude"
        test_file.write_text(original_content)
        
        commit_hash, session = add_test_change(claude_repo, test_file, ChangeType.WRITE, original_content)
        
        # User modifies the file
        user_modified_content = "# Original content from Claude\n# User added this line"
        test_file.write_text(user_modified_content)
        
        # Get diff results
        diff_results = claude_repo.get_meaningful_diff(limit=5)
        
        # Should show as modified
        assert diff_results["summary"]["claude_changes_intact"] == 0
        assert diff_results["summary"]["user_modified_after_claude"] == 1
        assert diff_results["summary"]["conflicts"] == 1
        
        change_analysis = diff_results["changes_analyzed"][0]
        assert change_analysis["status"] == "user_modified"
        assert change_analysis["has_conflicts"]
        assert len(change_analysis["diff_lines"]) > 0
        
    def test_git_native_diff_format(self, claude_repo):
        """Test that git-native diffs are properly formatted."""
        test_file = claude_repo.project_root / "diff_test.py"
        claude_content = "line1\nline2\nline3"
        test_file.write_text(claude_content)
        
        commit_hash, session = add_test_change(claude_repo, test_file, ChangeType.WRITE, claude_content)
        
        # User modifies middle line
        user_content = "line1\nline2_modified\nline3"
        test_file.write_text(user_content)
        
        # Get diff results
        diff_results = claude_repo.get_meaningful_diff(limit=5)
        
        change_analysis = diff_results["changes_analyzed"][0]
        diff_lines = change_analysis["diff_lines"]
        
        # Should have proper unified diff format
        assert any("---" in line for line in diff_lines)
        assert any("+++" in line for line in diff_lines)
        assert any("-line2" in line for line in diff_lines)
        assert any("+line2_modified" in line for line in diff_lines)
        
    def test_revert_confidence_analysis(self, claude_repo):
        """Test that revert confidence is properly calculated."""
        test_file = claude_repo.project_root / "revert_test.py"
        content = "def simple_function(): pass"
        test_file.write_text(content)
        
        commit_hash, session = add_test_change(claude_repo, test_file, ChangeType.WRITE, content)
        
        # Small user modification
        modified_content = "def simple_function(): pass\n# Small comment"
        test_file.write_text(modified_content)
        
        # Get diff results
        diff_results = claude_repo.get_meaningful_diff(limit=5)
        
        change_analysis = diff_results["changes_analyzed"][0]
        revert_info = change_analysis["revert_info"]
        
        # Should have revert analysis
        assert "can_revert" in revert_info
        assert "confidence" in revert_info
        assert "diff_stats" in revert_info
        assert revert_info["diff_stats"]["total_changes"] > 0


class TestEnhancedDiffOutput:
    """Test the enhanced diff output features."""
    
    def test_pattern_detection_in_changes(self, claude_repo):
        """Test detection of user change patterns."""
        test_file = claude_repo.project_root / "pattern_test.py"
        original = "def func(): pass"
        test_file.write_text(original)
        
        commit_hash, session = add_test_change(claude_repo, test_file, ChangeType.WRITE, original)
        
        # User adds imports and comments
        modified = "import os  # User added import\n# User comment\ndef func(): pass"
        test_file.write_text(modified)
        
        # Get diff results
        diff_results = claude_repo.get_meaningful_diff(limit=5)
        
        change_analysis = diff_results["changes_analyzed"][0]
        patterns = change_analysis["user_changes_detected"]
        
        # Should detect patterns
        assert len(patterns) > 0
        
        # Check for common pattern detection
        patterns_text = " ".join(patterns)
        assert "added" in patterns_text.lower() or "modified" in patterns_text.lower()


class TestFileStructureMirroring:
    """Test that the file mirroring works correctly."""
    
    def test_mirrored_files_exist(self, claude_repo):
        """Test that files are properly mirrored."""
        # Create nested file structure
        nested_dir = claude_repo.project_root / "src" / "utils"
        nested_dir.mkdir(parents=True)
        test_file = nested_dir / "helper.py"
        content = "# Utility helper"
        test_file.write_text(content)
        
        commit_hash, session = add_test_change(claude_repo, test_file, ChangeType.WRITE, content)
        
        # Verify mirrored structure
        mirrored_file = claude_repo.claude_git_dir / "files" / "src" / "utils" / "helper.py"
        assert mirrored_file.exists()
        assert mirrored_file.read_text() == content
        
        # Verify metadata exists
        metadata_files = list((claude_repo.claude_git_dir / "metadata").glob("*.json"))
        assert len(metadata_files) >= 1
        
    def test_git_commits_structure(self, claude_repo):
        """Test that git commits have proper structure."""
        test_file = claude_repo.project_root / "commit_structure_test.py"
        content = "# Test commit structure"
        test_file.write_text(content)
        
        commit_hash, session = add_test_change(claude_repo, test_file, ChangeType.WRITE, content)
        
        # Get the commit and verify its structure
        commit = claude_repo.repo.commit(commit_hash)
        
        # Should have meaningful commit message
        assert "write:" in commit.message.lower()
        assert "commit_structure_test.py" in commit.message
        
        # Should contain both files and metadata
        committed_paths = [item.path for item in commit.tree.traverse()]
        assert any("files/" in path for path in committed_paths)
        assert any("metadata/" in path and ".json" in path for path in committed_paths)
        

class TestRealWorldScenarios:
    """Test realistic usage scenarios."""
    
    def test_multiple_changes_same_session(self, claude_repo):
        """Test multiple changes in same session."""
        session = claude_repo.get_or_create_current_session()
        
        # Create multiple files
        for i in range(3):
            test_file = claude_repo.project_root / f"file_{i}.py"
            content = f"# File {i}"
            test_file.write_text(content)
            
            change = create_test_change(test_file, ChangeType.WRITE, content, session.id)
            claude_repo.add_change(change)
        
        # Get diff results
        diff_results = claude_repo.get_meaningful_diff(limit=5)
        
        # Should show all 3 changes
        assert diff_results["summary"]["total_claude_changes"] == 3
        assert len(diff_results["changes_analyzed"]) == 3
        
        # All should be unchanged since we didn't modify them
        assert diff_results["summary"]["claude_changes_intact"] == 3
        
    def test_mixed_write_and_edit_operations(self, claude_repo):
        """Test scenario with both write and edit operations."""
        session = claude_repo.get_or_create_current_session()
        
        # Write initial file
        test_file = claude_repo.project_root / "mixed_ops.py"
        initial_content = "def initial(): pass"
        test_file.write_text(initial_content)
        
        write_change = create_test_change(test_file, ChangeType.WRITE, initial_content, session.id)
        claude_repo.add_change(write_change)
        
        # Edit the file
        new_content = "def initial_renamed(): pass"
        test_file.write_text(new_content)
        
        edit_change = create_test_change(
            test_file, ChangeType.EDIT, new_content, session.id,
            old_string="def initial(): pass",
            new_string="def initial_renamed(): pass"
        )
        claude_repo.add_change(edit_change)
        
        # Get diff results
        diff_results = claude_repo.get_meaningful_diff(limit=5)
        
        # Should show both changes
        assert diff_results["summary"]["total_claude_changes"] == 2
        
        # Find write and edit changes
        changes = {c["change_type"]: c for c in diff_results["changes_analyzed"]}
        assert "write" in changes
        assert "edit" in changes
        
        # Both should be unchanged
        assert all(c["status"] == "unchanged" for c in diff_results["changes_analyzed"])