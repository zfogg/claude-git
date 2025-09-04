"""Tests for claude-git init safety checks."""

import tempfile
from pathlib import Path

import pytest
from git import Repo

from claude_git.core.git_native_repository import GitNativeRepository


@pytest.fixture
def temp_git_project():
    """Create a temporary git project for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        project_path = Path(temp_dir)

        # Initialize git repo
        main_repo = Repo.init(project_path)
        with main_repo.config_writer() as config:
            config.set_value("user", "name", "Test User")
            config.set_value("user", "email", "test@example.com")

        # Create test file and commit
        (project_path / "test.py").write_text("print('test')\n")
        main_repo.index.add(["test.py"])
        main_repo.index.commit("Initial commit")

        yield project_path


def test_init_refuses_to_overwrite_existing_git_native_repo(temp_git_project):
    """Test that init refuses to overwrite an existing git-native repository."""
    git_native = GitNativeRepository(temp_git_project)

    # Initialize first time - should work
    git_native.init()
    assert git_native.exists()

    # Try to initialize again - should fail
    git_native2 = GitNativeRepository(temp_git_project)
    with pytest.raises(ValueError, match="Claude-git already initialized"):
        git_native2.init()


def test_init_refuses_non_empty_claude_git_directory(temp_git_project):
    """Test that init refuses to initialize when .claude-git directory exists with content."""
    claude_git_dir = temp_git_project / ".claude-git"
    claude_git_dir.mkdir()

    # Create some content in .claude-git
    (claude_git_dir / "some_file.txt").write_text("existing content")

    # Try to initialize - should fail
    git_native = GitNativeRepository(temp_git_project)
    with pytest.raises(ValueError, match="already exists and is not empty"):
        git_native.init()


def test_init_allows_empty_claude_git_directory(temp_git_project):
    """Test that init works when .claude-git directory exists but is empty."""
    claude_git_dir = temp_git_project / ".claude-git"
    claude_git_dir.mkdir()

    # Directory exists but is empty - should work
    git_native = GitNativeRepository(temp_git_project)
    git_native.init()
    assert git_native.exists()


def test_init_requires_git_repository(temp_git_project):
    """Test that init requires a git repository to exist."""
    # Remove the .git directory
    import shutil

    shutil.rmtree(temp_git_project / ".git")

    # Try to initialize - should fail
    git_native = GitNativeRepository(temp_git_project)
    with pytest.raises(ValueError, match="No git repository found"):
        git_native.init()


def test_init_creates_proper_structure(temp_git_project):
    """Test that init creates the expected file structure."""
    git_native = GitNativeRepository(temp_git_project)
    git_native.init()

    # Verify expected structure
    assert (temp_git_project / ".claude-git").exists()
    assert (temp_git_project / ".claude-git" / ".git").exists()
    assert (temp_git_project / ".claude-git" / ".claude-git-config.json").exists()

    # Verify config file content
    config_file = temp_git_project / ".claude-git" / ".claude-git-config.json"
    import json

    config = json.loads(config_file.read_text())
    assert config["version"] == "2.0.0"
    assert config["architecture"] == "git-native-dual-repo"
    assert "main_repo_initial_commit" in config
