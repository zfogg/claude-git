#!/usr/bin/env python3
"""
Automated tests for claude-git mixed user/Claude workflow.

This test suite validates the dual-repository architecture by simulating
realistic development scenarios with mixed user and Claude changes.
"""

import subprocess
import tempfile
from pathlib import Path

import pytest
from git import Repo

from claude_git.core.git_native_repository import GitNativeRepository


class TestMixedWorkflow:
    """Test suite for mixed user/Claude development workflow."""

    @pytest.fixture
    def temp_mixed_project(self):
        """Create a temporary project with mixed user/Claude changes."""
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = Path(temp_dir)

            # Initialize main git repository
            main_repo = Repo.init(project_path)
            with main_repo.config_writer() as config:
                config.set_value("user", "name", "Test User")
                config.set_value("user", "email", "user@test.com")

            # Create initial user files
            (project_path / "main.py").write_text("def main():\n    pass\n")
            (project_path / "README.md").write_text("# Test Project\n")
            main_repo.index.add(["main.py", "README.md"])
            main_repo.index.commit("Initial user commit")

            # Initialize claude-git
            git_native = GitNativeRepository(project_path)
            git_native.init()

            yield project_path, git_native

    def test_user_then_claude_changes(self, temp_mixed_project):
        """Test user changes followed by Claude changes."""
        project_path, git_native = temp_mixed_project

        # Simulate user changes
        user_file = project_path / "user_feature.py"
        user_file.write_text(
            "# User created this feature\nclass UserFeature:\n    pass\n"
        )

        # Start Claude session
        git_native.session_start("feature-development")

        # Simulate Claude changes
        claude_file = project_path / "claude_helper.py"
        claude_file.write_text(
            "# Claude added this helper\ndef helper():\n    return 'helped'\n"
        )
        git_native.accumulate_change(
            str(claude_file), "Write", {"content": claude_file.read_text()}
        )

        # End Claude session
        thinking = "Added helper function to support user's feature implementation"
        commit_hash = git_native.session_end(thinking)

        # Validate results
        assert commit_hash != ""
        assert len(commit_hash) == 40

        # Check files exist in both repos
        assert (project_path / "user_feature.py").exists()
        assert (project_path / "claude_helper.py").exists()
        assert (git_native.claude_git_dir / "user_feature.py").exists()
        assert (git_native.claude_git_dir / "claude_helper.py").exists()

        # Validate commit message contains thinking
        commit = git_native.claude_repo.commit(commit_hash)
        assert thinking in commit.message

    def test_interleaved_changes(self, temp_mixed_project):
        """Test interleaved user and Claude changes."""
        project_path, git_native = temp_mixed_project

        # User change 1
        config_file = project_path / "config.py"
        config_file.write_text("DEBUG = True\n")

        # Claude session 1
        git_native.session_start("initial-setup")
        main_file = project_path / "main.py"
        main_file.write_text("def main():\n    print('Hello')\n")
        git_native.accumulate_change(str(main_file), "Edit", {})
        git_native.session_end("Added basic main function")

        # User change 2
        config_file.write_text("DEBUG = True\nLOG_LEVEL = 'INFO'\n")

        # Claude session 2
        git_native.session_start("enhancement")
        utils_file = project_path / "utils.py"
        utils_file.write_text("def utility():\n    return 'util'\n")
        git_native.accumulate_change(str(utils_file), "Write", {})
        git_native.session_end("Added utility functions")

        # Validate all files are synced
        for filename in ["config.py", "main.py", "utils.py"]:
            main_file = project_path / filename
            claude_file = git_native.claude_git_dir / filename

            assert main_file.exists()
            assert claude_file.exists()
            assert main_file.read_text() == claude_file.read_text()

    def test_file_synchronization_validation(self, temp_mixed_project):
        """Test comprehensive file synchronization validation."""
        project_path, git_native = temp_mixed_project

        # Create various file types
        test_files = {
            "code.py": "print('python code')\n",
            "data.json": '{"key": "value"}\n',
            "docs.md": "# Documentation\nContent here.\n",
            "script.sh": "#!/bin/bash\necho 'script'\n",
        }

        git_native.session_start("file-types-test")

        for filename, content in test_files.items():
            file_path = project_path / filename
            file_path.write_text(content)
            git_native.accumulate_change(str(file_path), "Write", {"content": content})

        commit_hash = git_native.session_end("Created various file types for testing")

        # Validate synchronization
        for filename in test_files:
            main_file = project_path / filename
            claude_file = git_native.claude_git_dir / filename

            assert main_file.exists(), f"Main repo missing {filename}"
            assert claude_file.exists(), f"Claude repo missing {filename}"

            main_content = main_file.read_text()
            claude_content = claude_file.read_text()
            assert main_content == claude_content, f"Content mismatch for {filename}"

        # Validate commit structure
        commit = git_native.claude_repo.commit(commit_hash)
        assert "Created various file types" in commit.message
        assert "Changes: 4" in commit.message  # Should show count of 4 changes

    def test_git_native_commands_integration(self, temp_mixed_project):
        """Test integration with claude-git CLI commands."""
        project_path, git_native = temp_mixed_project

        # Make some changes
        git_native.session_start("cli-test")

        test_file = project_path / "cli_test.py"
        test_file.write_text("# CLI integration test\nprint('testing')\n")
        git_native.accumulate_change(str(test_file), "Write", {})

        commit_hash = git_native.session_end("CLI integration test commit")

        # Test CLI commands work with this repository
        def run_claude_git(cmd_args):
            result = subprocess.run(
                ["python", "-m", "claude_git.cli.main"] + cmd_args,
                cwd=project_path,
                capture_output=True,
                text=True,
            )
            return result.stdout, result.stderr, result.returncode

        # Test status command
        stdout, stderr, returncode = run_claude_git(["status"])
        assert returncode == 0
        assert "Architecture: Git-native" in stdout

        # Test log command
        stdout, stderr, returncode = run_claude_git(["log"])
        assert returncode == 0
        assert commit_hash[:7] in stdout  # Git typically shows 7 chars in short format
        assert "CLI integration test commit" in stdout

    def test_error_handling_and_recovery(self, temp_mixed_project):
        """Test error handling in mixed workflow scenarios."""
        project_path, git_native = temp_mixed_project

        # Test session end without session start
        commit_hash = git_native.session_end("orphan commit")
        assert commit_hash == ""

        # Test accumulate change without session (immediate commit)
        standalone_file = project_path / "standalone.py"
        standalone_file.write_text("# Standalone change\n")

        # This should create immediate commit
        git_native.accumulate_change(str(standalone_file), "Write", {})

        # Verify immediate commit was created
        commits = list(git_native.claude_repo.iter_commits())
        immediate_commit = None
        for commit in commits:
            if "write standalone.py" in commit.message.lower():
                immediate_commit = commit
                break

        assert immediate_commit is not None
        assert "standalone.py" in immediate_commit.message


def test_repository_health_validation():
    """Test the repository health validation utility."""
    from test_file import test_repository_health

    # Test with current project
    project_root = Path(__file__).parent.parent
    health_results = test_repository_health(project_root)

    # Validate health check results
    assert isinstance(health_results, dict)
    assert "config_exists" in health_results
    assert "main_repo_valid" in health_results
    assert "claude_repo_valid" in health_results
    assert "has_commits" in health_results
    assert "files_synced" in health_results

    # For this working repository, all should pass
    assert all(health_results.values()), f"Health check failed: {health_results}"


if __name__ == "__main__":
    # Run tests directly
    pytest.main([__file__, "-v"])
