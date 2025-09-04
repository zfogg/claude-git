"""
Worktree management for multi-session Claude development.

This module provides the core functionality for creating, managing, and
synchronizing git worktrees for individual Claude Code sessions.
"""

import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


class WorktreeManager:
    """Manages git worktrees for multi-session Claude development."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.claude_git_path = self.project_root / ".claude-git"
        self.worktree_base = self.claude_git_path / "worktree"

        # Initialize .claude-git if needed
        self._ensure_claude_git_initialized()

    def _ensure_claude_git_initialized(self) -> None:
        """Initialize .claude-git repository if it doesn't exist."""
        if not self.claude_git_path.exists():
            os.makedirs(self.claude_git_path)

        if not (self.claude_git_path / ".git").exists():
            # Initialize git repo
            subprocess.run(["git", "init"], cwd=self.claude_git_path, check=True)

            # Create initial commit
            subprocess.run(["git", "add", "."], cwd=self.claude_git_path)
            subprocess.run(
                [
                    "git",
                    "commit",
                    "--allow-empty",
                    "-m",
                    "Initialize claude-git repository",
                ],
                cwd=self.claude_git_path,
                check=True,
            )

            print("✅ Initialized .claude-git repository")

    def create_session_worktree(self, session_id: str, user_branch: str) -> Path:
        """
        Create a new worktree for a Claude session working on a specific branch.

        Args:
            session_id: Unique identifier for the Claude session
            user_branch: Branch from user repository that Claude will work on

        Returns:
            Path to the created worktree directory
        """
        worktree_name = f"{session_id}-{user_branch}"
        worktree_path = self.worktree_base / worktree_name
        claude_branch = f"claude-{worktree_name}"

        # Ensure worktree base directory exists
        os.makedirs(self.worktree_base, exist_ok=True)

        try:
            # Ensure user branch exists in .claude-git repo
            self._ensure_branch_exists(user_branch)

            # Create worktree from user branch
            subprocess.run(
                [
                    "git",
                    "worktree",
                    "add",
                    "-b",
                    claude_branch,
                    str(worktree_path),
                    user_branch,
                ],
                cwd=self.claude_git_path,
                check=True,
            )

            # Set up session metadata
            self._create_session_metadata(session_id, user_branch, worktree_path)

            print(
                f"✅ Created worktree for session {session_id} on branch {user_branch}"
            )
            print(f"   Path: {worktree_path}")

            return worktree_path

        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to create worktree: {e}")

    def _ensure_branch_exists(self, user_branch: str) -> None:
        """Ensure the user branch exists in .claude-git repository."""
        # Check if branch exists
        result = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{user_branch}"],
            cwd=self.claude_git_path,
            capture_output=True,
        )

        if result.returncode != 0:
            # Branch doesn't exist, create it from main or current HEAD
            try:
                subprocess.run(
                    ["git", "branch", user_branch, "HEAD"],
                    cwd=self.claude_git_path,
                    check=True,
                )
                print(f"Created branch {user_branch} in .claude-git")
            except subprocess.CalledProcessError:
                # If that fails, create orphan branch
                subprocess.run(
                    ["git", "checkout", "--orphan", user_branch],
                    cwd=self.claude_git_path,
                    check=True,
                )
                subprocess.run(
                    [
                        "git",
                        "commit",
                        "--allow-empty",
                        "-m",
                        f"Initialize {user_branch}",
                    ],
                    cwd=self.claude_git_path,
                    check=True,
                )
                subprocess.run(["git", "checkout", "main"], cwd=self.claude_git_path)

    def _create_session_metadata(
        self, session_id: str, user_branch: str, worktree_path: Path
    ) -> None:
        """Create metadata file for session tracking."""
        metadata = {
            "session_id": session_id,
            "user_branch": user_branch,
            "worktree_path": str(worktree_path),
            "created_at": datetime.now().isoformat(),
            "status": "active",
        }

        metadata_path = worktree_path / ".claude-session.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

    def remove_session_worktree(self, session_id: str, user_branch: str) -> None:
        """Remove a session worktree and clean up."""
        worktree_name = f"{session_id}-{user_branch}"
        worktree_path = self.worktree_base / worktree_name
        claude_branch = f"claude-{worktree_name}"

        if not worktree_path.exists():
            print(f"⚠️  Worktree {worktree_name} does not exist")
            return

        try:
            # Remove worktree
            subprocess.run(
                ["git", "worktree", "remove", str(worktree_path)],
                cwd=self.claude_git_path,
                check=True,
            )

            # Remove the Claude branch (optional, keeps history if commented out)
            subprocess.run(
                ["git", "branch", "-D", claude_branch],
                cwd=self.claude_git_path,
                check=True,
            )

            print(f"✅ Removed worktree for session {session_id} on {user_branch}")

        except subprocess.CalledProcessError as e:
            print(f"⚠️  Error removing worktree: {e}")

    def get_active_sessions(self, user_branch: Optional[str] = None) -> List[Dict]:
        """Get list of active Claude sessions."""
        sessions = []

        if not self.worktree_base.exists():
            return sessions

        for worktree_dir in self.worktree_base.iterdir():
            if not worktree_dir.is_dir():
                continue

            metadata_file = worktree_dir / ".claude-session.json"
            if not metadata_file.exists():
                continue

            try:
                with open(metadata_file) as f:
                    metadata = json.load(f)

                # Filter by branch if specified
                if user_branch and metadata.get("user_branch") != user_branch:
                    continue

                # Add runtime status information
                metadata["uncommitted_changes"] = self._count_uncommitted_changes(
                    worktree_dir
                )
                metadata["last_activity"] = self._get_last_activity(worktree_dir)

                sessions.append(metadata)

            except (json.JSONDecodeError, KeyError) as e:
                print(f"⚠️  Invalid session metadata in {worktree_dir}: {e}")

        return sorted(sessions, key=lambda s: s.get("created_at", ""))

    def _count_uncommitted_changes(self, worktree_path: Path) -> int:
        """Count uncommitted changes in a worktree."""
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=worktree_path,
                capture_output=True,
                text=True,
                check=True,
            )

            return len([line for line in result.stdout.split("\n") if line.strip()])
        except subprocess.CalledProcessError:
            return 0

    def _get_last_activity(self, worktree_path: Path) -> str:
        """Get timestamp of last activity in worktree."""
        try:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%ci"],
                cwd=worktree_path,
                capture_output=True,
                text=True,
                check=True,
            )

            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return "unknown"

    def recover_session_worktree(self, session_id: str) -> List[Path]:
        """
        Recover worktrees from a crashed or interrupted Claude session.

        Returns list of worktree paths that belong to the session.
        """
        recovered_worktrees = []

        if not self.worktree_base.exists():
            return recovered_worktrees

        # Find all worktrees for this session
        for worktree_dir in self.worktree_base.iterdir():
            if worktree_dir.name.startswith(f"{session_id}-"):
                recovered_worktrees.append(worktree_dir)

        if recovered_worktrees:
            print(
                f"🔄 Found {len(recovered_worktrees)} worktrees for session {session_id}:"
            )
            for worktree in recovered_worktrees:
                branch = worktree.name.split("-", 1)[1]  # Extract branch name
                changes = self._count_uncommitted_changes(worktree)
                print(f"   {branch}: {changes} uncommitted changes")

        return recovered_worktrees

    def cleanup_inactive_sessions(self, max_age_hours: int = 24) -> None:
        """Clean up worktrees from inactive sessions."""
        from datetime import datetime, timedelta

        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)

        for session in self.get_active_sessions():
            created_at = datetime.fromisoformat(session["created_at"])

            if created_at < cutoff_time and session["uncommitted_changes"] == 0:
                print(
                    f"🧹 Cleaning up inactive session: {session['session_id']} ({session['user_branch']})"
                )
                self.remove_session_worktree(
                    session["session_id"], session["user_branch"]
                )

    def sync_user_changes_to_claude_git(
        self, changed_files: List[str], current_branch: str
    ) -> None:
        """Sync user changes from main repo to .claude-git."""
        if not changed_files:
            return

        # Copy changed files to .claude-git
        for file_path in changed_files:
            src_file = self.project_root / file_path
            dst_file = self.claude_git_path / file_path

            if src_file.exists():
                # Ensure destination directory exists
                os.makedirs(dst_file.parent, exist_ok=True)
                shutil.copy2(src_file, dst_file)

        # Commit changes to .claude-git
        try:
            subprocess.run(["git", "add", "."], cwd=self.claude_git_path, check=True)

            commit_message = (
                f"User changes from {current_branch}: {', '.join(changed_files[:3])}"
            )
            if len(changed_files) > 3:
                commit_message += f" and {len(changed_files) - 3} more"

            subprocess.run(
                ["git", "commit", "-m", commit_message],
                cwd=self.claude_git_path,
                check=True,
            )

            print(f"✅ Synced {len(changed_files)} user changes to .claude-git")

        except subprocess.CalledProcessError as e:
            print(f"⚠️  Error syncing user changes: {e}")

    def sync_claude_changes_to_user_repo(self, user_branch: str) -> None:
        """Sync changes from .claude-git back to user's working directory."""
        # Get changed files since last sync
        try:
            # Use a tag to track last sync point
            sync_tag = "last-user-sync"

            # Get files changed since last sync
            result = subprocess.run(
                ["git", "diff", "--name-only", f"{sync_tag}..HEAD"],
                cwd=self.claude_git_path,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                # No sync tag exists, sync all files
                result = subprocess.run(
                    ["git", "ls-files"],
                    cwd=self.claude_git_path,
                    capture_output=True,
                    text=True,
                    check=True,
                )

            changed_files = [f for f in result.stdout.split("\n") if f.strip()]

            # Copy files from .claude-git to user workspace
            for file_path in changed_files:
                src_file = self.claude_git_path / file_path
                dst_file = self.project_root / file_path

                if src_file.exists() and not file_path.startswith(
                    "."
                ):  # Skip .git files
                    # Ensure destination directory exists
                    os.makedirs(dst_file.parent, exist_ok=True)
                    shutil.copy2(src_file, dst_file)

            # Update sync marker
            subprocess.run(
                ["git", "tag", "-f", sync_tag, "HEAD"],
                cwd=self.claude_git_path,
                check=True,
            )

            print(f"✅ Synced {len(changed_files)} Claude changes to user workspace")

        except subprocess.CalledProcessError as e:
            print(f"⚠️  Error syncing Claude changes: {e}")
