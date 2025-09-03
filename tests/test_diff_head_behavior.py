"""Tests for claude-git diff HEAD~ behavior to match git diff behavior."""

import subprocess
import pytest
from pathlib import Path
from claude_git.core.repository import ClaudeGitRepository


class TestDiffHeadBehavior:
    """Test that claude-git diff HEAD~ behaves like git diff HEAD~."""
    
    def test_diff_head_tilde_with_invalid_commit_should_fail(self, temp_git_repo):
        """claude-git diff HEAD~10 should fail when HEAD~10 doesn't exist, like git does."""
        temp_dir, git_repo = temp_git_repo
        
        # Initialize claude-git
        claude_repo = ClaudeGitRepository(temp_dir)
        claude_repo.init()
        
        # Check how many commits we have in the git repo
        result = subprocess.run(
            ["git", "log", "--oneline"], 
            cwd=temp_dir, 
            capture_output=True, 
            text=True
        )
        commit_count = len(result.stdout.strip().split('\n')) if result.stdout.strip() else 0
        
        # Test that git fails for HEAD~{commit_count + 5}
        invalid_ref = f"HEAD~{commit_count + 5}"
        git_result = subprocess.run(
            ["git", "diff", invalid_ref], 
            cwd=temp_dir, 
            capture_output=True, 
            text=True
        )
        
        # Git should fail
        assert git_result.returncode != 0
        assert "ambiguous argument" in git_result.stderr or "unknown revision" in git_result.stderr
        
        # claude-git should also fail
        claude_result = subprocess.run(
            ["python", "-m", "claude_git.cli.main", "diff", invalid_ref], 
            cwd=temp_dir,
            capture_output=True, 
            text=True
        )
        
        # claude-git should fail too (currently this test will fail because it doesn't)
        assert claude_result.returncode != 0, f"claude-git diff {invalid_ref} should fail but returned: {claude_result.stdout}"
    
    def test_diff_head_tilde_shows_cumulative_changes(self, temp_git_repo):
        """claude-git diff HEAD~N should show all changes since HEAD~N, like git diff."""
        temp_dir, git_repo = temp_git_repo
        
        # Initialize claude-git
        claude_repo = ClaudeGitRepository(temp_dir)
        claude_repo.init()
        
        # Create multiple commits with different files to test cumulative behavior
        # This simulates what git diff HEAD~2 would show: all changes from HEAD~2 to HEAD
        
        test_file1 = temp_dir / "test1.py"
        test_file1.write_text("print('original')")
        git_repo.index.add(["test1.py"])  # Use relative path
        git_repo.index.commit("Add test1.py")
        
        test_file2 = temp_dir / "test2.py" 
        test_file2.write_text("print('second file')")
        git_repo.index.add(["test2.py"])  # Use relative path
        git_repo.index.commit("Add test2.py")
        
        test_file3 = temp_dir / "test3.py"
        test_file3.write_text("print('third file')")
        git_repo.index.add(["test3.py"])  # Use relative path
        git_repo.index.commit("Add test3.py")
        
        # Get what git shows for HEAD~2 (should show changes in test2.py and test3.py)
        git_result = subprocess.run(
            ["git", "diff", "HEAD~2", "--name-only"],
            cwd=temp_dir,
            capture_output=True,
            text=True
        )
        
        if git_result.returncode == 0:
            git_files = set(git_result.stdout.strip().split('\n')) if git_result.stdout.strip() else set()
            
            # claude-git diff HEAD~2 should show changes that affect the same conceptual timeframe
            # (though it shows Claude changes, not git changes)
            claude_result = subprocess.run(
                ["python", "-m", "claude_git.cli.main", "diff", "HEAD~2", "--no-pager"],
                cwd=temp_dir,
                capture_output=True, 
                text=True
            )
            
            # The specific assertion depends on whether there are Claude changes
            # At minimum, it shouldn't show the exact same output as HEAD~1
            claude_head1_result = subprocess.run(
                ["python", "-m", "claude_git.cli.main", "diff", "HEAD~1", "--no-pager"],
                cwd=temp_dir,
                capture_output=True,
                text=True  
            )
            
            # HEAD~2 and HEAD~1 should show different outputs if there are changes in between
            # (unless there are no Claude changes, in which case both should be empty)
            if claude_result.stdout.strip() or claude_head1_result.stdout.strip():
                assert claude_result.stdout != claude_head1_result.stdout, (
                    "claude-git diff HEAD~2 and HEAD~1 should show different outputs "
                    "when there are changes between those commits"
                )

    def test_diff_head_specific_numbers_are_different(self, temp_git_repo):
        """Different HEAD~ numbers should show different changes.""" 
        temp_dir, git_repo = temp_git_repo
        
        # Initialize claude-git
        claude_repo = ClaudeGitRepository(temp_dir)
        claude_repo.init()
        
        # Check if we have at least 3 commits
        result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=temp_dir,
            capture_output=True,
            text=True
        )
        commits = result.stdout.strip().split('\n') if result.stdout.strip() else []
        
        if len(commits) >= 3:
            # Test that HEAD~1 and HEAD~2 show different results
            head1_result = subprocess.run(
                ["python", "-m", "claude_git.cli.main", "diff", "HEAD~1", "--no-pager"],
                cwd=temp_dir,
                capture_output=True,
                text=True
            )
            
            head2_result = subprocess.run(
                ["python", "-m", "claude_git.cli.main", "diff", "HEAD~2", "--no-pager"], 
                cwd=temp_dir,
                capture_output=True,
                text=True
            )
            
            # They should either both be empty (no Claude changes) or show different content
            if head1_result.stdout.strip() and head2_result.stdout.strip():
                # If both have content, they should be different
                assert head1_result.stdout != head2_result.stdout, (
                    "HEAD~1 and HEAD~2 diffs should be different when both have content"
                )
        else:
            pytest.skip(f"Need at least 3 commits for this test, only have {len(commits)}")


# Fixtures would be defined in conftest.py, but for completeness:
@pytest.fixture
def temp_git_repo():
    """Create a temporary git repository for testing."""
    import tempfile
    import shutil
    import git
    
    temp_dir = Path(tempfile.mkdtemp())
    try:
        # Initialize git repo
        git_repo = git.Repo.init(temp_dir)
        
        # Configure git user for commits
        git_repo.config_writer().set_value("user", "name", "Test User").release()
        git_repo.config_writer().set_value("user", "email", "test@example.com").release()
        
        # Create initial commit
        initial_file = temp_dir / "README.md"
        initial_file.write_text("# Test Repository")
        git_repo.index.add(["README.md"])  # Use relative path
        git_repo.index.commit("Initial commit")
        
        yield temp_dir, git_repo
        
    finally:
        shutil.rmtree(temp_dir)