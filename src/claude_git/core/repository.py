"""Claude Git repository management using real git."""

import difflib
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import git
from git import Repo

from claude_git.models.change import Change
from claude_git.models.session import Session


class ClaudeGitRepository:
    """Manages a real git repository for Claude changes."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.claude_git_dir = self.project_root / ".claude-git"
        self.sessions_file = self.claude_git_dir / "sessions.json"
        self.config_file = self.claude_git_dir / "config.json"
        self._repo: Optional[Repo] = None

    @property
    def repo(self) -> Repo:
        """Get the git repository, initializing if needed."""
        if self._repo is None:
            self._repo = Repo(self.claude_git_dir)
        return self._repo

    def exists(self) -> bool:
        """Check if Claude Git repository exists."""
        return (
            self.claude_git_dir.exists()
            and (self.claude_git_dir / ".git").exists()
            and self.config_file.exists()
        )

    def init(self) -> None:
        """Initialize a new Claude Git repository."""
        # Create directory
        self.claude_git_dir.mkdir(exist_ok=True)

        # Initialize git repo
        self._repo = Repo.init(self.claude_git_dir)

        # Create config file
        config = {
            "version": "0.1.0",
            "created": datetime.now().isoformat(),
            "project_root": str(self.project_root),
        }
        self.config_file.write_text(json.dumps(config, indent=2))

        # Create sessions file
        self.sessions_file.write_text(json.dumps([], indent=2))

        # Initial commit
        self.repo.index.add([str(self.config_file.name), str(self.sessions_file.name)])
        self.repo.index.commit("Initial Claude Git repository")

        # Create main branch
        self.repo.create_head("main")

    def add_change(self, change: Change) -> str:
        """Add a change as a git commit and return commit hash."""
        # Ensure we're on the correct session branch
        session = self.get_session(change.session_id)
        if session:
            self._ensure_branch(session.branch_name)

        # Get current git hash of parent repository
        parent_repo_hash = self._get_parent_repo_hash()
        change.parent_repo_hash = parent_repo_hash

        # Capture parent repo status to detect human changes
        parent_repo_status = self._get_parent_repo_status()
        change.parent_repo_status = parent_repo_status

        # GIT-NATIVE APPROACH: Store actual file content in mirrored directory structure

        # Create mirrored file structure in claude-git repo
        relative_file_path = change.file_path.relative_to(self.project_root)
        mirrored_file = self.claude_git_dir / "files" / relative_file_path

        # Ensure directory structure exists
        mirrored_file.parent.mkdir(parents=True, exist_ok=True)

        # Store the actual new content of the file (after Claude's change)
        final_content = (
            change.new_content
            if change.new_content
            else change.file_path.read_text(encoding="utf-8")
        )
        mirrored_file.write_text(final_content, encoding="utf-8")

        # Create minimal metadata file for reference
        metadata_dir = self.claude_git_dir / "metadata"
        metadata_dir.mkdir(exist_ok=True)

        metadata_file = metadata_dir / f"{change.id}.json"
        metadata = {
            "id": change.id,
            "timestamp": change.timestamp.isoformat(),
            "change_type": change.change_type.value,
            "file_path": str(relative_file_path),
            "parent_repo_hash": parent_repo_hash,
            "tool_input": change.tool_input,
        }

        metadata_file.write_text(json.dumps(metadata, indent=2))

        # Stage the mirrored file and metadata
        self.repo.index.add(
            [
                str(mirrored_file.relative_to(self.claude_git_dir)),
                str(metadata_file.relative_to(self.claude_git_dir)),
            ]
        )

        # Create commit message with parent repo hash
        commit_msg = self._create_commit_message(change, parent_repo_hash)

        # Commit the change
        commit = self.repo.index.commit(commit_msg)

        # Update session metadata
        self._update_session_with_commit(change.session_id, commit.hexsha)

        return commit.hexsha

    def get_or_create_current_session(self) -> Session:
        """Get the current active session or create a new one."""
        sessions = self._load_sessions()

        # Look for active sessions
        active_sessions = [s for s in sessions if s.is_active]

        if active_sessions:
            # Return the most recent active session
            return max(active_sessions, key=lambda s: s.start_time)

        # Create new session with unique branch name
        session_id = str(uuid.uuid4())
        timestamp = datetime.now()
        base_branch_name = f"session-{timestamp.strftime('%Y-%m-%d-%H-%M')}"

        # Handle concurrent sessions in the same minute by adding seconds
        branch_name = base_branch_name
        counter = 0
        while branch_name in [h.name for h in self.repo.heads]:
            counter += 1
            if counter == 1:
                # First collision, add seconds
                branch_name = f"session-{timestamp.strftime('%Y-%m-%d-%H-%M-%S')}"
            else:
                # Multiple collisions, add counter
                branch_name = (
                    f"session-{timestamp.strftime('%Y-%m-%d-%H-%M-%S')}-{counter}"
                )

        session = Session(
            id=session_id,
            start_time=datetime.now(),
            branch_name=branch_name,
            project_path=self.project_root,
        )

        # Create branch for this session
        self._ensure_branch(branch_name)

        # Save session
        sessions.append(session)
        self._save_sessions(sessions)

        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """Get a session by ID."""
        sessions = self._load_sessions()
        return next((s for s in sessions if s.id == session_id), None)

    def list_sessions(self) -> List[Session]:
        """List all sessions."""
        return self._load_sessions()

    def get_commits_for_session(self, session_id: str) -> List[git.Commit]:
        """Get all commits for a specific session."""
        session = self.get_session(session_id)
        if not session:
            return []

        try:
            # Get commits from the session branch
            branch = self.repo.heads[session.branch_name]
            return list(self.repo.iter_commits(branch))
        except (git.exc.BadName, IndexError):
            return []

    def run_git_command(self, args: List[str]) -> str:
        """Run a git command on the Claude repository."""
        try:
            # Use getattr to dynamically call the git command method
            if not args:
                raise RuntimeError("No git command specified")

            command = args[0]
            command_args = args[1:] if len(args) > 1 else []

            git_method = getattr(self.repo.git, command)
            return git_method(*command_args)
        except AttributeError:
            raise RuntimeError(f"Unknown git command: {command}")
        except git.exc.GitCommandError as e:
            raise RuntimeError(f"Git command failed: {e}")

    def run_git_command_with_pager(self, args: List[str]) -> None:
        """Run a git command with pager support, respecting git configuration."""
        import os
        import subprocess

        try:
            if not args:
                raise RuntimeError("No git command specified")

            # Build the full git command
            cmd = ["git", "-C", str(self.claude_git_dir)] + args

            # Let git handle paging according to user's configuration
            env = os.environ.copy()

            # Run the command and let git handle paging
            result = subprocess.run(cmd, env=env, cwd=str(self.claude_git_dir))

            if result.returncode != 0:
                raise RuntimeError(
                    f"Git command failed with exit code {result.returncode}"
                )

        except FileNotFoundError:
            raise RuntimeError("Git command not found. Make sure git is installed.")
        except Exception as e:
            raise RuntimeError(f"Git command failed: {e}")

    def _ensure_branch(self, branch_name: str) -> None:
        """Ensure a branch exists and check it out."""
        try:
            # Check if branch exists
            if branch_name not in [h.name for h in self.repo.heads]:
                # Create new branch from main
                main_branch = (
                    self.repo.heads.main
                    if "main" in [h.name for h in self.repo.heads]
                    else self.repo.heads.master
                )
                self.repo.create_head(branch_name, main_branch)

            # Checkout the branch
            self.repo.heads[branch_name].checkout()
        except git.exc.GitCommandError:
            # If main/master doesn't exist, create from current HEAD
            if not self.repo.heads:
                self.repo.create_head(branch_name)
            else:
                self.repo.create_head(branch_name, self.repo.head.commit)
            self.repo.heads[branch_name].checkout()

    def _create_commit_message(
        self, change: Change, parent_repo_hash: Optional[str] = None
    ) -> str:
        """Create a descriptive commit message for a change."""
        file_name = change.file_path.name
        change_type = change.change_type.value

        if (
            change.change_type.name == "EDIT"
            and change.old_string
            and change.new_string
        ):
            # For edits, show what changed
            old_preview = (
                change.old_string[:50] + "..."
                if len(change.old_string) > 50
                else change.old_string
            )
            new_preview = (
                change.new_string[:50] + "..."
                if len(change.new_string) > 50
                else change.new_string
            )
            base_msg = f"{change_type}: {file_name}\n\n- {old_preview}\n+ {new_preview}"
        else:
            # For writes or other changes
            base_msg = (
                f"{change_type}: {file_name}\n\nUpdated by Claude at {change.timestamp}"
            )

        if parent_repo_hash:
            base_msg += f"\n\nParent repo: {parent_repo_hash[:8]}"

        return base_msg

    def _update_session_with_commit(self, session_id: str, commit_hash: str) -> None:
        """Update session metadata with new commit."""
        sessions = self._load_sessions()

        for session in sessions:
            if session.id == session_id:
                if not hasattr(session, "change_ids") or session.change_ids is None:
                    session.change_ids = []
                session.change_ids.append(commit_hash)
                break

        self._save_sessions(sessions)

    def _load_sessions(self) -> List[Session]:
        """Load sessions from the sessions file."""
        if not self.sessions_file.exists():
            return []

        try:
            sessions_data = json.loads(self.sessions_file.read_text())
            return [Session(**data) for data in sessions_data]
        except (json.JSONDecodeError, ValueError):
            return []

    def _save_sessions(self, sessions: List[Session]) -> None:
        """Save sessions to the sessions file."""
        sessions_data = [session.model_dump() for session in sessions]
        self.sessions_file.write_text(json.dumps(sessions_data, indent=2, default=str))

        # Commit the updated sessions file
        try:
            self.repo.index.add([str(self.sessions_file.name)])
            self.repo.index.commit(
                f"Update sessions metadata - {len(sessions)} sessions"
            )
        except git.exc.GitCommandError:
            # Ignore commit errors for sessions file updates
            pass

    def _create_patch(self, change: Change) -> str:
        """Create a patch file for a Claude change."""
        if change.change_type.name == "WRITE":
            # For new files, create a patch that adds the entire file
            lines = change.new_content.split("\n")
            patch_lines = [
                "--- /dev/null",
                f"+++ {change.file_path}",
                f"@@ -0,0 +1,{len(lines)} @@",
            ]
            patch_lines.extend(f"+{line}" for line in lines)
            return "\n".join(patch_lines)

        if (
            change.change_type.name == "EDIT"
            and change.old_string
            and change.new_string
        ):
            # For edits, create a patch showing the specific change
            # This is simplified - real implementation would need proper diff context
            return f"""--- {change.file_path}
+++ {change.file_path}
@@ -1,1 +1,1 @@
-{change.old_string}
+{change.new_string}
"""

        # Fallback for other change types
        return f"# Claude change {change.id}\n# Type: {change.change_type.value}\n# File: {change.file_path}\n"

    def _get_parent_repo_hash(self) -> Optional[str]:
        """Get the current git hash of the parent repository."""
        try:
            # Look for .git directory in parent project
            parent_git_dir = self.project_root / ".git"
            if not parent_git_dir.exists():
                return None

            from git import Repo as GitRepo

            parent_repo = GitRepo(self.project_root)
            return parent_repo.head.commit.hexsha
        except Exception:
            return None

    def _get_parent_repo_status(self) -> Optional[Dict]:
        """Get comprehensive status of parent repository to detect human changes."""
        try:
            parent_git_dir = self.project_root / ".git"
            if not parent_git_dir.exists():
                return None

            from git import Repo as GitRepo

            parent_repo = GitRepo(self.project_root)

            # Get porcelain status v2 for comprehensive change detection
            status_output = parent_repo.git.status(
                "--porcelain=v2", "--untracked-files=all"
            )

            # Parse status into structured data
            status_info = {
                "modified_files": [],
                "added_files": [],
                "deleted_files": [],
                "renamed_files": [],
                "copied_files": [],
                "untracked_files": [],
                "ignored_files": [],
                "file_hashes": {},
                "has_changes": bool(status_output.strip()),
            }

            for line in status_output.strip().split("\n"):
                if not line:
                    continue

                parts = line.split()
                if len(parts) < 2:
                    continue

                # Parse porcelain v2 format
                if line.startswith("1 "):  # Tracked file with changes
                    # Format: 1 <XY> <sub> <mH> <mI> <mW> <hH> <hI> <path>
                    xy_status = parts[1]
                    path = " ".join(parts[8:]) if len(parts) > 8 else parts[-1]

                    if "M" in xy_status:
                        status_info["modified_files"].append(path)
                    if "A" in xy_status:
                        status_info["added_files"].append(path)
                    if "D" in xy_status:
                        status_info["deleted_files"].append(path)

                elif line.startswith("2 "):  # Renamed file
                    # Format: 2 <XY> <sub> <mH> <mI> <mW> <hH> <hI> <X><score> <path><sep><origPath>
                    path_part = " ".join(parts[9:]) if len(parts) > 9 else parts[-1]
                    status_info["renamed_files"].append(path_part)

                elif line.startswith("? "):  # Untracked file
                    path = line[2:]  # Remove "? " prefix
                    # Skip .claude-git directory
                    if not path.startswith(".claude-git"):
                        status_info["untracked_files"].append(path)

                elif line.startswith("! "):  # Ignored file
                    path = line[2:]  # Remove "! " prefix
                    status_info["ignored_files"].append(path)

            # Get file hashes for modified files to detect content changes
            for modified_file in status_info["modified_files"]:
                try:
                    file_path = self.project_root / modified_file
                    if file_path.exists() and file_path.is_file():
                        import hashlib

                        content = file_path.read_bytes()
                        status_info["file_hashes"][modified_file] = hashlib.sha256(
                            content
                        ).hexdigest()[:16]
                except Exception:
                    continue

            return status_info

        except Exception:
            return None

    def detect_conflicts_with_human_changes(self, change: Change) -> Dict:
        """Analyze potential conflicts between Claude's change and human modifications."""
        conflicts = {
            "has_conflicts": False,
            "same_file_modified": False,
            "related_files_modified": [],
            "human_modifications": [],
            "recommendations": [],
        }

        if not change.parent_repo_status:
            return conflicts

        status = change.parent_repo_status
        claude_file_path = str(change.file_path.relative_to(self.project_root))

        # Check if Claude is modifying a file that humans have also modified
        if claude_file_path in status.get("modified_files", []):
            conflicts["has_conflicts"] = True
            conflicts["same_file_modified"] = True
            conflicts["recommendations"].append(
                f"⚠️  Both you and Claude modified {claude_file_path}. Review changes carefully before applying."
            )

        # Check for modifications to related files (same directory, similar names)
        claude_dir = str(change.file_path.parent.relative_to(self.project_root))
        claude_filename = change.file_path.stem

        for modified_file in status.get("modified_files", []):
            modified_path = Path(modified_file)
            modified_dir = str(modified_path.parent)
            modified_filename = modified_path.stem

            # Same directory or similar filename
            if (
                modified_dir == claude_dir and modified_filename != claude_filename
            ) or (modified_filename == claude_filename and modified_dir != claude_dir):
                conflicts["related_files_modified"].append(modified_file)

        if conflicts["related_files_modified"]:
            conflicts["has_conflicts"] = True
            conflicts["recommendations"].append(
                f"📁 Related files modified: {', '.join(conflicts['related_files_modified'])}"
            )

        # Track all human modifications for context
        for category in [
            "modified_files",
            "added_files",
            "deleted_files",
            "untracked_files",
        ]:
            for file_path in status.get(category, []):
                conflicts["human_modifications"].append(
                    {
                        "file": file_path,
                        "type": category.replace("_files", ""),
                        "hash": status.get("file_hashes", {}).get(file_path),
                    }
                )

        # Add recommendations based on the scope of changes
        human_change_count = len(conflicts["human_modifications"])
        if human_change_count > 5:
            conflicts["recommendations"].append(
                f"🔍 {human_change_count} files modified by human. Consider reviewing full changeset."
            )
        elif human_change_count > 0:
            conflicts["recommendations"].append(
                f"📝 {human_change_count} files modified by human alongside Claude's change."
            )

        return conflicts

    def get_meaningful_diff(
        self,
        limit: int = 10,
        parent_hash: Optional[str] = None,
        paths: Optional[List[str]] = None,
    ) -> Dict:
        """Get git-native diff showing Claude's changes vs current files."""
        diff_results = {
            "changes_analyzed": [],
            "files_modified_since_claude": [],
            "files_unchanged_since_claude": [],
            "files_not_found": [],
            "summary": {
                "total_claude_changes": 0,
                "user_modified_after_claude": 0,
                "claude_changes_intact": 0,
                "conflicts": 0,
            },
        }

        # Get recent commits from current session
        sessions = self._load_sessions()
        if not sessions:
            return diff_results

        current_session = max(
            [s for s in sessions if s.is_active],
            key=lambda x: x.start_time,
            default=None,
        )

        if not current_session:
            return diff_results

        commits = self.get_commits_for_session(current_session.id)

        # Analyze recent commits (excluding metadata commits)
        change_commits = [
            c
            for c in commits[: limit * 2]
            if not c.message.startswith("Update sessions metadata")
        ][:limit]

        for commit in change_commits:
            try:
                # Find metadata files that were added/modified in this specific commit
                if commit.parents:
                    # Get files changed in this commit (compared to parent)
                    changed_items = commit.diff(commit.parents[0])
                    changed_metadata_files = [
                        item.b_path
                        for item in changed_items
                        if item.b_path
                        and item.b_path.startswith("metadata/")
                        and item.b_path.endswith(".json")
                    ]
                else:
                    # First commit - all files are new
                    changed_metadata_files = [
                        str(f.path)
                        for f in commit.tree.traverse()
                        if f.name.endswith(".json") and "metadata/" in str(f.path)
                    ]

                if not changed_metadata_files:
                    continue

                # Get the first (and usually only) metadata file that was changed in this commit
                metadata_path = changed_metadata_files[0]
                metadata_blob = commit.tree / metadata_path
                metadata = json.loads(metadata_blob.data_stream.read().decode("utf-8"))

                # Filter by parent hash if specified
                if parent_hash:
                    file_parent_hash = metadata.get("parent_repo_hash", "")
                    if not (
                        file_parent_hash and file_parent_hash.startswith(parent_hash)
                    ):
                        continue

                # Filter by paths if specified
                if paths:
                    file_path = metadata.get("file_path", "")
                    if not any(
                        file_path.startswith(path) or path in file_path
                        for path in paths
                    ):
                        continue

                # Use git-native analysis
                change_analysis = self._git_native_analysis(metadata, commit)
                if change_analysis:
                    diff_results["changes_analyzed"].append(change_analysis)

                    # Update summary
                    diff_results["summary"]["total_claude_changes"] += 1

                    if change_analysis["status"] == "user_modified":
                        diff_results["files_modified_since_claude"].append(
                            change_analysis
                        )
                        diff_results["summary"]["user_modified_after_claude"] += 1
                        if change_analysis.get("has_conflicts", False):
                            diff_results["summary"]["conflicts"] += 1
                    elif change_analysis["status"] == "unchanged":
                        diff_results["files_unchanged_since_claude"].append(
                            change_analysis
                        )
                        diff_results["summary"]["claude_changes_intact"] += 1
                    elif change_analysis["status"] == "file_not_found":
                        diff_results["files_not_found"].append(change_analysis)

            except Exception:
                # Skip problematic commits but continue processing
                continue

        return diff_results

    def get_meaningful_diff_for_commit(
        self,
        commit_hash: str,
        parent_hash: Optional[str] = None,
        paths: Optional[List[str]] = None,
    ) -> Optional[Dict]:
        """Get git-native diff for a specific commit."""
        try:
            commit = self.repo.commit(commit_hash)

            # Find the metadata file for this commit
            metadata_files = [
                f
                for f in commit.tree.traverse()
                if f.name.endswith(".json") and "metadata/" in str(f.path)
            ]

            if not metadata_files:
                return None

            # Parse the metadata
            metadata = json.loads(metadata_files[0].data_stream.read().decode("utf-8"))

            # Filter by parent hash if specified
            if parent_hash:
                file_parent_hash = metadata.get("parent_repo_hash", "")
                if not (file_parent_hash and file_parent_hash.startswith(parent_hash)):
                    return None

            # Filter by paths if specified
            if paths:
                file_path = metadata.get("file_path", "")
                if not any(
                    file_path.startswith(path) or path in file_path for path in paths
                ):
                    return None

            # Use git-native analysis
            change_analysis = self._git_native_analysis(metadata, commit)
            if change_analysis:
                return {
                    "changes_analyzed": [change_analysis],
                    "summary": {
                        "total_claude_changes": 1,
                        "user_modified_after_claude": 1
                        if change_analysis["status"] == "user_modified"
                        else 0,
                        "claude_changes_intact": 1
                        if change_analysis["status"] == "unchanged"
                        else 0,
                        "conflicts": 1
                        if change_analysis.get("has_conflicts", False)
                        else 0,
                    },
                }

            return None

        except Exception:
            return None

    def _analyze_change_vs_current_state(
        self, change_data: Dict, commit: git.Commit
    ) -> Optional[Dict]:
        """Analyze a single change against the current state of the file."""
        try:
            file_path = Path(change_data["file_path"])
            relative_path = file_path.relative_to(self.project_root)

            analysis = {
                "commit_hash": commit.hexsha[:8],
                "commit_message": commit.message.strip().split("\n")[0],
                "commit_time": commit.committed_datetime,
                "file_path": str(relative_path),
                "change_type": change_data.get("change_type", "unknown"),
                "parent_repo_hash": change_data.get("parent_repo_hash"),
                "status": "unknown",
                "diff_lines": [],
                "has_conflicts": False,
                "user_changes_detected": [],
            }

            # Check if file currently exists
            if not file_path.exists():
                analysis["status"] = "file_not_found"
                analysis["diff_lines"] = [f"❌ File {relative_path} no longer exists"]
                return analysis

            # Get current file content
            current_content = file_path.read_text(encoding="utf-8")

            # For git-style diff, show what Claude changed (like git diff)
            if change_data["change_type"] == "write":
                # For writes, show the diff from empty file to Claude's content
                claude_content = change_data.get("new_content", "")

                # Generate diff from empty to Claude's content
                diff_lines = list(
                    difflib.unified_diff(
                        [],  # Empty file (before Claude's change)
                        claude_content.splitlines(keepends=True),
                        fromfile=f"a/{relative_path}",
                        tofile=f"b/{relative_path}",
                        lineterm="",
                    )
                )
                analysis["diff_lines"] = diff_lines

                # Set status based on current state vs Claude's intended state
                if current_content == claude_content:
                    analysis["status"] = "unchanged"
                else:
                    analysis["status"] = "user_modified"
                    analysis["has_conflicts"] = True

            elif change_data["change_type"] == "edit":
                # For edits, show the diff of what Claude changed
                old_string = change_data.get("old_string", "")
                new_string = change_data.get("new_string", "")
                old_content = change_data.get("old_content", "")

                if not old_string or not new_string:
                    analysis["status"] = "incomplete_data"
                    return analysis

                # Generate git-style diff showing Claude's edit
                if old_content and old_string in old_content:
                    # Show diff of the old content vs new content
                    claude_intended = old_content.replace(old_string, new_string)

                    diff_lines = list(
                        difflib.unified_diff(
                            old_content.splitlines(keepends=True),
                            claude_intended.splitlines(keepends=True),
                            fromfile=f"a/{relative_path}",
                            tofile=f"b/{relative_path}",
                            lineterm="",
                        )
                    )
                    analysis["diff_lines"] = diff_lines

                    # Set status based on current state
                    if current_content == claude_intended:
                        analysis["status"] = "unchanged"
                    else:
                        analysis["status"] = "user_modified"
                        analysis["has_conflicts"] = True
                else:
                    # Fallback: create a simple diff showing the edit
                    diff_lines = [
                        f"--- a/{relative_path}",
                        f"+++ b/{relative_path}",
                        "@@ -1,1 +1,1 @@",
                        f"-{old_string}",
                        f"+{new_string}",
                    ]
                    analysis["diff_lines"] = diff_lines
                    analysis["status"] = "incomplete_data"

                    # Check if the old string is back
                    if old_string in current_content:
                        analysis["user_changes_detected"].append(
                            "🔄 Original content appears to be restored"
                        )

            # Add revert capability analysis
            analysis["revert_info"] = self._analyze_revert_capability(
                change_data, analysis["status"]
            )

            return analysis

        except Exception as e:
            return {
                "commit_hash": commit.hexsha[:8],
                "file_path": change_data.get("file_path", "unknown"),
                "status": "error",
                "error": str(e),
            }

    def _analyze_revert_capability(
        self, change_data: Dict, current_status: str
    ) -> Dict:
        """Analyze whether a Claude change can be safely reverted."""
        revert_info = {
            "can_revert": False,
            "revert_type": "unknown",
            "revert_command": None,
            "warnings": [],
            "confidence": "low",
            "parent_repo_info": {},
        }

        try:
            file_path = Path(change_data["file_path"])

            if not file_path.exists():
                revert_info["warnings"].append(
                    "❌ File no longer exists - cannot revert"
                )
                return revert_info

            change_type = change_data.get("change_type", "unknown")
            current_content = file_path.read_text(encoding="utf-8")

            # Analyze parent repo status to understand user's changes
            claude_change_hash = change_data.get("parent_repo_hash")
            change_data.get("parent_repo_status", {})
            current_parent_status = self._get_parent_repo_status()
            current_parent_hash = self._get_parent_repo_hash()

            revert_info["parent_repo_info"] = {
                "hash_at_claude_change": claude_change_hash,
                "current_hash": current_parent_hash,
                "user_committed_since_claude": claude_change_hash
                != current_parent_hash,
                "repo_has_uncommitted_changes": current_parent_status.get(
                    "has_changes", False
                )
                if current_parent_status
                else False,
            }

            # Check if user has committed changes to the main repo since Claude's change
            user_committed_since = revert_info["parent_repo_info"][
                "user_committed_since_claude"
            ]

            if user_committed_since:
                revert_info["warnings"].append(
                    f"📝 User committed changes to main repo since Claude's change (was {claude_change_hash[:8] if claude_change_hash else 'unknown'}, now {current_parent_hash[:8] if current_parent_hash else 'unknown'})"
                )

            # Check if the specific file was modified by user in main repo
            relative_path = str(file_path.relative_to(self.project_root))
            file_in_user_changes = False

            if current_parent_status and current_parent_status.get("has_changes"):
                # Check if this file appears in current uncommitted changes
                all_changed_files = (
                    current_parent_status.get("modified_files", [])
                    + current_parent_status.get("added_files", [])
                    + current_parent_status.get("deleted_files", [])
                )
                file_in_user_changes = relative_path in all_changed_files

                if file_in_user_changes:
                    revert_info["warnings"].append(
                        "⚠️  File has uncommitted changes in main repo - reverting Claude's change may conflict"
                    )

            if change_type == "write":
                # For writes, check if we can restore the original file or delete it
                old_content = change_data.get("old_content")

                if old_content is not None and old_content == "":
                    # File was created by Claude
                    revert_info["can_revert"] = True
                    revert_info["revert_type"] = "delete_file"
                    revert_info["revert_command"] = (
                        f"claude-git rollback {change_data.get('id', 'HASH')}"
                    )
                    revert_info["confidence"] = "high"

                    if current_status == "user_modified":
                        revert_info["warnings"].append(
                            "⚠️  File has been modified since Claude created it - reverting will lose user changes"
                        )
                        revert_info["confidence"] = "medium"

                    # Adjust confidence based on parent repo status
                    if user_committed_since or file_in_user_changes:
                        revert_info["confidence"] = (
                            "medium" if revert_info["confidence"] == "high" else "low"
                        )

                elif old_content:
                    # File was overwritten by Claude
                    revert_info["can_revert"] = True
                    revert_info["revert_type"] = "restore_original"
                    revert_info["revert_command"] = (
                        f"claude-git rollback {change_data.get('id', 'HASH')}"
                    )
                    revert_info["confidence"] = "high"

                    if current_status == "user_modified":
                        revert_info["warnings"].append(
                            "⚠️  File has been modified since Claude overwrote it - reverting will lose user changes"
                        )
                        revert_info["confidence"] = "low"

                    # Adjust confidence based on parent repo status
                    if user_committed_since or file_in_user_changes:
                        revert_info["confidence"] = (
                            "medium" if revert_info["confidence"] == "high" else "low"
                        )
                        if user_committed_since and not file_in_user_changes:
                            revert_info["warnings"].append(
                                "✅ User committed main repo changes - reverting Claude's change is safer"
                            )

            elif change_type == "edit":
                # For edits, check if we can reverse the string replacement with line-level analysis
                old_string = change_data.get("old_string", "")
                new_string = change_data.get("new_string", "")

                # Perform detailed line-level conflict detection
                line_conflict_info = self._analyze_line_level_conflicts(
                    file_path,
                    old_string,
                    new_string,
                    change_data.get("parent_repo_hash"),
                )
                revert_info.update(line_conflict_info)

                if old_string and new_string:
                    if new_string in current_content:
                        # Claude's change is still present and can be reversed
                        revert_info["can_revert"] = True
                        revert_info["revert_type"] = "reverse_edit"
                        revert_info["revert_command"] = (
                            f"claude-git rollback {change_data.get('id', 'HASH')}"
                        )

                        # Check if reverting would conflict with user changes
                        if current_status == "user_modified":
                            # Would need to be more sophisticated to detect exact conflicts
                            revert_info["confidence"] = "medium"
                            revert_info["warnings"].append(
                                "⚠️  File has additional changes - review carefully before reverting"
                            )
                        else:
                            revert_info["confidence"] = "high"

                        # Use parent repo status to refine revert confidence
                        if user_committed_since:
                            if not file_in_user_changes:
                                revert_info["warnings"].append(
                                    "✅ User committed main repo (different files) - Claude's revert is safer"
                                )
                                # Don't downgrade confidence if user committed unrelated changes
                            else:
                                revert_info["confidence"] = "low"
                                revert_info["warnings"].append(
                                    "⚠️  User committed changes to this file - high risk of conflicts"
                                )
                        elif file_in_user_changes:
                            revert_info["confidence"] = "low"

                    elif old_string in current_content:
                        # Claude's change was already reverted or original content restored
                        revert_info["warnings"].append(
                            "ℹ️  Claude's change appears to already be reverted"
                        )

                    else:
                        # Neither old nor new string found - file changed significantly
                        revert_info["warnings"].append(
                            "❌ File changed significantly - cannot safely revert Claude's edit"
                        )

            return revert_info

        except Exception as e:
            revert_info["warnings"].append(f"❌ Error analyzing revert capability: {e}")
            return revert_info

    def _analyze_line_level_conflicts(
        self,
        file_path: Path,
        old_string: str,
        new_string: str,
        parent_hash: Optional[str],
    ) -> Dict:
        """Perform detailed line-level analysis to determine if revert is safe."""
        conflict_info = {
            "line_analysis": "unknown",
            "specific_conflicts": [],
            "safe_revert_confidence": "low",
        }

        try:
            if not file_path.exists():
                conflict_info["line_analysis"] = "file_missing"
                return conflict_info

            current_content = file_path.read_text(encoding="utf-8")

            # Check if Claude's change is still intact
            if new_string not in current_content:
                if old_string in current_content:
                    conflict_info["line_analysis"] = "already_reverted"
                    conflict_info["safe_revert_confidence"] = "high"
                    conflict_info["warnings"] = ["ℹ️  Change appears already reverted"]
                else:
                    conflict_info["line_analysis"] = "content_changed_significantly"
                    conflict_info["warnings"] = [
                        "❌ File changed significantly - cannot locate Claude's change"
                    ]
                return conflict_info

            # Claude's change is present - analyze if surrounding context changed
            current_lines = current_content.splitlines()
            old_string.splitlines()
            new_lines = new_string.splitlines()

            # Find where Claude's change appears in current file
            claude_change_context = self._find_change_context(current_lines, new_lines)

            if not claude_change_context:
                conflict_info["line_analysis"] = "context_not_found"
                conflict_info["warnings"] = [
                    "❌ Cannot locate Claude's change context in current file"
                ]
                return conflict_info

            start_line, end_line = claude_change_context

            # Get what the file looked like when Claude made the change
            if parent_hash:
                parent_content = self._get_file_at_parent_hash(file_path, parent_hash)
                if parent_content:
                    # Compare current surrounding context with parent context
                    conflict_analysis = self._compare_context_changes(
                        parent_content,
                        current_content,
                        start_line,
                        end_line,
                        old_string,
                        new_string,
                    )
                    conflict_info.update(conflict_analysis)
                else:
                    # Fallback: basic string replacement check
                    conflict_info.update(
                        self._basic_replacement_check(
                            current_content, old_string, new_string
                        )
                    )
            else:
                # No parent hash available, use basic check
                conflict_info.update(
                    self._basic_replacement_check(
                        current_content, old_string, new_string
                    )
                )

        except Exception as e:
            conflict_info["line_analysis"] = "error"
            conflict_info["warnings"] = [f"❌ Error in line analysis: {e}"]

        return conflict_info

    def _find_change_context(
        self, current_lines: List[str], new_lines: List[str]
    ) -> Optional[Tuple[int, int]]:
        """Find the line range where Claude's change appears in the current file."""
        try:
            if not new_lines:
                return None

            # Look for the first line of Claude's change
            first_new_line = new_lines[0]
            for i, line in enumerate(current_lines):
                if first_new_line.strip() in line:
                    # Found potential start, verify the full change is here
                    if len(new_lines) == 1:
                        return (i, i + 1)

                    # Check if multiple lines match
                    match_count = 0
                    for j, new_line in enumerate(new_lines):
                        if (
                            i + j < len(current_lines)
                            and new_line.strip() in current_lines[i + j]
                        ):
                            match_count += 1
                        else:
                            break

                    if match_count == len(new_lines):
                        return (i, i + len(new_lines))

        except Exception:
            pass
        return None

    def _get_file_at_parent_hash(
        self, file_path: Path, parent_hash: str
    ) -> Optional[str]:
        """Get the content of a file at a specific parent repo commit."""
        try:
            # Try to get the file content from the parent repo at the given hash
            parent_git_dir = self.project_root / ".git"
            if not parent_git_dir.exists():
                return None

            from git import Repo as GitRepo

            parent_repo = GitRepo(self.project_root)

            # Get relative path from project root
            relative_path = file_path.relative_to(self.project_root)

            # Get the file at the parent hash
            commit = parent_repo.commit(parent_hash)
            blob = commit.tree / str(relative_path)
            return blob.data_stream.read().decode("utf-8")

        except Exception:
            return None

    def _compare_context_changes(
        self,
        parent_content: str,
        current_content: str,
        start_line: int,
        end_line: int,
        old_string: str,
        new_string: str,
    ) -> Dict:
        """Compare context around Claude's change using content-based diff (like git)."""
        result = {
            "line_analysis": "git_style_diff",
            "safe_revert_confidence": "high",
            "specific_conflicts": [],
            "warnings": [],
        }

        try:
            # Use git-style three-way diff analysis
            # Compare: parent → claude_intended → current

            # Step 1: What Claude intended the file to look like
            claude_intended_content = parent_content.replace(old_string, new_string)

            # Step 2: Generate unified diff between Claude's intended result and current state
            claude_lines = claude_intended_content.splitlines(keepends=True)
            current_lines = current_content.splitlines(keepends=True)

            diff_lines = list(
                difflib.unified_diff(
                    claude_lines,
                    current_lines,
                    fromfile="Claude's intended result",
                    tofile="Current file",
                    lineterm="",
                    n=3,  # 3 lines of context like git default
                )
            )

            if len(diff_lines) <= 2:  # Only headers, no actual differences
                result["safe_revert_confidence"] = "high"
                result["warnings"] = [
                    "✅ File matches Claude's intended result - safe to revert"
                ]
            else:
                # Analyze the differences to see if they conflict with Claude's change
                conflict_analysis = self._analyze_unified_diff(
                    diff_lines, old_string, new_string
                )
                result.update(conflict_analysis)

        except Exception as e:
            result["line_analysis"] = "git_diff_failed"
            result["safe_revert_confidence"] = "low"
            result["warnings"] = [f"⚠️  Git-style diff analysis failed: {e}"]

        return result

    def _analyze_unified_diff(
        self, diff_lines: List[str], old_string: str, new_string: str
    ) -> Dict:
        """Analyze unified diff output to detect conflicts with Claude's change."""
        result = {
            "safe_revert_confidence": "medium",
            "specific_conflicts": [],
            "warnings": [],
        }

        try:
            # Count additions and deletions
            additions = [
                line
                for line in diff_lines
                if line.startswith("+") and not line.startswith("+++")
            ]
            deletions = [
                line
                for line in diff_lines
                if line.startswith("-") and not line.startswith("---")
            ]

            # Check if changes intersect with Claude's specific strings
            claude_strings_modified = False
            user_added_content = []

            for addition in additions:
                content = addition[1:]  # Remove + prefix
                if old_string.strip() in content or new_string.strip() in content:
                    claude_strings_modified = True
                else:
                    user_added_content.append(content.strip())

            for deletion in deletions:
                content = deletion[1:]  # Remove - prefix
                if old_string.strip() in content or new_string.strip() in content:
                    claude_strings_modified = True

            # Determine safety based on what was changed
            if not claude_strings_modified:
                if len(user_added_content) <= 2:
                    result["safe_revert_confidence"] = "high"
                    result["warnings"] = [
                        f"✅ User added {len(additions)} lines, but didn't modify Claude's specific changes - safe to revert"
                    ]
                else:
                    result["safe_revert_confidence"] = "medium"
                    result["warnings"] = [
                        f"⚠️  User added {len(additions)} lines near Claude's change - review before reverting"
                    ]
            else:
                result["safe_revert_confidence"] = "low"
                result["specific_conflicts"] = [
                    f"User modified {len([d for d in deletions if old_string.strip() in d or new_string.strip() in d])} lines that contain Claude's changes",
                    f"User added {len([a for a in additions if old_string.strip() in a or new_string.strip() in a])} lines that reference Claude's changes",
                ]
                result["warnings"] = [
                    "❌ User modifications overlap with Claude's specific changes - high risk of conflicts"
                ]

        except Exception as e:
            result["safe_revert_confidence"] = "low"
            result["warnings"] = [f"⚠️  Diff analysis failed: {e}"]

        return result

    def _basic_replacement_check(
        self, current_content: str, old_string: str, new_string: str
    ) -> Dict:
        """Basic check if string replacement can be safely reversed."""
        result = {
            "line_analysis": "basic_check",
            "safe_revert_confidence": "medium",
            "warnings": [],
        }

        if new_string in current_content and old_string not in current_content:
            # Simple case - Claude's change is there, original is not
            result["safe_revert_confidence"] = "high"
            result["warnings"] = [
                "✅ Simple string replacement - should be safe to revert"
            ]
        elif new_string in current_content and old_string in current_content:
            # Both strings present - potential for confusion
            result["safe_revert_confidence"] = "low"
            result["warnings"] = [
                "⚠️  Both old and new strings found - revert may be ambiguous"
            ]
        else:
            result["safe_revert_confidence"] = "low"
            result["warnings"] = ["⚠️  Cannot perform basic replacement analysis"]

        return result

    def _git_native_analysis(
        self, metadata: Dict, commit: git.Commit
    ) -> Optional[Dict]:
        """Use git-native approach to analyze changes by comparing mirrored files."""
        try:
            # metadata["file_path"] is already a relative path
            relative_path = Path(metadata["file_path"])
            file_path = self.project_root / relative_path

            analysis = {
                "commit_hash": commit.hexsha[:8],
                "commit_message": commit.message.strip().split("\n")[0]
                if commit.message
                else "No message",
                "commit_time": commit.committed_datetime,
                "file_path": str(relative_path),
                "change_type": metadata.get("change_type", "unknown"),
                "parent_repo_hash": metadata.get("parent_repo_hash"),
                "status": "unknown",
                "diff_lines": [],
                "has_conflicts": False,
                "user_changes_detected": [],
            }

            # Check if actual file exists
            if not file_path.exists():
                analysis["status"] = "file_not_found"
                analysis["diff_lines"] = [f"❌ File {relative_path} no longer exists"]
                return analysis

            # Path to the mirrored file in claude-git repo
            mirrored_file = self.claude_git_dir / "files" / relative_path

            if not mirrored_file.exists():
                analysis["status"] = "mirror_not_found"
                analysis["diff_lines"] = [
                    f"⚠️  Mirrored file not found for {relative_path}"
                ]
                return analysis

            # Use git diff to show what Claude changed (like git diff)
            try:
                # Read both file contents
                mirrored_content = mirrored_file.read_text(encoding="utf-8")
                current_content = file_path.read_text(encoding="utf-8")

                # Generate git-style diff showing what Claude changed
                # We need to reconstruct what the file looked like before Claude's change
                change_type = metadata.get("change_type", "unknown")

                if change_type == "write":
                    # For writes, show diff from empty file to Claude's content
                    diff_lines = list(
                        difflib.unified_diff(
                            [],  # Empty file before Claude
                            mirrored_content.splitlines(keepends=True),
                            fromfile=f"a/{relative_path}",
                            tofile=f"b/{relative_path}",
                            lineterm="",
                        )
                    )
                elif change_type == "edit":
                    # For edits, we need the old content from tool_input
                    tool_input = metadata.get("tool_input", {})
                    old_string = tool_input.get("parameters", {}).get("old_string", "")
                    new_string = tool_input.get("parameters", {}).get("new_string", "")

                    if old_string and new_string and old_string in mirrored_content:
                        # Reconstruct the file before Claude's edit
                        before_content = mirrored_content.replace(
                            new_string, old_string
                        )
                        diff_lines = list(
                            difflib.unified_diff(
                                before_content.splitlines(keepends=True),
                                mirrored_content.splitlines(keepends=True),
                                fromfile=f"a/{relative_path}",
                                tofile=f"b/{relative_path}",
                                lineterm="",
                            )
                        )
                    else:
                        # Fallback: simple representation
                        diff_lines = [
                            f"--- a/{relative_path}",
                            f"+++ b/{relative_path}",
                            "@@ -1,1 +1,1 @@",
                            f"-{old_string}",
                            f"+{new_string}",
                        ]
                else:
                    # Unknown change type, just show as new file
                    diff_lines = list(
                        difflib.unified_diff(
                            [],
                            mirrored_content.splitlines(keepends=True),
                            fromfile=f"a/{relative_path}",
                            tofile=f"b/{relative_path}",
                            lineterm="",
                        )
                    )

                analysis["diff_lines"] = diff_lines

                # Set status based on whether current file matches Claude's version
                if mirrored_content == current_content:
                    analysis["status"] = "unchanged"
                    analysis["revert_info"] = {
                        "can_revert": True,
                        "revert_type": "clean_revert",
                        "confidence": "high",
                        "warnings": [],
                    }
                else:
                    analysis["status"] = "user_modified"
                    analysis["has_conflicts"] = True

                    # Generate unified diff using git-style approach
                    diff_lines = list(
                        difflib.unified_diff(
                            mirrored_content.splitlines(keepends=True),
                            current_content.splitlines(keepends=True),
                            fromfile=f"Claude's version ({commit.hexsha[:8]})",
                            tofile="Current version",
                            lineterm="",
                            n=3,  # 3 lines context like git
                        )
                    )

                    # Limit diff output for readability
                    analysis["diff_lines"] = (
                        diff_lines[:50] if len(diff_lines) > 50 else diff_lines
                    )

                    # Analyze revert capability using git-style approach
                    analysis["revert_info"] = self._git_native_revert_analysis(
                        mirrored_content, current_content, metadata, analysis
                    )

                    # Detect type of user modifications
                    analysis["user_changes_detected"] = self._detect_change_patterns(
                        diff_lines
                    )

            except Exception as e:
                analysis["status"] = "diff_error"
                analysis["diff_lines"] = [f"❌ Error generating diff: {str(e)}"]

            # Add revert capability analysis
            if "revert_info" not in analysis:
                analysis["revert_info"] = self._analyze_revert_capability(
                    metadata, analysis["status"]
                )

            return analysis

        except Exception as e:
            return {
                "commit_hash": commit.hexsha[:8] if commit else "unknown",
                "commit_message": commit.message.strip().split("\n")[0]
                if commit and commit.message
                else "No message",
                "file_path": metadata.get("file_path", "unknown"),
                "status": "analysis_error",
                "error": str(e),
                "diff_lines": [f"❌ Analysis failed: {str(e)}"],
            }

    def _git_native_revert_analysis(
        self, claude_content: str, current_content: str, metadata: Dict, analysis: Dict
    ) -> Dict:
        """Analyze revert capability using git-native diff approach."""
        revert_info = {
            "can_revert": False,
            "revert_type": "unknown",
            "confidence": "low",
            "warnings": [],
            "diff_stats": {},
        }

        try:
            # Get unified diff stats
            diff_lines = list(
                difflib.unified_diff(
                    claude_content.splitlines(keepends=True),
                    current_content.splitlines(keepends=True),
                    fromfile="Claude's version",
                    tofile="Current version",
                    lineterm="",
                    n=3,
                )
            )

            # Count changes
            additions = [
                line
                for line in diff_lines
                if line.startswith("+") and not line.startswith("+++")
            ]
            deletions = [
                line
                for line in diff_lines
                if line.startswith("-") and not line.startswith("---")
            ]

            revert_info["diff_stats"] = {
                "additions": len(additions),
                "deletions": len(deletions),
                "total_changes": len(additions) + len(deletions),
            }

            # Determine revert capability based on change complexity
            total_changes = revert_info["diff_stats"]["total_changes"]

            if total_changes == 0:
                # No changes - already reverted or identical
                revert_info["can_revert"] = True
                revert_info["revert_type"] = "no_changes_needed"
                revert_info["confidence"] = "high"
                revert_info["warnings"] = ["ℹ️  Files are identical - no revert needed"]

            elif total_changes <= 10:
                # Small changes - likely safe to revert
                revert_info["can_revert"] = True
                revert_info["revert_type"] = "safe_revert"
                revert_info["confidence"] = "high" if total_changes <= 3 else "medium"
                revert_info["warnings"] = [
                    f"✅ {total_changes} line(s) changed - revert should be safe"
                ]

            elif total_changes <= 50:
                # Medium changes - review recommended
                revert_info["can_revert"] = True
                revert_info["revert_type"] = "review_recommended"
                revert_info["confidence"] = "medium"
                revert_info["warnings"] = [
                    f"⚠️  {total_changes} lines changed - review diff carefully before reverting"
                ]

            else:
                # Large changes - high risk
                revert_info["can_revert"] = False
                revert_info["revert_type"] = "high_risk"
                revert_info["confidence"] = "low"
                revert_info["warnings"] = [
                    f"❌ {total_changes} lines changed - reverting may lose significant user work"
                ]

            # Check parent repo status for additional context
            current_parent_status = self._get_parent_repo_status()
            current_parent_hash = self._get_parent_repo_hash()
            claude_parent_hash = metadata.get("parent_repo_hash")

            if claude_parent_hash and current_parent_hash != claude_parent_hash:
                revert_info["warnings"].append(
                    f"📝 Parent repo changed since Claude's modification ({claude_parent_hash[:8]} → {current_parent_hash[:8] if current_parent_hash else 'unknown'})"
                )

            relative_path = str(
                Path(metadata["file_path"]).relative_to(self.project_root)
            )
            if current_parent_status and relative_path in current_parent_status.get(
                "modified_files", []
            ):
                revert_info["warnings"].append(
                    "⚠️  File has uncommitted changes in parent repo"
                )
                if revert_info["confidence"] == "high":
                    revert_info["confidence"] = "medium"

        except Exception as e:
            revert_info["warnings"] = [
                f"❌ Error analyzing revert capability: {str(e)}"
            ]

        return revert_info

    def _detect_change_patterns(self, diff_lines: List[str]) -> List[str]:
        """Detect patterns in user changes for better analysis."""
        patterns = []

        try:
            additions = [
                line
                for line in diff_lines
                if line.startswith("+") and not line.startswith("+++")
            ]
            deletions = [
                line
                for line in diff_lines
                if line.startswith("-") and not line.startswith("---")
            ]

            if len(additions) > 0 and len(deletions) == 0:
                patterns.append(f"📝 User added {len(additions)} lines")
            elif len(deletions) > 0 and len(additions) == 0:
                patterns.append(f"🗑️  User removed {len(deletions)} lines")
            elif len(additions) > 0 and len(deletions) > 0:
                patterns.append(
                    f"🔄 User modified {len(additions)} additions, {len(deletions)} deletions"
                )

            # Check for common patterns
            import_changes = [line for line in additions if "import " in line.lower()]
            comment_changes = [
                line
                for line in additions
                if line.strip().startswith("#") or line.strip().startswith("//")
            ]

            if import_changes:
                patterns.append(f"📦 {len(import_changes)} import statements added")
            if comment_changes:
                patterns.append(f"💬 {len(comment_changes)} comments added")

        except Exception:
            patterns.append("❓ Could not analyze change patterns")

        return patterns
