"""Git-native repository management for claude-git dual-repository architecture."""

import json
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import git
from git import Repo

# Import test integration for real-time feedback
from claude_git.core.test_integration import CrossSessionTestCoordinator, TestMonitor


class GitNativeRepository:
    """Git-native dual repository management for claude-git.

    Manages two synchronized git repositories:
    - Main repo: User-controlled commits
    - Claude-git repo: Auto-commits with logical boundaries
    """

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        self.claude_git_dir = self.project_root / ".claude-git"
        self.config_file = self.claude_git_dir / ".claude-git-config.json"
        self._claude_repo: Optional[Repo] = None
        self._main_repo: Optional[Repo] = None

        # Change accumulation for logical commits
        self._accumulated_changes: List[Dict[str, Any]] = []
        self._session_active = False
        self._current_session_id: Optional[str] = None

        # Multi-session branching support
        self.sessions_dir = self.claude_git_dir / "sessions"
        self.sessions_metadata_file = self.claude_git_dir / ".claude-sessions.json"
        self._current_session_branch: Optional[str] = None
        self._current_worktree_path: Optional[Path] = None

        # Real-time test integration
        self._test_monitor: Optional[TestMonitor] = None
        self._test_coordinator = CrossSessionTestCoordinator(self.claude_git_dir)
        self._enable_test_monitoring = self._should_enable_test_monitoring()

    @property
    def claude_repo(self) -> Repo:
        """Get the claude-git repository."""
        if self._claude_repo is None:
            self._claude_repo = Repo(self.claude_git_dir)
        return self._claude_repo

    @property
    def main_repo(self) -> Repo:
        """Get the main project repository."""
        if self._main_repo is None:
            self._main_repo = Repo(self.project_root)
        return self._main_repo

    def exists(self) -> bool:
        """Check if claude-git repository is properly initialized."""
        return (
            self.claude_git_dir.exists()
            and (self.claude_git_dir / ".git").exists()
            and self.config_file.exists()
        )

    def init(self) -> None:
        """Initialize fork-based dual-repository system."""
        print(f"Initializing claude-git fork in {self.project_root}")

        # Ensure main repo exists
        if not (self.project_root / ".git").exists():
            raise ValueError(f"No git repository found in {self.project_root}")

        # Check if claude-git already exists
        if self.exists():
            raise ValueError(
                f"Claude-git already initialized in {self.project_root}. "
                f"Remove {self.claude_git_dir} manually if you want to reinitialize."
            )

        # Additional safety check for any existing .claude-git directory
        if self.claude_git_dir.exists():
            # Check if it has any contents (files, directories, or git repo)
            contents = list(self.claude_git_dir.iterdir())
            if contents:
                raise ValueError(
                    f"Directory {self.claude_git_dir} already exists and is not empty. "
                    f"Please remove it manually before initializing claude-git."
                )

        print("🚀 Creating git fork with shared objects for performance...")

        # Create fork using git clone with --reference for object sharing
        subprocess.run(
            [
                "git",
                "clone",
                "--reference",
                str(self.project_root),  # Share objects for performance
                str(self.project_root),  # Source repository
                str(self.claude_git_dir),  # Destination (the fork)
            ],
            check=True,
        )

        # Initialize the forked repository
        self._claude_repo = Repo(self.claude_git_dir)

        # Configure git user for claude-git repo
        with self._claude_repo.config_writer() as config:
            config.set_value("user", "name", "Claude")
            config.set_value("user", "email", "noreply@anthropic.com")

        # Set up upstream remote pointing to the main repo
        print("🔗 Setting up upstream remote...")
        self._claude_repo.create_remote(
            "upstream", f"..{''}"
        )  # Points to parent directory (main repo)

        # Create config file
        config = {
            "version": "3.0.0",  # Fork-based architecture
            "created": datetime.now().isoformat(),
            "project_root": str(self.project_root),
            "architecture": "fork-based",
            "main_repo_initial_commit": self._get_main_repo_commit(),
            "upstream_remote": "upstream",
        }
        self.config_file.write_text(json.dumps(config, indent=2))

        # Add config file and create initial commit
        self.claude_repo.index.add([".claude-git-config.json"])
        self.claude_repo.index.commit(
            "Initialize claude-git fork-based system\n\n"
            f"Upstream-Repo: {self._get_main_repo_commit()}\n"
            "Architecture: fork-based with auto-commit + squash workflow\n"
            "\n🚀 Generated with [Claude Code](https://claude.ai/code)\n"
            "\nCo-Authored-By: Claude <noreply@anthropic.com>"
        )

        print("✅ Claude-git fork initialized successfully!")
        print(f"📁 Fork location: {self.claude_git_dir}")
        print("🔄 Use 'git fetch upstream' to sync with main repo")
        print("🌟 Ready for auto-commit + squash workflow!")

    def sync_from_upstream(self) -> bool:
        """Sync changes from upstream (main repo) using git pull.

        Returns:
            True if sync successful, False otherwise
        """
        print("🔄 Syncing from upstream repository...")

        try:
            # Fetch latest changes from upstream
            upstream_remote = self.claude_repo.remote("upstream")
            print("📥 Fetching upstream changes...")
            upstream_remote.fetch()

            # Get current branch name
            current_branch = self.claude_repo.active_branch.name

            # Pull changes from upstream/main to current branch
            print(f"🔀 Merging upstream/main into {current_branch}...")
            result = subprocess.run(
                ["git", "-C", str(self.claude_git_dir), "pull", "upstream", "main"],
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                print("✅ Successfully synced from upstream")
                return True
            # Handle merge conflicts
            if "CONFLICT" in result.stdout or "CONFLICT" in result.stderr:
                self._handle_merge_conflict_guidance()
                return False
            print(f"❌ Git pull failed: {result.stderr}")
            return False

        except Exception as e:
            print(f"❌ Unexpected error during sync: {e}")
            return False

    def _handle_merge_conflict_guidance(self):
        """Provide guidance for resolving merge conflicts."""
        print("\n🚨 MERGE CONFLICT DETECTED!")
        print("The upstream changes conflict with Claude's work.")
        print("\nResolution Options:")
        print("1. 🛠  MANUAL RESOLUTION:")
        print(f"   cd {self.claude_git_dir}")
        print("   # Edit conflicted files to resolve conflicts")
        print("   git add .")
        print("   git commit")
        print("\n2. 🔄 RESET AND RESTART:")
        print(f"   cd {self.claude_git_dir}")
        print("   git reset --hard upstream/main")
        print("   # ⚠️  This will lose Claude's uncommitted work")
        print("\n3. 🤖 AI-POWERED RESOLUTION (if available):")
        print("   claude-git resolve-conflicts --auto")
        print("\n4. 📱 GET HELP:")
        print("   claude-git status")
        print("   git status  # Show conflicted files")
        print("\nAfter resolving, restart your Claude session.")
        print("Claude will sync successfully on the next session start.")

    def auto_commit_change(
        self, message: str, files: Optional[List[str]] = None
    ) -> str:
        """Auto-commit a change to the claude-git fork.

        Args:
            message: Commit message
            files: Optional list of specific files to commit (None = commit all changes)

        Returns:
            Commit hash
        """
        try:
            # Add files to staging
            if files:
                self.claude_repo.index.add(files)
            else:
                # Add all changes
                subprocess.run(
                    ["git", "-C", str(self.claude_git_dir), "add", "."], check=True
                )

            # Create auto-commit
            commit = self.claude_repo.index.commit(f"[auto] {message}")
            return commit.hexsha

        except Exception as e:
            print(f"❌ Error creating auto-commit: {e}")
            raise

    def _get_main_repo_commit(self) -> str:
        """Get current commit hash from main repository."""
        try:
            return self.main_repo.head.commit.hexsha
        except Exception:
            return "unknown"

    # === Change Accumulation System ===

    def session_start(
        self, session_id: str, topic: str = None, use_branching: bool = True
    ) -> None:
        """Start a new Claude session for change accumulation.

        Args:
            session_id: Unique session identifier
            topic: Optional topic for session branching (auth, ui, db, etc.)
            use_branching: Whether to create session branch and worktree
        """
        print(f"🚀 Starting Claude session: {session_id}")

        # Sync from upstream first to ensure we have latest changes
        if not self.sync_from_upstream():
            print(
                "⚠️  Warning: Could not sync from upstream, continuing with current state"
            )

        # Check if multi-session branching should be used
        if use_branching:
            active_sessions = self.get_active_sessions()

            if len(active_sessions) > 0:
                print(
                    f"🔀 Multi-session mode: {len(active_sessions)} active sessions detected"
                )
                print("🌿 Creating dedicated branch and worktree for this session")

                # Create session branch and worktree
                branch_name = self.create_session_branch(session_id, topic)
                self._current_session_branch = branch_name
                self._current_worktree_path = self.sessions_dir / branch_name

            else:
                print("🚀 Single session mode: working on main branch")
                self._current_session_branch = None
                self._current_worktree_path = None
        else:
            print("🚀 Session branching disabled: working on main branch")
            self._current_session_branch = None
            self._current_worktree_path = None

        self._session_active = True
        self._current_session_id = session_id
        self._accumulated_changes = []

        # Start real-time test monitoring if enabled
        if self._enable_test_monitoring:
            worktree_path = self._current_worktree_path or self.claude_git_dir
            self._test_monitor = TestMonitor(
                session_id=session_id,
                worktree_path=worktree_path,
                project_root=self.project_root,
            )

            if self._test_monitor.start_monitoring():
                # Register with cross-session coordinator
                self._test_coordinator.register_session_monitor(
                    session_id, self._test_monitor
                )
                print(f"🧪 Real-time test monitoring started for session {session_id}")
            else:
                print(f"⚠️  Failed to start test monitoring for session {session_id}")
                self._test_monitor = None

    def accumulate_change(
        self, file_path: str, tool_name: str, tool_input: Dict[str, Any]
    ) -> None:
        """Accumulate a change during Claude session - no immediate commits."""
        print(f"📝 Accumulating change: {tool_name} on {file_path}")

        # Store change information
        change_info = {
            "file_path": file_path,
            "tool_name": tool_name,
            "tool_input": tool_input,
            "timestamp": datetime.now().isoformat(),
            "main_repo_commit": self._get_main_repo_commit(),
        }

        self._accumulated_changes.append(change_info)

        # Trigger test run for the changed file if monitoring is active
        if self._test_monitor and tool_name in ["Write", "Edit", "MultiEdit"]:
            # Run tests affected by this file change
            changed_files = [file_path]
            self._test_monitor.run_affected_tests(changed_files)

        # Sync the specific file from main repo to claude-git repo
        self._sync_file_to_claude_repo(file_path)

    def session_end(self, thinking_text: str = None) -> str:
        """End Claude session and create logical commit with thinking text."""
        if not self._session_active:
            print("⚠️  No active session to end")
            return ""

        print(f"🏁 Ending Claude session: {self._current_session_id}")

        if not self._accumulated_changes:
            print("ℹ️  No changes to commit")

            # Stop test monitoring if active
            self._cleanup_test_monitoring()

            self._session_active = False
            self._current_session_id = None
            return ""

        # Create commit message with thinking text
        commit_message = self._create_thinking_commit_message(thinking_text)

        # Stage all changed files
        changed_files = []
        for change in self._accumulated_changes:
            file_path = change["file_path"]
            rel_path = (
                Path(file_path).resolve().relative_to(self.project_root.resolve())
            )
            changed_files.append(str(rel_path))

        # Remove duplicates while preserving order
        unique_files = []
        seen = set()
        for file_path in changed_files:
            if file_path not in seen:
                unique_files.append(file_path)
                seen.add(file_path)

        try:
            # Determine where to commit based on session mode
            target_repo = self.claude_repo
            if self._current_worktree_path and self._current_worktree_path.exists():
                # Working in session worktree
                target_repo = Repo(self._current_worktree_path)
                print(
                    f"📁 Committing to session worktree: {self._current_session_branch}"
                )

            # Stage changes in appropriate repo
            target_repo.index.add(unique_files)

            # Create commit with git notes
            commit = target_repo.index.commit(commit_message)

            # Add structured data as git notes
            if target_repo == self.claude_repo:
                self._add_git_notes(commit.hexsha)
            else:
                # For session branches, add notes after potential merge
                pass

            print(f"✅ Created logical commit: {commit.hexsha[:8]}")

            # Handle session branch merging
            session_id = self._current_session_id
            if self._current_session_branch and self._current_worktree_path:
                print(
                    f"🔀 Attempting to merge session branch: {self._current_session_branch}"
                )
                merge_success = self.merge_session_branch(session_id, auto_merge=True)

                if merge_success:
                    print("✅ Session merged successfully")
                    # Add git notes to merged commit
                    latest_commit = self.claude_repo.head.commit
                    self._add_git_notes(latest_commit.hexsha)
                else:
                    print("⚠️  Session branch requires manual merge")

            # Stop test monitoring if active
            self._cleanup_test_monitoring()

            # Reset session state
            self._session_active = False
            self._current_session_id = None
            self._accumulated_changes = []
            self._current_session_branch = None
            self._current_worktree_path = None

            return commit.hexsha

        except Exception as e:
            print(f"❌ Error creating commit: {e}")
            return ""

    def _create_thinking_commit_message(self, thinking_text: str = None) -> str:
        """Create commit message with thinking text and metadata."""
        if thinking_text:
            # Use thinking text as primary message
            primary_message = thinking_text.strip()
        else:
            # Fallback to generated summary
            file_count = len({c["file_path"] for c in self._accumulated_changes})
            tool_types = {c["tool_name"] for c in self._accumulated_changes}
            primary_message = (
                f"Claude session: {', '.join(tool_types)} on {file_count} files"
            )

        # Add structured metadata
        files_changed = list(
            {
                str(
                    Path(c["file_path"])
                    .resolve()
                    .relative_to(self.project_root.resolve())
                )
                for c in self._accumulated_changes
            }
        )

        metadata_lines = [
            "",  # Blank line after primary message
            f"Parent-Repo: {self._get_main_repo_commit()}",
            f"Session: {self._current_session_id}",
            f"Files: {','.join(files_changed)}",
            f"Changes: {len(self._accumulated_changes)}",
        ]

        return primary_message + "\n".join(metadata_lines)

    def _add_git_notes(self, commit_hash: str) -> None:
        """Add structured data as git notes for efficient querying."""
        try:
            # Prepare structured note data
            note_data = {
                "parent_repo": self._get_main_repo_commit(),
                "session_id": self._current_session_id,
                "timestamp": datetime.now().isoformat(),
                "files": [
                    str(
                        Path(c["file_path"])
                        .resolve()
                        .relative_to(self.project_root.resolve())
                    )
                    for c in self._accumulated_changes
                ],
                "tools": [c["tool_name"] for c in self._accumulated_changes],
                "change_count": len(self._accumulated_changes),
            }

            # Add git note with structured JSON
            note_json = json.dumps(note_data, indent=2)

            # Use GitPython for notes
            self.claude_repo.git.notes("add", "-m", note_json, commit_hash)

        except git.exc.GitCommandError as e:
            print(f"⚠️  Could not add git notes: {e}")
        except Exception as e:
            print(f"⚠️  Error adding git notes: {e}")

    def _sync_file_to_claude_repo(self, file_path: str) -> None:
        """Sync a specific file from main repo to claude-git repo."""
        try:
            source_file = Path(file_path)
            if not source_file.exists():
                print(f"⚠️  Source file does not exist: {file_path}")
                return

            rel_path = source_file.resolve().relative_to(self.project_root.resolve())
            target_file = self.claude_git_dir / rel_path

            # Ensure target directory exists
            target_file.parent.mkdir(parents=True, exist_ok=True)

            # Copy file
            shutil.copy2(source_file, target_file)

        except Exception as e:
            print(f"⚠️  Error syncing file {file_path}: {e}")

    def _create_immediate_commit(
        self, file_path: str, tool_name: str, tool_input: Dict[str, Any]
    ) -> None:
        """Create immediate commit for changes outside of session."""
        print(f"💾 Creating immediate commit for {tool_name} on {file_path}")

        # Sync the file
        self._sync_file_to_claude_repo(file_path)

        # Create simple commit message
        rel_path = Path(file_path).resolve().relative_to(self.project_root.resolve())
        commit_message = (
            f"claude: {tool_name.lower()} {rel_path}\n\n"
            f"Parent-Repo: {self._get_main_repo_commit()}\n"
            f"Tool: {tool_name}"
        )

        try:
            # Stage and commit
            self.claude_repo.index.add([str(rel_path)])
            commit = self.claude_repo.index.commit(commit_message)
            print(f"✅ Created immediate commit: {commit.hexsha[:8]}")

        except Exception as e:
            print(f"❌ Error creating immediate commit: {e}")

    def _commit_pending_user_changes(self) -> None:
        """Detect and commit any user changes before Claude starts working."""
        print("🔍 Checking for pending user changes...")

        try:
            # Check if main repo has uncommitted changes
            if self.main_repo.is_dirty():
                print("📝 Detected uncommitted user changes in main repo")
                # Note: We don't commit to main repo - that's user's choice
                # But we should sync current state to claude-git

            # Check for files that are different between main and claude-git repos
            changed_files = self._detect_file_differences()

            if changed_files:
                print(f"📁 Syncing {len(changed_files)} changed files from user")

                # Sync changed files
                for file_path in changed_files:
                    self._sync_file_to_claude_repo(str(self.project_root / file_path))

                # Commit user changes to claude-git
                commit_message = (
                    f"user: modified {len(changed_files)} files\n\n"
                    f"Parent-Repo: {self._get_main_repo_commit()}\n"
                    f"Files: {','.join(changed_files)}"
                )

                self.claude_repo.index.add(changed_files)
                commit = self.claude_repo.index.commit(commit_message)
                print(f"✅ Committed user changes: {commit.hexsha[:8]}")

        except Exception as e:
            print(f"⚠️  Error checking user changes: {e}")

    def _detect_file_differences(self) -> List[str]:
        """Detect files that differ between main repo and claude-git repo."""
        changed_files = []

        try:
            # Compare files in main repo vs claude-git repo
            for item in self.project_root.rglob("*"):
                if (
                    ".git" in item.parts
                    or ".claude-git" in item.parts
                    or item.name.startswith(".")
                ):
                    continue

                if item.is_file():
                    rel_path = item.resolve().relative_to(self.project_root.resolve())
                    claude_file = self.claude_git_dir / rel_path

                    # Check if files are different
                    if not claude_file.exists():
                        changed_files.append(str(rel_path))
                    else:
                        try:
                            main_content = item.read_text(encoding="utf-8")
                            claude_content = claude_file.read_text(encoding="utf-8")

                            if main_content != claude_content:
                                changed_files.append(str(rel_path))

                        except (UnicodeDecodeError, OSError):
                            # Handle binary files by comparing file stats
                            if item.stat().st_mtime != claude_file.stat().st_mtime:
                                changed_files.append(str(rel_path))

        except Exception as e:
            print(f"⚠️  Error detecting file differences: {e}")

        return changed_files

    # ========================================
    # AI-Powered Conflict Resolution System
    # ========================================

    def resolve_conflicts_with_ai(
        self, conflict_files: List[str], max_time_seconds: int = 60
    ) -> Dict[str, Any]:
        """Use Claude Code to automatically resolve merge conflicts.

        Args:
            conflict_files: List of files with conflicts
            max_time_seconds: Maximum time to spend on AI resolution

        Returns:
            Dict with resolution results: {
                'success': bool,
                'resolved_files': List[str],
                'duration': float,
                'worktree_path': str,
                'resolution_commit': str
            }
        """
        import time

        start_time = time.time()

        try:
            # Create isolated conflict resolution worktree
            resolution_worktree = self._create_conflict_resolution_worktree()

            print(f"🤖 AI conflict resolution started (max {max_time_seconds}s)")
            print(f"📁 Resolution worktree: {resolution_worktree}")

            resolved_files = []

            for conflict_file in conflict_files:
                elapsed = time.time() - start_time
                if elapsed >= max_time_seconds:
                    print(f"⏰ Time limit reached ({max_time_seconds}s)")
                    break

                remaining_time = max_time_seconds - elapsed
                print(f"🔧 Resolving {conflict_file} ({remaining_time:.1f}s remaining)")

                # Generate contextual prompt for this conflict
                conflict_prompt = self._generate_conflict_resolution_prompt(
                    conflict_file, resolution_worktree
                )

                # Invoke Claude Code non-interactively
                resolution_result = self._invoke_claude_code_for_resolution(
                    conflict_prompt, conflict_file, resolution_worktree
                )

                if resolution_result["success"]:
                    resolved_files.append(conflict_file)
                    print(f"✅ Resolved {conflict_file}")
                else:
                    print(
                        f"❌ Failed to resolve {conflict_file}: {resolution_result['error']}"
                    )
                    break

            # Create resolution commit if any files were resolved
            resolution_commit = None
            if resolved_files:
                resolution_commit = self._commit_ai_resolution(
                    resolution_worktree, resolved_files
                )

            duration = time.time() - start_time

            return {
                "success": len(resolved_files) == len(conflict_files),
                "resolved_files": resolved_files,
                "duration": duration,
                "worktree_path": str(resolution_worktree),
                "resolution_commit": resolution_commit,
                "partial_resolution": len(resolved_files) > 0
                and len(resolved_files) < len(conflict_files),
            }

        except Exception as e:
            print(f"❌ AI conflict resolution failed: {e}")
            return {
                "success": False,
                "resolved_files": [],
                "duration": time.time() - start_time,
                "error": str(e),
                "worktree_path": None,
                "resolution_commit": None,
            }

    def _create_conflict_resolution_worktree(self) -> Path:
        """Create a temporary worktree for conflict resolution using GitPython."""

        # Create temporary directory for resolution worktree
        temp_dir = Path(tempfile.mkdtemp(prefix="claude-git-resolve-"))

        try:
            # Create worktree with the conflicted state using GitPython
            self.claude_repo.git.worktree("add", str(temp_dir), "claude-main")

            return temp_dir

        except git.exc.GitCommandError as e:
            print(f"❌ Failed to create resolution worktree: {e}")
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            raise

    def _generate_conflict_resolution_prompt(
        self, conflict_file: str, worktree_path: Path
    ) -> str:
        """Generate contextual prompt for Claude Code conflict resolution."""
        conflict_file_path = worktree_path / conflict_file

        if not conflict_file_path.exists():
            raise FileNotFoundError(f"Conflict file not found: {conflict_file_path}")

        # Read the conflicted file content
        with open(conflict_file_path, encoding="utf-8") as f:
            conflict_content = f.read()

        # Extract conflict sections
        conflict_sections = self._parse_git_conflict_markers(conflict_content)

        # Get file context (imports, surrounding functions, etc.)
        file_context = self._extract_file_context(conflict_file_path)

        # Generate the prompt
        return f"""MERGE CONFLICT RESOLUTION TASK

You are an expert software engineer resolving a merge conflict in a collaborative AI-human development project.

File: {conflict_file}
Language: {self._detect_language(conflict_file)}

CRITICAL RULES:
1. USER CHANGES ALWAYS WIN - Preserve user's architectural decisions
2. Integrate valuable logic from AI changes where compatible
3. Maintain code quality, style, and consistency
4. Create working, syntactically correct code
5. OUTPUT ONLY the resolved file content, no explanations

File Context:
{file_context}

Conflict Details:
{self._format_conflict_sections(conflict_sections)}

Current Conflicted Content:
```{self._detect_language(conflict_file)}
{conflict_content}
```

TASK: Resolve this conflict by creating a merged solution that preserves the user's changes while integrating compatible AI improvements.

OUTPUT: Complete resolved file content only.
"""

    def _parse_git_conflict_markers(self, content: str) -> List[Dict[str, str]]:
        """Parse Git conflict markers and extract conflict sections."""
        conflicts = []
        lines = content.split("\n")

        in_conflict = False
        current_conflict = {}

        for line in lines:
            if line.startswith("<<<<<<<"):
                in_conflict = True
                current_conflict = {
                    "ours": [],
                    "theirs": [],
                    "current_section": "ours",
                    "marker_line": line,
                }
            elif line.startswith("======="):
                if in_conflict:
                    current_conflict["current_section"] = "theirs"
            elif line.startswith(">>>>>>>"):
                if in_conflict:
                    current_conflict["end_marker"] = line
                    conflicts.append(current_conflict)
                    current_conflict = {}
                in_conflict = False
            else:
                if in_conflict:
                    section = current_conflict["current_section"]
                    current_conflict[section].append(line)

        return conflicts

    def _extract_file_context(self, file_path: Path) -> str:
        """Extract relevant context from the file for better conflict resolution."""
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()

            # Extract imports, class definitions, function signatures
            context_lines = []
            lines = content.split("\n")

            for line in lines:
                stripped = line.strip()
                # Skip conflict markers
                if any(
                    marker in stripped for marker in ["<<<<<<<", "=======", ">>>>>>>"]
                ):
                    continue

                # Include imports, class/function definitions
                if stripped.startswith(
                    (
                        "import ",
                        "from ",
                        "class ",
                        "def ",
                        "async def",
                        "#",
                        "/**",
                        "/*",
                        "//",
                    )
                ):
                    context_lines.append(line)

                # Limit context to prevent huge prompts
                if len(context_lines) >= 20:
                    break

            return "\n".join(context_lines)

        except Exception as e:
            return f"Could not extract file context: {e}"

    def _detect_language(self, file_path: str) -> str:
        """Detect programming language from file extension."""
        extension_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "javascript",
            ".tsx": "typescript",
            ".java": "java",
            ".cpp": "cpp",
            ".c": "c",
            ".h": "c",
            ".go": "go",
            ".rs": "rust",
            ".php": "php",
            ".rb": "ruby",
            ".sh": "bash",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".json": "json",
            ".xml": "xml",
            ".html": "html",
            ".css": "css",
            ".scss": "scss",
            ".md": "markdown",
        }

        ext = Path(file_path).suffix.lower()
        return extension_map.get(ext, "text")

    def _format_conflict_sections(self, conflicts: List[Dict[str, str]]) -> str:
        """Format conflict sections for the prompt."""
        if not conflicts:
            return "No conflicts detected"

        formatted = []
        for i, conflict in enumerate(conflicts, 1):
            ours_code = "\n".join(conflict.get("ours", []))
            theirs_code = "\n".join(conflict.get("theirs", []))

            formatted.append(f"""
Conflict {i}:
USER'S CODE (must be preserved):
{ours_code}

AI'S CODE (integrate if compatible):
{theirs_code}
""")

        return "\n".join(formatted)

    def _invoke_claude_code_for_resolution(
        self, prompt: str, conflict_file: str, worktree_path: Path
    ) -> Dict[str, Any]:
        """Invoke Claude Code non-interactively to resolve the conflict."""

        try:
            # Write prompt to temporary file
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False
            ) as f:
                f.write(prompt)
                prompt_file = f.name

            # Invoke Claude Code with the prompt
            cmd = ["claude", "-p", prompt]

            # Set working directory to the resolution worktree
            result = subprocess.run(
                cmd,
                cwd=str(worktree_path),
                input=prompt,
                text=True,
                capture_output=True,
                timeout=45,  # Leave 15s buffer from the 60s limit
            )

            # Clean up prompt file
            Path(prompt_file).unlink(missing_ok=True)

            if result.returncode == 0:
                # Claude Code provided a solution
                resolved_content = result.stdout.strip()

                # Write resolved content to the conflict file
                conflict_file_path = worktree_path / conflict_file
                with open(conflict_file_path, "w", encoding="utf-8") as f:
                    f.write(resolved_content)

                # Verify the resolution (no conflict markers)
                if self._verify_conflict_resolution(conflict_file_path):
                    return {
                        "success": True,
                        "resolved_content": resolved_content,
                        "claude_output": result.stdout,
                    }
                return {
                    "success": False,
                    "error": "Resolution contains conflict markers or is invalid",
                    "claude_output": result.stdout,
                }
            return {
                "success": False,
                "error": f"Claude Code failed: {result.stderr}",
                "return_code": result.returncode,
            }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Claude Code resolution timed out"}
        except Exception as e:
            return {"success": False, "error": f"Unexpected error: {e}"}

    def _verify_conflict_resolution(self, file_path: Path) -> bool:
        """Verify that the conflict resolution is valid."""
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()

            # Check for remaining conflict markers
            conflict_markers = ["<<<<<<<", "=======", ">>>>>>>"]
            for marker in conflict_markers:
                if marker in content:
                    return False

            # Basic syntax check for Python files
            if file_path.suffix == ".py":
                try:
                    import ast

                    ast.parse(content)
                except SyntaxError:
                    return False

            return True

        except Exception:
            return False

    def _commit_ai_resolution(
        self, worktree_path: Path, resolved_files: List[str]
    ) -> str:
        """Commit the AI-resolved changes in the resolution worktree using GitPython."""
        try:
            # Create repo object for the worktree
            worktree_repo = Repo(worktree_path)

            # Stage resolved files using GitPython
            worktree_repo.index.add(resolved_files)

            # Create commit with AI resolution metadata
            commit_message = f"""AI-resolved merge conflicts

Files resolved by Claude Code:
{chr(10).join(f"- {f}" for f in resolved_files)}

Auto-generated conflict resolution
Time: {datetime.now().isoformat()}
"""

            # Commit using GitPython
            commit = worktree_repo.index.commit(commit_message)

            return commit.hexsha

        except git.exc.GitCommandError as e:
            print(f"❌ Failed to commit AI resolution: {e}")
            return ""
        except Exception as e:
            print(f"❌ Error during AI resolution commit: {e}")
            return ""

    # ========================================
    # Multi-Session Branching & Worktree Management
    # ========================================

    def create_session_branch(self, session_id: str, topic: str = None) -> str:
        """Create a new branch and worktree for a Claude session.

        Args:
            session_id: Unique session identifier
            topic: Optional topic for the session (auth, ui, db, etc.)

        Returns:
            Branch name created
        """
        timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")

        if topic:
            branch_name = f"session-{topic}-{timestamp}"
        else:
            branch_name = f"session-{timestamp}"

        try:
            # Ensure sessions directory exists
            self.sessions_dir.mkdir(exist_ok=True)

            # Create new branch from current HEAD
            self.claude_repo.create_head(branch_name)

            # Create worktree for this session
            worktree_path = self.sessions_dir / branch_name
            self._create_worktree(branch_name, worktree_path)

            # Update session metadata
            self._update_session_metadata(
                session_id, branch_name, str(worktree_path), topic
            )

            print(f"🌿 Created session branch: {branch_name}")
            print(f"📁 Worktree path: {worktree_path}")

            return branch_name

        except Exception as e:
            print(f"❌ Error creating session branch: {e}")
            raise

    def _create_worktree(self, branch_name: str, worktree_path: Path) -> None:
        """Create a git worktree for the session using GitPython."""
        try:
            # Remove existing worktree if it exists
            if worktree_path.exists():
                shutil.rmtree(worktree_path)

            # Create git worktree using GitPython
            self.claude_repo.git.worktree("add", str(worktree_path), branch_name)

            # Sync current files to the new worktree
            self._sync_files_to_worktree(worktree_path)

        except git.exc.GitCommandError as e:
            print(f"❌ Git worktree creation failed: {e}")
            raise

    def _sync_files_to_worktree(self, worktree_path: Path) -> None:
        """Sync current project files to the worktree."""
        try:
            for item in self.project_root.rglob("*"):
                if (
                    ".git" in item.parts
                    or ".claude-git" in item.parts
                    or item.name.startswith(".")
                ):
                    continue

                if item.is_file():
                    rel_path = item.relative_to(self.project_root)
                    target_path = worktree_path / rel_path

                    # Create parent directories
                    target_path.parent.mkdir(parents=True, exist_ok=True)

                    # Copy file
                    shutil.copy2(item, target_path)

        except Exception as e:
            print(f"⚠️  Error syncing files to worktree: {e}")

    def _update_session_metadata(
        self, session_id: str, branch_name: str, worktree_path: str, topic: str = None
    ) -> None:
        """Update session metadata JSON file."""
        try:
            # Load existing metadata
            metadata = {}
            if self.sessions_metadata_file.exists():
                with open(self.sessions_metadata_file) as f:
                    metadata = json.load(f)

            # Add new session
            metadata[session_id] = {
                "branch_name": branch_name,
                "worktree_path": worktree_path,
                "topic": topic,
                "created_at": datetime.now().isoformat(),
                "status": "active",
                "main_repo_commit": self._get_main_repo_commit(),
            }

            # Save metadata
            with open(self.sessions_metadata_file, "w") as f:
                json.dump(metadata, f, indent=2)

        except Exception as e:
            print(f"⚠️  Error updating session metadata: {e}")

    def get_active_sessions(self) -> Dict[str, Dict]:
        """Get all active Claude sessions."""
        try:
            if not self.sessions_metadata_file.exists():
                return {}

            with open(self.sessions_metadata_file) as f:
                metadata = json.load(f)

            # Filter for active sessions
            return {
                session_id: session_data
                for session_id, session_data in metadata.items()
                if session_data.get("status") == "active"
            }

        except Exception as e:
            print(f"⚠️  Error getting active sessions: {e}")
            return {}

    def merge_session_branch(self, session_id: str, auto_merge: bool = True) -> bool:
        """Merge a session branch back to main claude-git branch.

        Args:
            session_id: Session to merge
            auto_merge: If True, automatically merge non-conflicting changes

        Returns:
            True if merge successful, False if conflicts require manual resolution
        """
        try:
            # Get session metadata
            metadata = self._get_session_metadata(session_id)
            if not metadata:
                print(f"❌ Session {session_id} not found")
                return False

            branch_name = metadata["branch_name"]
            worktree_path = Path(metadata["worktree_path"])

            # Switch to main branch
            self.claude_repo.heads.main.checkout()

            # Attempt merge
            try:
                # Try fast-forward merge first
                merge_base = self.claude_repo.merge_base(
                    self.claude_repo.head.commit,
                    self.claude_repo.heads[branch_name].commit,
                )[0]

                if merge_base == self.claude_repo.head.commit:
                    # Fast-forward merge possible
                    self.claude_repo.head.reference = self.claude_repo.heads[
                        branch_name
                    ].commit
                    self.claude_repo.head.reset(index=True, working_tree=True)
                    print(f"✅ Fast-forward merged session: {branch_name}")

                else:
                    # Three-way merge needed
                    if auto_merge:
                        self.claude_repo.git.merge(
                            branch_name, "--no-ff", m=f"Merge session: {session_id}"
                        )
                        print(f"✅ Auto-merged session: {branch_name}")
                    else:
                        print(f"🔄 Manual merge required for session: {branch_name}")
                        return False

                # Clean up worktree and branch
                self._cleanup_session(session_id, branch_name, worktree_path)
                return True

            except git.exc.GitCommandError as e:
                if "CONFLICT" in str(e):
                    print(f"⚠️  Merge conflicts detected for session: {branch_name}")
                    print("🔧 Use 'claude-git merge-interactive' to resolve conflicts")
                    return False
                raise

        except Exception as e:
            print(f"❌ Error merging session {session_id}: {e}")
            return False

    def _get_session_metadata(self, session_id: str) -> Optional[Dict]:
        """Get metadata for a specific session."""
        try:
            if not self.sessions_metadata_file.exists():
                return None

            with open(self.sessions_metadata_file) as f:
                metadata = json.load(f)

            return metadata.get(session_id)

        except Exception as e:
            print(f"⚠️  Error getting session metadata: {e}")
            return None

    def _cleanup_session(
        self, session_id: str, branch_name: str, worktree_path: Path
    ) -> None:
        """Clean up session branch and worktree after merge using GitPython."""
        try:
            # Remove worktree using GitPython
            if worktree_path.exists():
                self.claude_repo.git.worktree("remove", str(worktree_path), "--force")

            # Delete branch using GitPython
            self.claude_repo.delete_head(branch_name, force=True)

            # Update metadata
            self._mark_session_completed(session_id)

            print(f"🧹 Cleaned up session: {session_id}")

        except git.exc.GitCommandError as e:
            print(f"⚠️  Git error cleaning up session: {e}")
        except Exception as e:
            print(f"⚠️  Error cleaning up session: {e}")

    def _mark_session_completed(self, session_id: str) -> None:
        """Mark session as completed in metadata."""
        try:
            if not self.sessions_metadata_file.exists():
                return

            with open(self.sessions_metadata_file) as f:
                metadata = json.load(f)

            if session_id in metadata:
                metadata[session_id]["status"] = "completed"
                metadata[session_id]["completed_at"] = datetime.now().isoformat()

            with open(self.sessions_metadata_file, "w") as f:
                json.dump(metadata, f, indent=2)

        except Exception as e:
            print(f"⚠️  Error marking session completed: {e}")

    def list_session_branches(self) -> List[Dict[str, Any]]:
        """List all session branches with their metadata."""
        branches = []

        try:
            if not self.sessions_metadata_file.exists():
                return branches

            with open(self.sessions_metadata_file) as f:
                metadata = json.load(f)

            for session_id, session_data in metadata.items():
                branches.append(
                    {
                        "session_id": session_id,
                        "branch_name": session_data.get("branch_name"),
                        "topic": session_data.get("topic"),
                        "status": session_data.get("status"),
                        "created_at": session_data.get("created_at"),
                        "main_repo_commit": session_data.get("main_repo_commit"),
                    }
                )

            return sorted(branches, key=lambda x: x["created_at"], reverse=True)

        except Exception as e:
            print(f"⚠️  Error listing session branches: {e}")
            return branches

    def _should_enable_test_monitoring(self) -> bool:
        """Determine if real-time test monitoring should be enabled for this project."""
        # Check for Python test frameworks and test files
        test_indicators = [
            # pytest configuration
            self.project_root / "pytest.ini",
            self.project_root / "pyproject.toml",  # May have pytest config
            self.project_root / "setup.cfg",  # May have pytest config
            # Test directories
            self.project_root / "tests",
            self.project_root / "test",
        ]

        # Check for test files in common patterns
        test_file_patterns = ["test_*.py", "*_test.py", "tests/*.py"]

        # If any test indicators exist, enable monitoring
        if any(indicator.exists() for indicator in test_indicators):
            print("🧪 Test monitoring enabled: Found test configuration/directories")
            return True

        # Check for test files using glob patterns
        for pattern in test_file_patterns:
            if any(self.project_root.glob(pattern)):
                print(f"🧪 Test monitoring enabled: Found test files ({pattern})")
                return True

        print("ℹ️  Test monitoring disabled: No test configuration detected")
        return False

    def _cleanup_test_monitoring(self) -> None:
        """Stop and clean up test monitoring for the current session."""
        if self._test_monitor:
            # Get session summary before stopping
            session_summary = self._test_monitor.get_session_test_summary()

            # Stop monitoring
            self._test_monitor.stop_monitoring()

            # Unregister from coordinator
            if self._current_session_id:
                self._test_coordinator.unregister_session_monitor(
                    self._current_session_id
                )

            # Report final test status
            if session_summary["total_test_runs"] > 0:
                status = "✅" if session_summary["overall_success"] else "❌"
                print(
                    f"{status} Session test summary: {session_summary['successful_runs']}/{session_summary['total_test_runs']} test runs successful"
                )
                print(
                    f"   Latest: {session_summary['latest_passed']} passed, {session_summary['latest_failed']} failed"
                )

            self._test_monitor = None

    # Legacy CLI compatibility methods

    def list_sessions(self) -> List[Dict[str, Any]]:
        """List all sessions (compatibility method)."""
        try:
            return list(self.get_active_sessions().values())
        except Exception:
            return []

    def get_commits_for_session(self, session_id: str) -> List[Any]:
        """Get commits for a session (compatibility method)."""
        try:
            # Try to find commits with session ID in git notes or message
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.claude_git_dir),
                    "log",
                    "--oneline",
                    "--grep",
                    f"Session: {session_id}",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode == 0:
                commits = []
                for line in result.stdout.strip().split("\n"):
                    if line:
                        commit_hash = line.split()[0]
                        message = " ".join(line.split()[1:])
                        commits.append({"hash": commit_hash, "message": message})
                return commits
        except Exception:
            pass
        return []

    def run_git_command_with_pager(self, args: List[str]) -> None:
        """Run git command with pager (compatibility method)."""
        cmd = ["git", "-C", str(self.claude_git_dir)] + args
        subprocess.run(cmd, check=False)

    def run_git_command(self, args: List[str]) -> subprocess.CompletedProcess:
        """Run git command (compatibility method)."""
        cmd = ["git", "-C", str(self.claude_git_dir)] + args
        return subprocess.run(cmd, capture_output=True, text=True, check=False)

    def get_meaningful_diff(self, *args, **kwargs) -> Dict[str, Any]:
        """Get meaningful diff (compatibility method)."""
        # Simple implementation - return minimal structure for compatibility
        result = self.run_git_command(["diff"])
        diff_text = result.stdout if result.returncode == 0 else ""

        # Return expected dictionary format
        return {"changes_analyzed": [{"diff": diff_text}] if diff_text.strip() else []}

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session info (compatibility method)."""
        sessions = self.get_active_sessions()
        return sessions.get(session_id)

    def _get_parent_repo_status(self) -> Dict[str, Any]:
        """Get parent repo status (compatibility method)."""
        try:
            result = subprocess.run(
                ["git", "-C", str(self.project_root), "status", "--porcelain"],
                capture_output=True,
                text=True,
                check=False,
            )

            return {"has_changes": bool(result.stdout.strip()), "status": result.stdout}
        except Exception:
            return {"has_changes": False, "status": ""}

    def get_meaningful_diff_for_commit(self, commit_hash: str) -> str:
        """Get meaningful diff for commit (compatibility method)."""
        result = self.run_git_command(["show", "--stat", commit_hash])
        return result.stdout if result.returncode == 0 else ""

    def _get_parent_repo_hash(self) -> str:
        """Get parent repo current commit hash (compatibility method)."""
        try:
            result = subprocess.run(
                ["git", "-C", str(self.project_root), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except Exception:
            return ""

    @property
    def repo(self) -> Repo:
        """Compatibility property for accessing the git repo."""
        return self.claude_repo
