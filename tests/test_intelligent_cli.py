"""Tests for intelligent CLI commands (conflicts, resolve, analyze)."""

import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from git import Repo

from claude_git.cli.main import main
from claude_git.core.repository import ClaudeGitRepository
from claude_git.models.change import Change, ChangeType


@pytest.fixture
def project_with_conflicts():
    """Create a project with detected conflicts for CLI testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        project_path = Path(temp_dir)
        
        # Initialize git repo
        git_repo = Repo.init(project_path)
        
        # Create and commit initial file
        test_file = project_path / "test.py"
        test_file.write_text("def original_function():\n    pass")
        git_repo.index.add(["test.py"])
        git_repo.index.commit("Initial commit")
        
        # Human modifies file
        test_file.write_text("def original_function():\n    # Modified by human\n    pass")
        git_repo.index.add(["test.py"])
        
        # Initialize Claude Git and create conflicting change
        claude_repo = ClaudeGitRepository(project_path)
        claude_repo.init()
        
        session = claude_repo.get_or_create_current_session()
        
        change = Change(
            id="conflict-change",
            session_id=session.id,
            timestamp=datetime.now(),
            change_type=ChangeType.EDIT,
            file_path=project_path / "test.py",
            old_string="def original_function():",
            new_string="def improved_function():",
            new_content="def improved_function():\n    # Updated by Claude\n    pass",
            tool_input={"tool": "Edit"}
        )
        
        commit_hash = claude_repo.add_change(change)
        
        yield project_path, commit_hash


@pytest.fixture  
def project_with_multiple_changes():
    """Create a project with multiple changes for analysis testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        project_path = Path(temp_dir)
        
        # Initialize git repo
        git_repo = Repo.init(project_path)
        
        # Create initial files
        files_to_create = [
            ("main.py", "def main():\n    pass"),
            ("utils.py", "def helper():\n    pass"),
            ("config.py", "DEBUG = True")
        ]
        
        for filename, content in files_to_create:
            file_path = project_path / filename
            file_path.write_text(content)
            git_repo.index.add([filename])
            
        git_repo.index.commit("Initial commit")
        
        # Initialize Claude Git
        claude_repo = ClaudeGitRepository(project_path)
        claude_repo.init()
        
        session = claude_repo.get_or_create_current_session()
        
        # Create multiple changes with different patterns
        changes_data = [
            ("edit", "main.py", "def main():", "def improved_main():", False),
            ("edit", "utils.py", "def helper():", "def better_helper():", True),  # This will have conflict
            ("write", "new_file.py", None, None, False),
            ("edit", "config.py", "DEBUG = True", "DEBUG = False", False),
        ]
        
        commit_hashes = []
        
        for i, (change_type, filename, old_str, new_str, create_human_conflict) in enumerate(changes_data):
            # Create human conflict if specified
            if create_human_conflict:
                file_path = project_path / filename
                current_content = file_path.read_text()
                file_path.write_text(current_content + "\n# Human added comment")
                git_repo.index.add([filename])
            
            if change_type == "edit":
                change = Change(
                    id=f"change-{i}",
                    session_id=session.id,
                    timestamp=datetime.now(),
                    change_type=ChangeType.EDIT,
                    file_path=project_path / filename,
                    old_string=old_str,
                    new_string=new_str,
                    new_content=f"updated content {i}",
                    tool_input={"tool": "Edit"}
                )
            else:  # write
                change = Change(
                    id=f"change-{i}",
                    session_id=session.id,
                    timestamp=datetime.now(),
                    change_type=ChangeType.WRITE,
                    file_path=project_path / filename,
                    new_content=f"# New file {i}\ndef new_function():\n    return {i}",
                    tool_input={"tool": "Write"}
                )
            
            commit_hash = claude_repo.add_change(change)
            commit_hashes.append(commit_hash)
        
        yield project_path, commit_hashes


def test_conflicts_command_detects_conflicts(project_with_conflicts):
    """Test that the conflicts command detects and displays conflicts."""
    project_path, commit_hash = project_with_conflicts
    
    runner = CliRunner()
    
    with runner.isolated_filesystem():
        # Change to project directory
        import os
        os.chdir(str(project_path))
        
        result = runner.invoke(main, ['conflicts'])
        
        assert result.exit_code == 0
        assert "Conflict detected" in result.output
        assert "Both you and Claude modified" in result.output
        assert commit_hash[:8] in result.output


def test_conflicts_command_no_conflicts():
    """Test conflicts command when no conflicts exist."""
    with tempfile.TemporaryDirectory() as temp_dir:
        project_path = Path(temp_dir)
        
        # Create clean project
        git_repo = Repo.init(project_path)
        test_file = project_path / "clean.py"
        test_file.write_text("# Clean file")
        git_repo.index.add(["clean.py"])
        git_repo.index.commit("Clean commit")
        
        # Initialize Claude Git with clean change
        claude_repo = ClaudeGitRepository(project_path)
        claude_repo.init()
        
        session = claude_repo.get_or_create_current_session()
        change = Change(
            id="clean-change",
            session_id=session.id,
            timestamp=datetime.now(),
            change_type=ChangeType.EDIT,
            file_path=project_path / "clean.py",
            old_string="# Clean file",
            new_string="# Updated file",
            new_content="# Updated file",
            tool_input={"tool": "Edit"}
        )
        
        claude_repo.add_change(change)
        
        runner = CliRunner()
        
        with runner.isolated_filesystem():
            import os
            os.chdir(str(project_path))
            
            result = runner.invoke(main, ['conflicts'])
            
            assert result.exit_code == 0
            assert "No conflicts detected" in result.output


def test_resolve_command_provides_guidance(project_with_conflicts):
    """Test that the resolve command provides conflict resolution guidance."""
    project_path, commit_hash = project_with_conflicts
    
    runner = CliRunner()
    
    with runner.isolated_filesystem():
        import os
        os.chdir(str(project_path))
        
        result = runner.invoke(main, ['resolve', commit_hash])
        
        assert result.exit_code == 0
        assert "Conflict resolution for commit" in result.output
        assert "Claude's Change:" in result.output
        assert "Resolution Options:" in result.output
        assert "Review changes manually" in result.output


def test_resolve_command_no_conflicts():
    """Test resolve command on a commit without conflicts."""
    with tempfile.TemporaryDirectory() as temp_dir:
        project_path = Path(temp_dir)
        
        # Create project with non-conflicting change
        git_repo = Repo.init(project_path)
        test_file = project_path / "clean.py"
        test_file.write_text("# Original")
        git_repo.index.add(["clean.py"])
        git_repo.index.commit("Initial")
        
        claude_repo = ClaudeGitRepository(project_path)
        claude_repo.init()
        
        session = claude_repo.get_or_create_current_session()
        change = Change(
            id="clean-change",
            session_id=session.id,
            timestamp=datetime.now(),
            change_type=ChangeType.EDIT,
            file_path=project_path / "clean.py",
            old_string="# Original",
            new_string="# Updated",
            new_content="# Updated",
            tool_input={"tool": "Edit"}
        )
        
        commit_hash = claude_repo.add_change(change)
        
        runner = CliRunner()
        
        with runner.isolated_filesystem():
            import os
            os.chdir(str(project_path))
            
            result = runner.invoke(main, ['resolve', commit_hash])
            
            assert result.exit_code == 0
            assert "No conflicts detected" in result.output


def test_analyze_command_provides_insights(project_with_multiple_changes):
    """Test that the analyze command provides intelligent insights."""
    project_path, commit_hashes = project_with_multiple_changes
    
    runner = CliRunner()
    
    with runner.isolated_filesystem():
        import os
        os.chdir(str(project_path))
        
        result = runner.invoke(main, ['analyze'])
        
        assert result.exit_code == 0
        assert "Analysis of recent Claude changes" in result.output
        assert "Change Analysis Summary" in result.output
        assert "Total changes:" in result.output
        assert "Conflicts detected:" in result.output
        assert "File Types Modified" in result.output
        assert "Recommended Merge Strategy:" in result.output
        assert "Suggested Next Steps" in result.output


def test_analyze_command_merge_strategies(project_with_multiple_changes):
    """Test that different merge strategies are recommended based on conflict ratios."""
    project_path, commit_hashes = project_with_multiple_changes
    
    runner = CliRunner()
    
    with runner.isolated_filesystem():
        import os
        os.chdir(str(project_path))
        
        result = runner.invoke(main, ['analyze'])
        
        assert result.exit_code == 0
        
        # Should recommend selective merge since we have some conflicts (25% rate)
        assert "🟡 Selective Merge" in result.output or "🟢 Safe Auto-Merge" in result.output


def test_analyze_command_with_session_id(project_with_multiple_changes):
    """Test analyze command with specific session ID."""
    project_path, commit_hashes = project_with_multiple_changes
    
    # Get session ID
    claude_repo = ClaudeGitRepository(project_path)
    sessions = claude_repo.list_sessions()
    session_id = sessions[0].id
    
    runner = CliRunner()
    
    with runner.isolated_filesystem():
        import os
        os.chdir(str(project_path))
        
        result = runner.invoke(main, ['analyze', '--session-id', session_id])
        
        assert result.exit_code == 0
        assert f"Analysis for session {session_id[:8]}" in result.output
        assert "Change Analysis Summary" in result.output


def test_analyze_command_recommendations():
    """Test that appropriate recommendations are generated by analyze command."""
    with tempfile.TemporaryDirectory() as temp_dir:
        project_path = Path(temp_dir)
        
        # Create project with Python files
        git_repo = Repo.init(project_path)
        
        py_files = ["main.py", "utils.py", "test.py"]
        for filename in py_files:
            file_path = project_path / filename
            file_path.write_text(f"# {filename}\ndef function():\n    pass")
            git_repo.index.add([filename])
        
        git_repo.index.commit("Initial commit")
        
        claude_repo = ClaudeGitRepository(project_path)
        claude_repo.init()
        
        session = claude_repo.get_or_create_current_session()
        
        # Create multiple edit changes (should trigger batching recommendation)
        for i, filename in enumerate(py_files):
            change = Change(
                id=f"edit-{i}",
                session_id=session.id,
                timestamp=datetime.now(),
                change_type=ChangeType.EDIT,
                file_path=project_path / filename,
                old_string="def function():",
                new_string=f"def improved_function_{i}():",
                new_content=f"# Updated {filename}",
                tool_input={"tool": "Edit"}
            )
            claude_repo.add_change(change)
        
        runner = CliRunner()
        
        with runner.isolated_filesystem():
            import os
            os.chdir(str(project_path))
            
            result = runner.invoke(main, ['analyze'])
            
            assert result.exit_code == 0
            assert "Intelligent Recommendations" in result.output
            assert "Python files modified" in result.output


def test_cli_error_handling():
    """Test CLI error handling for invalid inputs."""
    runner = CliRunner()
    
    with runner.isolated_filesystem():
        # Test conflicts command without Claude Git initialized
        result = runner.invoke(main, ['conflicts'])
        assert result.exit_code == 0
        assert "Not in a git repository" in result.output
        
        # Test resolve with invalid commit hash in empty directory
        result = runner.invoke(main, ['resolve', 'invalid-hash'])
        assert result.exit_code == 0
        assert "Not in a git repository" in result.output
        
        # Test analyze without initialization
        result = runner.invoke(main, ['analyze'])
        assert result.exit_code == 0
        assert "Not in a git repository" in result.output


def test_conflicts_command_with_limit(project_with_multiple_changes):
    """Test conflicts command with limit parameter."""
    project_path, commit_hashes = project_with_multiple_changes
    
    runner = CliRunner()
    
    with runner.isolated_filesystem():
        import os
        os.chdir(str(project_path))
        
        result = runner.invoke(main, ['conflicts', '--limit', '2'])
        
        assert result.exit_code == 0
        # Should still detect conflicts but with limited search
        assert "Conflict detected" in result.output or "No conflicts detected" in result.output


def test_analyze_handles_no_changes():
    """Test analyze command when no Claude changes exist."""
    with tempfile.TemporaryDirectory() as temp_dir:
        project_path = Path(temp_dir)
        
        # Create empty Claude Git repo
        git_repo = Repo.init(project_path)
        test_file = project_path / "empty.py"
        test_file.write_text("# Empty")
        git_repo.index.add(["empty.py"])
        git_repo.index.commit("Initial")
        
        claude_repo = ClaudeGitRepository(project_path)
        claude_repo.init()
        
        runner = CliRunner()
        
        with runner.isolated_filesystem():
            import os
            os.chdir(str(project_path))
            
            result = runner.invoke(main, ['analyze'])
            
            assert result.exit_code == 0
            assert "No Claude changes found to analyze" in result.output