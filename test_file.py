#!/usr/bin/env python3
"""
Test utility for validating claude-git dual-repository functionality.

This script demonstrates mixed user/Claude workflow and validates sync behavior.
Original functions preserved, enhanced with repository testing capabilities.
"""

import subprocess
from pathlib import Path


def hello_world():
    """Simple test function."""
    print("Hello, world!")
    return "Hello, world!"


def goodbye_world():
    """User added this function manually."""
    print("Goodbye, world!")
    return "Goodbye, world!"


def run_git_command(repo_dir: str, cmd: list[str]) -> str:
    """Run git command in specified repository directory."""
    result = subprocess.run(
        ["git", "-C", repo_dir] + cmd, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def validate_file_sync(project_root: Path, filename: str) -> bool:
    """Check if file exists and is identical in both repositories."""
    main_file = project_root / filename
    claude_file = project_root / ".claude-git" / filename

    if not main_file.exists() or not claude_file.exists():
        return False

    return main_file.read_text() == claude_file.read_text()


def test_repository_health(project_root: Path) -> dict[str, bool]:
    """Comprehensive health check of claude-git repositories."""
    results = {}

    # Test 1: Configuration file exists
    config_file = project_root / ".claude-git" / ".claude-git-config.json"
    results["config_exists"] = config_file.exists()

    # Test 2: Both repositories are git repos
    results["main_repo_valid"] = (project_root / ".git").exists()
    results["claude_repo_valid"] = (project_root / ".claude-git" / ".git").exists()

    # Test 3: Recent commits in claude-git repo
    try:
        claude_commits = run_git_command(
            str(project_root / ".claude-git"), ["log", "--oneline"]
        )
        results["has_commits"] = len(claude_commits.strip()) > 0
    except subprocess.CalledProcessError:
        results["has_commits"] = False

    # Test 4: File synchronization working
    test_files = ["user_notes.txt", "test_file.py", "README.md"]
    sync_results = []
    for filename in test_files:
        if (project_root / filename).exists():
            sync_results.append(validate_file_sync(project_root, filename))

    results["files_synced"] = all(sync_results) if sync_results else True

    return results


def main():
    """Run comprehensive test suite."""
    project_root = Path(__file__).parent
    print(f"🔍 Testing claude-git in: {project_root}")

    # Run original functions
    print("\n🎉 Original Functions:")
    hello_world()
    goodbye_world()

    # Run health check
    health = test_repository_health(project_root)

    print("\n📊 Repository Health Check:")
    for test_name, passed in health.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {test_name}: {status}")

    all_passed = all(health.values())
    print(
        f"\n🎯 Overall Status: {'✅ HEALTHY' if all_passed else '❌ ISSUES DETECTED'}"
    )


if __name__ == "__main__":
    main()
