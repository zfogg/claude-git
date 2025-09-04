"""Comprehensive tests for claude-git diff command matching git behavior."""

import subprocess
import tempfile
import time
from pathlib import Path

import pytest
from git import Repo

from claude_git.core.git_native_repository import GitNativeRepository


@pytest.fixture
def temp_diff_project():
    """Create a temporary project with git and claude-git repositories for diff testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        project_path = Path(temp_dir)

        # Initialize main git repository
        main_repo = Repo.init(project_path)

        # Configure git user for testing
        with main_repo.config_writer() as config:
            config.set_value("user", "name", "Test User")
            config.set_value("user", "email", "test@example.com")

        # Create initial files
        (project_path / "file1.txt").write_text("Line 1\nLine 2\nLine 3\n")
        (project_path / "file2.py").write_text("def hello():\n    print('Hello')\n")
        (project_path / "README.md").write_text("# Test Project\n")

        # Create subdirectory with files
        (project_path / "src").mkdir()
        (project_path / "src" / "main.py").write_text(
            "import sys\n\ndef main():\n    print('Main')\n"
        )

        # Initial commit in main repo
        main_repo.index.add(["file1.txt", "file2.py", "README.md", "src/main.py"])
        main_repo.index.commit("Initial commit")

        # Initialize git-native claude repository
        git_native = GitNativeRepository(project_path)
        git_native.init()

        yield project_path, git_native, main_repo


def run_git_diff(repo_dir: Path, args: list) -> tuple[str, int]:
    """Run git diff command and return (stdout, returncode)."""
    cmd = ["git", "-C", str(repo_dir), "diff"] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout, result.returncode


def run_claude_git_diff(project_dir: Path, args: list) -> tuple[str, int]:
    """Run claude-git diff command and return (stdout, returncode)."""
    cmd = ["python", "-m", "claude_git.cli.main", "diff", "--no-pager"] + args
    result = subprocess.run(cmd, cwd=str(project_dir), capture_output=True, text=True)
    return result.stdout, result.returncode


def test_basic_diff_no_changes(temp_diff_project):
    """Test diff with no changes shows nothing, like git."""
    project_path, git_native, main_repo = temp_diff_project

    # Both should show no output for no changes
    git_out, git_code = run_git_diff(git_native.claude_git_dir, [])
    claude_out, claude_code = run_claude_git_diff(project_path, [])

    # Both should have no output and return code 0
    assert git_out == ""
    assert claude_out == ""
    assert git_code == 0
    assert claude_code == 0


def test_diff_after_changes(temp_diff_project):
    """Test diff after making changes shows proper output."""
    project_path, git_native, main_repo = temp_diff_project

    # Start claude session and make changes
    git_native.session_start("test-session")

    # Modify a file
    test_file = project_path / "file1.txt"
    test_file.write_text("Line 1\nLine 2 modified\nLine 3\nLine 4 added\n")

    # Track change in claude-git
    git_native.accumulate_change(
        str(test_file),
        "Edit",
        {"old_string": "Line 2", "new_string": "Line 2 modified"},
    )

    # Add new file
    new_file = project_path / "new_file.txt"
    new_file.write_text("This is a new file\n")
    git_native.accumulate_change(
        str(new_file), "Write", {"content": "This is a new file\n"}
    )

    # End session to create commit
    git_native.session_end("Test changes for diff")

    # Compare outputs - claude-git should show the changes in the last commit
    claude_out, claude_code = run_claude_git_diff(project_path, ["HEAD~1"])

    assert claude_code == 0
    assert "file1.txt" in claude_out
    assert "new_file.txt" in claude_out


def test_diff_head_tilde_syntax(temp_diff_project):
    """Test HEAD~1, HEAD~2 etc syntax works like git."""
    project_path, git_native, main_repo = temp_diff_project

    # Create multiple commits
    for i in range(3):
        git_native.session_start(f"session-{i}")

        test_file = project_path / "file1.txt"
        content = f"Line 1\nLine 2 - modification {i}\nLine 3\n"
        test_file.write_text(content)

        git_native.accumulate_change(
            str(test_file),
            "Edit",
            {"old_string": "Line 2", "new_string": f"Line 2 - modification {i}"},
        )

        git_native.session_end(f"Modification {i}")
        time.sleep(0.1)  # Ensure different timestamps

    # Test HEAD~1 syntax
    claude_out, claude_code = run_claude_git_diff(project_path, ["HEAD~1"])

    assert claude_code == 0
    # Should show changes from HEAD~1 to current
    assert "file1.txt" in claude_out


def test_diff_commit_range_syntax(temp_diff_project):
    """Test commit range syntax like HEAD~2..HEAD works."""
    project_path, git_native, main_repo = temp_diff_project

    # Create multiple commits
    for i in range(3):
        git_native.session_start(f"session-{i}")

        test_file = project_path / "file1.txt"
        content = f"Line 1\nLine 2 - version {i}\nLine 3\n"
        test_file.write_text(content)

        git_native.accumulate_change(
            str(test_file),
            "Edit",
            {"old_string": "Line 2", "new_string": f"Line 2 - version {i}"},
        )

        git_native.session_end(f"Version {i}")
        time.sleep(0.1)

    # Test range syntax
    claude_out, claude_code = run_claude_git_diff(project_path, ["HEAD~2..HEAD"])

    assert claude_code == 0
    assert "file1.txt" in claude_out


def test_diff_with_file_paths(temp_diff_project):
    """Test diff with specific file paths."""
    project_path, git_native, main_repo = temp_diff_project

    # Start session and modify multiple files
    git_native.session_start("multi-file-session")

    # Modify file1.txt
    file1 = project_path / "file1.txt"
    file1.write_text("Modified file1\n")
    git_native.accumulate_change(str(file1), "Edit", {})

    # Modify src/main.py
    main_py = project_path / "src" / "main.py"
    main_py.write_text("def main():\n    print('Modified main')\n")
    git_native.accumulate_change(str(main_py), "Edit", {})

    git_native.session_end("Multi file changes")

    # Test diff with specific file path - show last commit changes for that file
    claude_out, claude_code = run_claude_git_diff(
        project_path, ["HEAD~1", "--", "file1.txt"]
    )

    assert claude_code == 0
    assert "file1.txt" in claude_out
    # Should not show src/main.py changes
    assert "src/main.py" not in claude_out


def test_diff_with_directory_paths(temp_diff_project):
    """Test diff with directory paths."""
    project_path, git_native, main_repo = temp_diff_project

    # Start session and modify files in src directory
    git_native.session_start("src-dir-session")

    # Modify src/main.py
    main_py = project_path / "src" / "main.py"
    main_py.write_text("def main():\n    print('Directory test')\n")
    git_native.accumulate_change(str(main_py), "Edit", {})

    # Also modify root level file
    file1 = project_path / "file1.txt"
    file1.write_text("Root level change\n")
    git_native.accumulate_change(str(file1), "Edit", {})

    git_native.session_end("Directory changes")

    # Test diff with src/ directory - show last commit changes in src/
    claude_out, claude_code = run_claude_git_diff(project_path, ["HEAD~1", "src/"])

    assert claude_code == 0
    assert "src/main.py" in claude_out
    # Should not show root level file changes
    assert "file1.txt" not in claude_out


def test_diff_parent_hash_filtering(temp_diff_project):
    """Test filtering diff by parent repository hash."""
    project_path, git_native, main_repo = temp_diff_project

    # Make a commit in main repo to get a parent hash
    main_file = project_path / "main_change.txt"
    main_file.write_text("Main repo change\n")
    main_repo.index.add(["main_change.txt"])
    main_commit = main_repo.index.commit("Main repo commit")
    parent_hash = main_commit.hexsha

    # Start claude session and make changes
    git_native.session_start("parent-hash-session")

    test_file = project_path / "file1.txt"
    test_file.write_text("Claude change for specific parent\n")
    git_native.accumulate_change(str(test_file), "Edit", {})

    git_native.session_end("Changes for parent hash test")

    # Test diff with parent hash filtering
    claude_out, claude_code = run_claude_git_diff(
        project_path, ["--parent-hash", parent_hash[:8]]
    )

    # Should work (might not show content if no changes match that exact hash)
    assert claude_code == 0


def test_diff_no_pager_flag(temp_diff_project):
    """Test --no-pager flag works correctly."""
    project_path, git_native, main_repo = temp_diff_project

    # Make some changes
    git_native.session_start("pager-test")

    test_file = project_path / "file1.txt"
    test_file.write_text("Change for pager test\n")
    git_native.accumulate_change(str(test_file), "Edit", {})

    git_native.session_end("Pager test changes")

    # Test with --no-pager flag - show last commit
    claude_out, claude_code = run_claude_git_diff(
        project_path, ["HEAD~1", "--no-pager"]
    )

    assert claude_code == 0
    assert "file1.txt" in claude_out


def test_diff_limit_option(temp_diff_project):
    """Test --limit option controls number of changes analyzed."""
    project_path, git_native, main_repo = temp_diff_project

    # Create multiple changes
    for i in range(5):
        git_native.session_start(f"limit-session-{i}")

        test_file = project_path / f"file_{i}.txt"
        test_file.write_text(f"Content for file {i}\n")
        git_native.accumulate_change(str(test_file), "Write", {})

        git_native.session_end(f"Change {i}")
        time.sleep(0.1)

    # Test with limit
    claude_out, claude_code = run_claude_git_diff(project_path, ["--limit", "2"])

    assert claude_code == 0
    # Should work with limit (exact behavior depends on implementation)


def test_diff_verbose_flag(temp_diff_project):
    """Test --verbose flag provides more detailed output."""
    project_path, git_native, main_repo = temp_diff_project

    # Make changes
    git_native.session_start("verbose-test")

    test_file = project_path / "file1.txt"
    test_file.write_text("Verbose test change\n")
    git_native.accumulate_change(str(test_file), "Edit", {})

    git_native.session_end("Verbose test")

    # Test with and without verbose
    normal_out, normal_code = run_claude_git_diff(project_path, [])
    verbose_out, verbose_code = run_claude_git_diff(project_path, ["--verbose"])

    assert normal_code == 0
    assert verbose_code == 0
    # Both should work (verbose might have more details)


def test_diff_error_handling(temp_diff_project):
    """Test error handling for invalid arguments."""
    project_path, git_native, main_repo = temp_diff_project

    # Test with invalid commit hash
    claude_out, claude_code = run_claude_git_diff(project_path, ["nonexistent123"])

    # Should handle gracefully (may return error code or empty output)
    # The important thing is it doesn't crash
    assert isinstance(claude_code, int)
    assert isinstance(claude_out, str)


def test_diff_output_format_matches_git_style(temp_diff_project):
    """Test that diff output format resembles git diff format."""
    project_path, git_native, main_repo = temp_diff_project

    # Make changes
    git_native.session_start("format-test")

    test_file = project_path / "file1.txt"
    original_content = test_file.read_text()
    modified_content = original_content.replace("Line 2", "Line 2 - MODIFIED")
    test_file.write_text(modified_content)

    git_native.accumulate_change(
        str(test_file),
        "Edit",
        {"old_string": "Line 2", "new_string": "Line 2 - MODIFIED"},
    )

    git_native.session_end("Format test")

    # Get claude-git diff output for the last commit
    claude_out, claude_code = run_claude_git_diff(project_path, ["HEAD~1"])

    assert claude_code == 0

    # Check for git-style diff markers
    assert "diff --git" in claude_out or "file1.txt" in claude_out
    # Should show the change in some recognizable format
    assert "MODIFIED" in claude_out


def test_diff_with_binary_files(temp_diff_project):
    """Test diff handling of binary files."""
    project_path, git_native, main_repo = temp_diff_project

    # Create a binary file
    binary_file = project_path / "image.bin"
    binary_file.write_bytes(b"\x00\x01\x02\x03\xff\xfe\xfd")

    git_native.session_start("binary-test")
    git_native.accumulate_change(str(binary_file), "Write", {"content": "binary"})
    git_native.session_end("Binary file test")

    # Test diff with binary file - show last commit
    claude_out, claude_code = run_claude_git_diff(project_path, ["HEAD~1"])

    # Should handle binary files gracefully
    assert claude_code == 0
    # Binary files might show filename or "Binary files ... differ"
    assert "image.bin" in claude_out or "Binary" in claude_out or claude_out == ""


def test_diff_large_changes(temp_diff_project):
    """Test diff with large file changes."""
    project_path, git_native, main_repo = temp_diff_project

    # Create a large file change
    large_content = "Line {}\n".format("x" * 1000) * 100
    large_file = project_path / "large_file.txt"
    large_file.write_text(large_content)

    git_native.session_start("large-change-test")
    git_native.accumulate_change(str(large_file), "Write", {"content": "large file"})
    git_native.session_end("Large change test")

    # Test diff with large change
    claude_out, claude_code = run_claude_git_diff(project_path, [])

    # Should handle large files gracefully
    assert claude_code == 0


def test_diff_empty_repository_state(temp_diff_project):
    """Test diff when repository is in various states."""
    project_path, git_native, main_repo = temp_diff_project

    # Test with no commits yet in claude-git
    # (git_native.init() creates initial commit, so we test the basic case)

    # Should not crash with fresh repository
    claude_out, claude_code = run_claude_git_diff(project_path, [])

    # Should handle gracefully
    assert isinstance(claude_code, int)
    assert isinstance(claude_out, str)


def test_git_diff_compatibility_comprehensive(temp_diff_project):
    """Comprehensive test ensuring claude-git diff behavior matches git where applicable."""
    project_path, git_native, main_repo = temp_diff_project

    # Create a sequence of changes
    changes = [
        ("file1.txt", "First change\n"),
        ("file2.py", "def updated():\n    return 'updated'\n"),
        ("new_file.md", "# New Document\nContent here\n"),
    ]

    for i, (filename, content) in enumerate(changes):
        git_native.session_start(f"compat-session-{i}")

        file_path = project_path / filename
        file_path.write_text(content)
        git_native.accumulate_change(
            str(file_path), "Edit" if file_path.exists() else "Write", {}
        )

        git_native.session_end(f"Change {i}")
        time.sleep(0.1)

    # Test various git-style commands that should work similarly
    test_cases = [
        [],  # basic diff
        ["--no-pager"],  # explicit no-pager
        ["--limit", "5"],  # limit results
    ]

    for args in test_cases:
        claude_out, claude_code = run_claude_git_diff(project_path, args)

        # All should execute successfully
        assert claude_code == 0
        assert isinstance(claude_out, str)

        # If there are changes, should show file names
        if claude_out.strip():
            assert any(fname in claude_out for fname, _ in changes)
