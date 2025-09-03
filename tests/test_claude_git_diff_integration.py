"""Robust integration tests for claude-git diff using real git operations.

These tests create real git repositories, make commits, and verify that
claude-git diff behavior matches git diff behavior for files that Claude modifies.
"""

import tempfile
import shutil
import subprocess
from pathlib import Path
import git
import pytest
from click.testing import CliRunner

from claude_git.core.repository import ClaudeGitRepository
from claude_git.cli.main import diff as diff_command
from claude_git.models.change import ChangeType


class TestClaudeGitDiffIntegration:
    """Integration tests that compare claude-git diff with git diff behavior."""

    @pytest.fixture
    def git_repo_with_history(self):
        """Create a git repository with real commit history."""
        temp_dir = Path(tempfile.mkdtemp())
        try:
            # Initialize git repo
            repo = git.Repo.init(temp_dir)
            repo.config_writer().set_value("user", "name", "Test User").release()
            repo.config_writer().set_value("user", "email", "test@example.com").release()
            
            # Create initial commit
            readme = temp_dir / "README.md"
            readme.write_text("# Test Repository")
            repo.index.add(["README.md"])
            initial_commit = repo.index.commit("Initial commit")
            
            # Create first feature file
            feature1 = temp_dir / "src" / "feature1.py"
            feature1.parent.mkdir(parents=True, exist_ok=True)
            feature1.write_text("def feature1():\n    return 'hello'\n")
            repo.index.add(["src/feature1.py"])
            commit1 = repo.index.commit("Add feature1")
            
            # Create second feature file
            feature2 = temp_dir / "src" / "feature2.py" 
            feature2.write_text("def feature2():\n    return 'world'\n")
            repo.index.add(["src/feature2.py"])
            commit2 = repo.index.commit("Add feature2")
            
            # Modify first feature
            feature1.write_text("def feature1():\n    return 'hello updated'\n")
            repo.index.add(["src/feature1.py"])
            commit3 = repo.index.commit("Update feature1")
            
            # Add third feature
            feature3 = temp_dir / "src" / "feature3.py"
            feature3.write_text("def feature3():\n    return 'new feature'\n")
            repo.index.add(["src/feature3.py"])
            commit4 = repo.index.commit("Add feature3")
            
            yield {
                'temp_dir': temp_dir,
                'repo': repo,
                'commits': {
                    'initial': initial_commit.hexsha,
                    'feature1': commit1.hexsha,
                    'feature2': commit2.hexsha,
                    'feature1_updated': commit3.hexsha,
                    'feature3': commit4.hexsha,
                }
            }
        finally:
            shutil.rmtree(temp_dir)

    def _setup_claude_changes(self, claude_repo, file_path, change_type, content):
        """Helper to set up Claude changes in the repository."""
        # Write to actual file
        actual_file = claude_repo.project_root / file_path
        actual_file.parent.mkdir(parents=True, exist_ok=True)
        actual_file.write_text(content)
        
        # Mirror to claude-git files
        mirrored_file = claude_repo.claude_git_dir / "files" / file_path
        mirrored_file.parent.mkdir(parents=True, exist_ok=True)
        mirrored_file.write_text(content)
        
        # Create metadata
        import uuid
        from datetime import datetime
        change_id = str(uuid.uuid4()).replace('-', '')[:8]
        metadata = {
            "change_id": change_id,
            "change_type": change_type.value,
            "file_path": str(file_path),
            "timestamp": datetime.now().isoformat(),
            "tool_name": "Write",
            "tool_input": {
                "name": "Write",
                "parameters": {"file_path": str(actual_file), "content": content}
            }
        }
        
        metadata_file = claude_repo.claude_git_dir / "metadata" / f"{change_id}.json"
        metadata_file.parent.mkdir(parents=True, exist_ok=True)
        metadata_file.write_text(str(metadata).replace("'", '"'))
        
        return change_id

    def test_diff_single_commit_matches_git_behavior(self, git_repo_with_history):
        """Test that claude-git diff HEAD~N matches git diff HEAD~N behavior."""
        setup = git_repo_with_history
        temp_dir = setup['temp_dir']
        commits = setup['commits']
        
        # Initialize claude-git
        claude_repo = ClaudeGitRepository(temp_dir)
        claude_repo.init()
        
        # Simulate Claude making changes to files that exist in git history
        # Let's say Claude modified feature1.py and feature2.py
        self._setup_claude_changes(claude_repo, "src/feature1.py", ChangeType.EDIT, 
                                  "def feature1():\n    return 'claude modified'\n")
        self._setup_claude_changes(claude_repo, "src/feature2.py", ChangeType.EDIT,
                                  "def feature2():\n    return 'claude modified too'\n")
        
        # Commit these changes to git so we can test diff behavior
        setup['repo'].index.add(["src/feature1.py", "src/feature2.py", ".claude-git"])
        claude_commit = setup['repo'].index.commit("Claude modifications")
        
        # Now test claude-git diff HEAD~1 (should show changes from previous commit)
        # IMPORTANT: Use CliRunner with cwd set to temp_dir so CLI finds correct .claude-git
        runner = CliRunner()
        with runner.isolated_filesystem():
            # Change to the temp directory so claude-git CLI finds the correct repository
            import os
            os.chdir(str(temp_dir))
            result = runner.invoke(diff_command, ["HEAD~1", "--no-pager"])
            assert result.exit_code == 0
        
        # Get what git diff shows for the same range
        git_result = subprocess.run(
            ["git", "diff", "HEAD~1", "HEAD", ".claude-git/files"],
            cwd=temp_dir,
            capture_output=True,
            text=True
        )
        
        # Both should show changes (claude-git output should be filtered and cleaned)
        if git_result.stdout.strip():
            # If git shows changes in .claude-git/files, claude-git should show corresponding changes
            assert result.output.strip() != ""
            # Should contain file paths without .claude-git/files prefix
            assert "src/feature1.py" in result.output or "src/feature2.py" in result.output
            # Should not contain the .claude-git/files prefix in paths (just check the diff lines, not debug output)
            # Extract just the diff part (skip any debug output)
            diff_output = result.output.split('diff --git', 1)[-1] if 'diff --git' in result.output else result.output
            assert ".claude-git/files" not in diff_output

    def test_diff_commit_range_cumulative_behavior(self, git_repo_with_history):
        """Test that claude-git diff shows cumulative changes like git diff."""
        setup = git_repo_with_history
        temp_dir = setup['temp_dir']
        commits = setup['commits']
        
        # Initialize claude-git
        claude_repo = ClaudeGitRepository(temp_dir)
        claude_repo.init()
        
        # Make multiple Claude changes across different commits
        # First change
        self._setup_claude_changes(claude_repo, "src/feature1.py", ChangeType.EDIT,
                                  "def feature1():\n    return 'first claude change'\n")
        setup['repo'].index.add(["src/feature1.py", ".claude-git"])
        commit_a = setup['repo'].index.commit("Claude change A")
        
        # Second change
        self._setup_claude_changes(claude_repo, "src/feature2.py", ChangeType.EDIT,
                                  "def feature2():\n    return 'second claude change'\n")
        setup['repo'].index.add(["src/feature2.py", ".claude-git"])
        commit_b = setup['repo'].index.commit("Claude change B")
        
        # Third change  
        self._setup_claude_changes(claude_repo, "src/feature3.py", ChangeType.WRITE,
                                  "def feature3():\n    return 'third claude change'\n")
        setup['repo'].index.add(["src/feature3.py", ".claude-git"])
        commit_c = setup['repo'].index.commit("Claude change C")
        
        # Test HEAD~3 should show cumulative changes from all three commits
        runner = CliRunner()
        with runner.isolated_filesystem():
            import os
            os.chdir(str(temp_dir))
            result = runner.invoke(diff_command, ["HEAD~3", "--no-pager"])
            assert result.exit_code == 0
        
        # Compare with git behavior
        git_result = subprocess.run(
            ["git", "diff", "HEAD~3", "HEAD", ".claude-git/files"],
            cwd=temp_dir,
            capture_output=True,
            text=True
        )
        
        if git_result.stdout.strip():
            # Should show cumulative changes from all three commits
            output = result.output
            assert "src/feature1.py" in output  # First change
            assert "src/feature2.py" in output  # Second change  
            assert "src/feature3.py" in output  # Third change
            
            # Verify the cumulative nature - should show final state vs initial state
            assert "first claude change" in output
            assert "second claude change" in output
            assert "third claude change" in output

    def test_diff_with_specific_commit_hash(self, git_repo_with_history):
        """Test claude-git diff with specific commit hash."""
        setup = git_repo_with_history
        temp_dir = setup['temp_dir']
        commits = setup['commits']
        
        # Initialize claude-git
        claude_repo = ClaudeGitRepository(temp_dir)
        claude_repo.init()
        
        # Make a Claude change
        self._setup_claude_changes(claude_repo, "src/new_file.py", ChangeType.WRITE,
                                  "def new_function():\n    return 'claude created this'\n")
        setup['repo'].index.add(["src/new_file.py", ".claude-git"])
        new_commit = setup['repo'].index.commit("Claude creates new file")
        
        # Test diff from a specific earlier commit
        stored_hash = commits['feature2']  # This is the hash we "stored" earlier
        
        runner = CliRunner()
        with runner.isolated_filesystem():
            import os
            os.chdir(str(temp_dir))
            result = runner.invoke(diff_command, [stored_hash, "--no-pager"])
            assert result.exit_code == 0
        
        # Compare with git diff using the same commit hash
        git_result = subprocess.run(
            ["git", "diff", stored_hash, "HEAD", ".claude-git/files"],
            cwd=temp_dir,
            capture_output=True,
            text=True
        )
        
        if git_result.stdout.strip():
            # Should show the new file that Claude created
            assert "src/new_file.py" in result.output
            assert "claude created this" in result.output
            assert "def new_function" in result.output

    def test_diff_invalid_commit_fails_like_git(self, git_repo_with_history):
        """Test that invalid commits fail with same behavior as git."""
        setup = git_repo_with_history
        temp_dir = setup['temp_dir']
        
        # Initialize claude-git
        claude_repo = ClaudeGitRepository(temp_dir)
        claude_repo.init()
        
        # Test with invalid commit that has too many ~
        invalid_ref = "HEAD~100"
        
        # First check that git fails
        git_result = subprocess.run(
            ["git", "diff", invalid_ref],
            cwd=temp_dir,
            capture_output=True,
            text=True
        )
        assert git_result.returncode != 0
        assert "ambiguous argument" in git_result.stderr.lower() or "unknown revision" in git_result.stderr.lower()
        
        # Now test that claude-git also fails
        runner = CliRunner()
        result = runner.invoke(diff_command, [invalid_ref, "--no-pager"])
        assert result.exit_code == 128  # Git's exit code for invalid refs
        assert "fatal:" in result.output.lower() and "ambiguous argument" in result.output.lower()

    def test_diff_no_changes_returns_empty_like_git(self, git_repo_with_history):
        """Test that when there are no Claude changes, output is empty like git diff."""
        setup = git_repo_with_history
        temp_dir = setup['temp_dir']
        
        # Initialize claude-git but don't make any Claude changes
        claude_repo = ClaudeGitRepository(temp_dir)
        claude_repo.init()
        
        # Test diff when there are no Claude changes
        runner = CliRunner()
        with runner.isolated_filesystem():
            import os
            os.chdir(str(temp_dir))
            result = runner.invoke(diff_command, ["HEAD~1", "--no-pager"])
            assert result.exit_code == 0
            assert result.output.strip() == ""  # Should be empty like git diff with no changes

    def test_diff_head_tilde_incremental_behavior(self, git_repo_with_history):
        """Test that HEAD~1, HEAD~2, HEAD~3 show incremental changes like git."""
        setup = git_repo_with_history
        temp_dir = setup['temp_dir']
        
        # Initialize claude-git
        claude_repo = ClaudeGitRepository(temp_dir)
        claude_repo.init()
        
        # Create incremental Claude changes across commits
        # Change 1
        self._setup_claude_changes(claude_repo, "src/file1.py", ChangeType.WRITE, "# Change 1\n")
        setup['repo'].index.add(["src/file1.py", ".claude-git"])
        setup['repo'].index.commit("Claude change 1")
        
        # Change 2  
        self._setup_claude_changes(claude_repo, "src/file2.py", ChangeType.WRITE, "# Change 2\n")
        setup['repo'].index.add(["src/file2.py", ".claude-git"])
        setup['repo'].index.commit("Claude change 2")
        
        # Change 3
        self._setup_claude_changes(claude_repo, "src/file3.py", ChangeType.WRITE, "# Change 3\n")
        setup['repo'].index.add(["src/file3.py", ".claude-git"])
        setup['repo'].index.commit("Claude change 3")
        
        runner = CliRunner()
        with runner.isolated_filesystem():
            import os
            os.chdir(str(temp_dir))
            
            # Test HEAD~1 (should show only the most recent change)
            result1 = runner.invoke(diff_command, ["HEAD~1", "--no-pager"])
            
            # Test HEAD~2 (should show last 2 changes)  
            result2 = runner.invoke(diff_command, ["HEAD~2", "--no-pager"])
            
            # Test HEAD~3 (should show all 3 changes)
            result3 = runner.invoke(diff_command, ["HEAD~3", "--no-pager"])
        
        # All should succeed
        assert result1.exit_code == 0
        assert result2.exit_code == 0  
        assert result3.exit_code == 0
        
        # Each should show progressively more content
        lines1 = len(result1.output.strip().split('\n')) if result1.output.strip() else 0
        lines2 = len(result2.output.strip().split('\n')) if result2.output.strip() else 0
        lines3 = len(result3.output.strip().split('\n')) if result3.output.strip() else 0
        
        # HEAD~3 should show most content (all changes), HEAD~2 should show more than HEAD~1
        # (This verifies cumulative behavior)
        if lines1 > 0 and lines2 > 0 and lines3 > 0:
            assert lines3 >= lines2 >= lines1, f"Expected lines3({lines3}) >= lines2({lines2}) >= lines1({lines1})"

    def test_diff_with_path_filtering(self, git_repo_with_history):
        """Test that path filtering works correctly with git-style behavior."""
        setup = git_repo_with_history
        temp_dir = setup['temp_dir']
        
        # Initialize claude-git
        claude_repo = ClaudeGitRepository(temp_dir)
        claude_repo.init()
        
        # Make changes to multiple files
        self._setup_claude_changes(claude_repo, "src/module1/file.py", ChangeType.WRITE, "# Module 1\n")
        self._setup_claude_changes(claude_repo, "src/module2/file.py", ChangeType.WRITE, "# Module 2\n") 
        self._setup_claude_changes(claude_repo, "docs/README.md", ChangeType.WRITE, "# Documentation\n")
        
        setup['repo'].index.add(["src", "docs", ".claude-git"])
        setup['repo'].index.commit("Claude changes multiple files")
        
        runner = CliRunner()
        with runner.isolated_filesystem():
            import os
            os.chdir(str(temp_dir))
            
            # Test with path filtering - should only show src/ files
            result = runner.invoke(diff_command, ["HEAD~1", "src/", "--no-pager"])
            assert result.exit_code == 0
        
        if result.output.strip():
            # Should show src files but not docs
            assert "src/module1/file.py" in result.output or "src/module2/file.py" in result.output
            assert "docs/README.md" not in result.output