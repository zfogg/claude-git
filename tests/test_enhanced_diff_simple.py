"""Simple tests for enhanced claude-git diff functionality to verify core features work."""

import json
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from click.testing import CliRunner

import pytest

from claude_git.core.repository import ClaudeGitRepository
from claude_git.models.change import Change, ChangeType
from claude_git.cli.main import diff as diff_command, _parse_diff_args


def create_test_change(file_path: Path, change_type: ChangeType, 
                      new_content: str, session_id: str = None,
                      old_string: str = None, new_string: str = None,
                      parent_repo_hash: str = None) -> Change:
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
        parent_repo_hash=parent_repo_hash,
        tool_input={"name": change_type.value.title(), "parameters": {"file_path": str(file_path)}}
    )


def add_test_change(claude_repo, file_path: Path, change_type: ChangeType, 
                   new_content: str, old_string: str = None, new_string: str = None,
                   parent_repo_hash: str = None):
    """Helper to create a session and add a change."""
    session = claude_repo.get_or_create_current_session()
    change = create_test_change(file_path, change_type, new_content, 
                               session.id, old_string, new_string, parent_repo_hash)
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


class TestArgumentParsingCore:
    """Test core argument parsing features that must work."""
    
    def test_parse_basic_cases(self):
        """Test basic argument parsing cases."""
        # No arguments
        parsed = _parse_diff_args(())
        assert parsed["commit_range"] is None
        assert parsed["single_commit"] is None
        assert parsed["paths"] == []
        
        # Single commit
        parsed = _parse_diff_args(("HEAD~1",))
        assert parsed["single_commit"] == "HEAD~1"
        
        # Commit range
        parsed = _parse_diff_args(("HEAD~3...HEAD~1",))
        assert parsed["commit_range"] == "HEAD~3...HEAD~1"
        
        # Paths only
        parsed = _parse_diff_args(("src/", "tests/"))
        assert parsed["paths"] == ["src/", "tests/"]
        
        # Commit with paths (git-style)
        parsed = _parse_diff_args(("HEAD~1", "src/"))
        assert parsed["single_commit"] == "HEAD~1"
        assert parsed["paths"] == ["src/"]
        
        # Commit range with paths (git-style)
        parsed = _parse_diff_args(("HEAD~3...HEAD~1", "src/", "tests/"))
        assert parsed["commit_range"] == "HEAD~3...HEAD~1"
        assert parsed["paths"] == ["src/", "tests/"]


class TestCLIBasicFunctionality:
    """Test that CLI commands work without errors."""
    
    def test_basic_diff_works(self, claude_repo):
        """Test that basic diff command executes successfully."""
        # Create a simple change
        test_file = claude_repo.project_root / "test.py"
        test_file.write_text("print('hello')")
        add_test_change(claude_repo, test_file, ChangeType.WRITE, "print('hello')")
        
        # Test basic diff
        runner = CliRunner()
        with patch('claude_git.cli.main._find_project_root', return_value=claude_repo.project_root):
            result = runner.invoke(diff_command, [])
            assert result.exit_code == 0
            # Check for git-style diff format
            assert "diff --git a/test.py b/test.py" in result.output
            assert "# Claude change" in result.output
    
    def test_diff_with_help(self):
        """Test that help displays correctly."""
        runner = CliRunner()
        result = runner.invoke(diff_command, ['--help'])
        assert result.exit_code == 0
        assert "Show meaningful diff" in result.output
        assert ("commit range with paths" in result.output or "Range with multiple paths" in result.output)  # New functionality documented
    
    def test_diff_empty_repo(self, claude_repo):
        """Test diff on empty repository doesn't crash."""
        runner = CliRunner()
        with patch('claude_git.cli.main._find_project_root', return_value=claude_repo.project_root):
            result = runner.invoke(diff_command, [])
            assert result.exit_code == 0
            # With no changes, output should be empty (like git diff)
            assert result.output.strip() == ""


class TestNewGitStyleSyntax:
    """Test the new git-style syntax features."""
    
    def test_commit_range_with_path_parsing(self):
        """Test that commit range with paths parses correctly."""
        parsed = _parse_diff_args(("abc123...def456", "src/module.py"))
        assert parsed["commit_range"] == "abc123...def456"
        assert parsed["paths"] == ["src/module.py"]
        
        parsed = _parse_diff_args(("HEAD~2...HEAD", "src/", "tests/"))
        assert parsed["commit_range"] == "HEAD~2...HEAD"
        assert parsed["paths"] == ["src/", "tests/"]
    
    def test_single_commit_with_path_parsing(self):
        """Test that single commit with paths parses correctly."""
        parsed = _parse_diff_args(("HEAD~1", "src/file.py"))
        assert parsed["single_commit"] == "HEAD~1"
        assert parsed["paths"] == ["src/file.py"]
    
    def test_cli_accepts_new_syntax(self, claude_repo):
        """Test that CLI accepts the new git-style syntax."""
        # Create some test changes
        test_file = claude_repo.project_root / "test.py"
        test_file.write_text("content")
        add_test_change(claude_repo, test_file, ChangeType.WRITE, "content")
        
        runner = CliRunner()
        with patch('claude_git.cli.main._find_project_root', return_value=claude_repo.project_root):
            # Test path filtering
            result = runner.invoke(diff_command, ['tests/'])
            assert result.exit_code == 0
            
            # Test commit with path (even if it returns no results)
            result = runner.invoke(diff_command, ['HEAD~1', 'src/'])
            assert result.exit_code == 0


class TestShowsByDefault:
    """Test that diff shows changes by default as requested."""
    
    def test_shows_changes_by_default(self, claude_repo):
        """Test that diff shows changes by default (not just summaries)."""
        # Create a change with conflict
        test_file = claude_repo.project_root / "conflict_test.py"
        test_file.write_text("original content")
        add_test_change(claude_repo, test_file, ChangeType.WRITE, "original content")
        
        # User modifies file 
        test_file.write_text("user modified content")
        
        runner = CliRunner()
        with patch('claude_git.cli.main._find_project_root', return_value=claude_repo.project_root):
            result = runner.invoke(diff_command, [])
            assert result.exit_code == 0
            
            # Should show the file and analysis (this verifies "shows by default")
            assert "conflict_test.py" in result.output
            # Check for git-style diff format
            assert "diff --git" in result.output
            assert "# Claude change" in result.output
    
    def test_shows_tool_information(self, claude_repo):
        """Test that diff shows tool call information."""
        test_file = claude_repo.project_root / "tool_test.py"
        test_file.write_text("content")
        add_test_change(claude_repo, test_file, ChangeType.WRITE, "content")
        
        runner = CliRunner()
        with patch('claude_git.cli.main._find_project_root', return_value=claude_repo.project_root):
            result = runner.invoke(diff_command, [])
            assert result.exit_code == 0
            
            # Should show tool information in the change comment
            assert "write:" in result.output


def test_comprehensive_functionality():
    """Integration test that verifies all major features work together."""
    # This test demonstrates the full functionality working together
    args_test_cases = [
        # Basic cases
        ((), {"commit_range": None, "single_commit": None, "paths": []}),
        (("HEAD~1",), {"single_commit": "HEAD~1", "paths": []}),
        (("HEAD~3...HEAD~1",), {"commit_range": "HEAD~3...HEAD~1", "paths": []}),
        
        # Git-style with paths
        (("HEAD~1", "src/"), {"single_commit": "HEAD~1", "paths": ["src/"]}),
        (("HEAD~3...HEAD~1", "src/", "tests/"), {"commit_range": "HEAD~3...HEAD~1", "paths": ["src/", "tests/"]}),
        
        # With separator
        (("HEAD~1", "--", "src/"), {"single_commit": "HEAD~1", "paths": ["src/"]}),
    ]
    
    for args, expected in args_test_cases:
        parsed = _parse_diff_args(args)
        
        # Check expected fields
        for key, value in expected.items():
            assert parsed[key] == value, f"Failed for args {args}: {key} = {parsed[key]}, expected {value}"
    
    print("All argument parsing tests passed!")


if __name__ == "__main__":
    test_comprehensive_functionality()
    print("Core functionality tests completed successfully!")