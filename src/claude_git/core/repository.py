"""Claude Git repository management using real git."""

import difflib
import json
import shutil
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
        
        # Analyze conflicts with human changes
        conflict_analysis = self.detect_conflicts_with_human_changes(change)
        
        # Create a change record file instead of the actual file
        change_dir = self.claude_git_dir / "changes"
        change_dir.mkdir(exist_ok=True)
        
        change_file = change_dir / f"{change.id}.json"
        change_data = {
            "id": change.id,
            "timestamp": change.timestamp.isoformat(),
            "change_type": change.change_type.value,
            "file_path": str(change.file_path),
            "old_string": change.old_string,
            "new_string": change.new_string,
            "old_content": change.old_content,
            "new_content": change.new_content,
            "tool_input": change.tool_input,
            "parent_repo_hash": parent_repo_hash,
            "parent_repo_status": parent_repo_status,
            "conflict_analysis": conflict_analysis,
        }
        
        change_file.write_text(json.dumps(change_data, indent=2))
        
        # Also create a patch file for easy application
        patch_file = change_dir / f"{change.id}.patch"
        patch_content = self._create_patch(change)
        patch_file.write_text(patch_content)
        
        # Stage both files
        self.repo.index.add([
            str(change_file.relative_to(self.claude_git_dir)),
            str(patch_file.relative_to(self.claude_git_dir))
        ])
        
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
                branch_name = f"session-{timestamp.strftime('%Y-%m-%d-%H-%M-%S')}-{counter}"
        
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
        import subprocess
        import os
        
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
                raise RuntimeError(f"Git command failed with exit code {result.returncode}")
                
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
                main_branch = self.repo.heads.main if "main" in [h.name for h in self.repo.heads] else self.repo.heads.master
                self.repo.create_head(branch_name, main_branch)
            
            # Checkout the branch
            self.repo.heads[branch_name].checkout()
        except git.exc.GitCommandError as e:
            # If main/master doesn't exist, create from current HEAD
            if not self.repo.heads:
                self.repo.create_head(branch_name)
            else:
                self.repo.create_head(branch_name, self.repo.head.commit)
            self.repo.heads[branch_name].checkout()
    
    def _create_commit_message(self, change: Change, parent_repo_hash: Optional[str] = None) -> str:
        """Create a descriptive commit message for a change."""
        file_name = change.file_path.name
        change_type = change.change_type.value
        
        if change.change_type.name == "EDIT" and change.old_string and change.new_string:
            # For edits, show what changed
            old_preview = change.old_string[:50] + "..." if len(change.old_string) > 50 else change.old_string
            new_preview = change.new_string[:50] + "..." if len(change.new_string) > 50 else change.new_string
            base_msg = f"{change_type}: {file_name}\n\n- {old_preview}\n+ {new_preview}"
        else:
            # For writes or other changes
            base_msg = f"{change_type}: {file_name}\n\nUpdated by Claude at {change.timestamp}"
        
        if parent_repo_hash:
            base_msg += f"\n\nParent repo: {parent_repo_hash[:8]}"
        
        return base_msg
    
    def _update_session_with_commit(self, session_id: str, commit_hash: str) -> None:
        """Update session metadata with new commit."""
        sessions = self._load_sessions()
        
        for session in sessions:
            if session.id == session_id:
                if not hasattr(session, 'change_ids') or session.change_ids is None:
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
            self.repo.index.commit(f"Update sessions metadata - {len(sessions)} sessions")
        except git.exc.GitCommandError:
            # Ignore commit errors for sessions file updates
            pass
    
    def _create_patch(self, change: Change) -> str:
        """Create a patch file for a Claude change."""
        if change.change_type.name == "WRITE":
            # For new files, create a patch that adds the entire file
            lines = change.new_content.split('\n')
            patch_lines = [
                f"--- /dev/null",
                f"+++ {change.file_path}",
                f"@@ -0,0 +1,{len(lines)} @@"
            ]
            patch_lines.extend(f"+{line}" for line in lines)
            return '\n'.join(patch_lines)
        
        elif change.change_type.name == "EDIT" and change.old_string and change.new_string:
            # For edits, create a patch showing the specific change
            # This is simplified - real implementation would need proper diff context
            return f"""--- {change.file_path}
+++ {change.file_path}
@@ -1,1 +1,1 @@
-{change.old_string}
+{change.new_string}
"""
        
        else:
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
            status_output = parent_repo.git.status("--porcelain=v2", "--untracked-files=all")
            
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
                "has_changes": bool(status_output.strip())
            }
            
            for line in status_output.strip().split('\n'):
                if not line:
                    continue
                    
                parts = line.split()
                if len(parts) < 2:
                    continue
                
                # Parse porcelain v2 format
                if line.startswith('1 '):  # Tracked file with changes
                    # Format: 1 <XY> <sub> <mH> <mI> <mW> <hH> <hI> <path>
                    xy_status = parts[1]
                    path = ' '.join(parts[8:]) if len(parts) > 8 else parts[-1]
                    
                    if 'M' in xy_status:
                        status_info["modified_files"].append(path)
                    if 'A' in xy_status:
                        status_info["added_files"].append(path)
                    if 'D' in xy_status:
                        status_info["deleted_files"].append(path)
                        
                elif line.startswith('2 '):  # Renamed file
                    # Format: 2 <XY> <sub> <mH> <mI> <mW> <hH> <hI> <X><score> <path><sep><origPath>
                    path_part = ' '.join(parts[9:]) if len(parts) > 9 else parts[-1]
                    status_info["renamed_files"].append(path_part)
                    
                elif line.startswith('? '):  # Untracked file
                    path = line[2:]  # Remove "? " prefix
                    # Skip .claude-git directory
                    if not path.startswith('.claude-git'):
                        status_info["untracked_files"].append(path)
                    
                elif line.startswith('! '):  # Ignored file
                    path = line[2:]  # Remove "! " prefix  
                    status_info["ignored_files"].append(path)
            
            # Get file hashes for modified files to detect content changes
            for modified_file in status_info["modified_files"]:
                try:
                    file_path = self.project_root / modified_file
                    if file_path.exists() and file_path.is_file():
                        import hashlib
                        content = file_path.read_bytes()
                        status_info["file_hashes"][modified_file] = hashlib.sha256(content).hexdigest()[:16]
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
            "recommendations": []
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
            if (modified_dir == claude_dir and modified_filename != claude_filename) or \
               (modified_filename == claude_filename and modified_dir != claude_dir):
                conflicts["related_files_modified"].append(modified_file)
                
        if conflicts["related_files_modified"]:
            conflicts["has_conflicts"] = True
            conflicts["recommendations"].append(
                f"📁 Related files modified: {', '.join(conflicts['related_files_modified'])}"
            )
        
        # Track all human modifications for context
        for category in ["modified_files", "added_files", "deleted_files", "untracked_files"]:
            for file_path in status.get(category, []):
                conflicts["human_modifications"].append({
                    "file": file_path,
                    "type": category.replace("_files", ""),
                    "hash": status.get("file_hashes", {}).get(file_path)
                })
        
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
    
    def get_meaningful_diff(self, limit: int = 10) -> Dict:
        """Get a human-readable diff showing Claude's recent changes vs current file state."""
        diff_results = {
            "changes_analyzed": [],
            "files_modified_since_claude": [],
            "files_unchanged_since_claude": [],
            "files_not_found": [],
            "summary": {
                "total_claude_changes": 0,
                "user_modified_after_claude": 0,
                "claude_changes_intact": 0,
                "conflicts": 0
            }
        }
        
        # Get recent commits from current session
        sessions = self._load_sessions()
        if not sessions:
            return diff_results
            
        current_session = max([s for s in sessions if s.is_active], 
                            key=lambda x: x.start_time, default=None)
        
        if not current_session:
            return diff_results
            
        commits = self.get_commits_for_session(current_session.id)
        
        # Analyze recent commits (excluding metadata commits)
        change_commits = [c for c in commits[:limit*2] 
                         if not c.message.startswith("Update sessions metadata")][:limit]
        
        for commit in change_commits:
            try:
                # Find the change JSON file for this commit
                json_files = [f for f in commit.tree.traverse() 
                            if f.name.endswith('.json') and 'changes/' in str(f.path)]
                
                if not json_files:
                    continue
                    
                # Parse the change data
                change_data = json.loads(json_files[0].data_stream.read().decode('utf-8'))
                file_path = Path(change_data["file_path"])
                
                # Analyze this change
                change_analysis = self._analyze_change_vs_current_state(change_data, commit)
                if change_analysis:
                    diff_results["changes_analyzed"].append(change_analysis)
                    
                    # Update summary
                    diff_results["summary"]["total_claude_changes"] += 1
                    
                    if change_analysis["status"] == "user_modified":
                        diff_results["files_modified_since_claude"].append(change_analysis)
                        diff_results["summary"]["user_modified_after_claude"] += 1
                        if change_analysis.get("has_conflicts", False):
                            diff_results["summary"]["conflicts"] += 1
                    elif change_analysis["status"] == "unchanged":
                        diff_results["files_unchanged_since_claude"].append(change_analysis)
                        diff_results["summary"]["claude_changes_intact"] += 1
                    elif change_analysis["status"] == "file_not_found":
                        diff_results["files_not_found"].append(change_analysis)
                        
            except Exception as e:
                # Skip problematic commits but continue processing
                continue
                
        return diff_results
    
    def _analyze_change_vs_current_state(self, change_data: Dict, commit: git.Commit) -> Optional[Dict]:
        """Analyze a single change against the current state of the file."""
        try:
            file_path = Path(change_data["file_path"])
            relative_path = file_path.relative_to(self.project_root)
            
            analysis = {
                "commit_hash": commit.hexsha[:8],
                "commit_message": commit.message.strip().split('\n')[0],
                "commit_time": commit.committed_datetime,
                "file_path": str(relative_path),
                "change_type": change_data.get("change_type", "unknown"),
                "status": "unknown",
                "diff_lines": [],
                "has_conflicts": False,
                "user_changes_detected": []
            }
            
            # Check if file currently exists
            if not file_path.exists():
                analysis["status"] = "file_not_found"
                analysis["diff_lines"] = [f"❌ File {relative_path} no longer exists"]
                return analysis
            
            # Get current file content
            current_content = file_path.read_text(encoding='utf-8')
            
            # Compare against Claude's expected result
            if change_data["change_type"] == "write":
                # For writes, compare against the new_content Claude created
                claude_content = change_data.get("new_content", "")
                
                if current_content == claude_content:
                    analysis["status"] = "unchanged"
                    analysis["diff_lines"] = [f"✅ File {relative_path} unchanged since Claude wrote it"]
                else:
                    analysis["status"] = "user_modified"
                    analysis["has_conflicts"] = True
                    # Generate diff
                    diff_lines = list(difflib.unified_diff(
                        claude_content.splitlines(keepends=True),
                        current_content.splitlines(keepends=True),
                        fromfile=f"Claude's version ({commit.hexsha[:8]})",
                        tofile="Current version",
                        lineterm=""
                    ))
                    analysis["diff_lines"] = diff_lines[:50]  # Limit output
                    
            elif change_data["change_type"] == "edit":
                # For edits, this is more complex - we need to check if the edit was applied
                # and if additional changes were made
                
                old_string = change_data.get("old_string", "")
                new_string = change_data.get("new_string", "")
                
                if not old_string or not new_string:
                    analysis["status"] = "incomplete_data"
                    return analysis
                
                # Check if Claude's change is still present
                if new_string in current_content:
                    # Claude's change is present, but check if there are additional modifications
                    # Compare against the old_content if available
                    old_content = change_data.get("old_content", "")
                    
                    if old_content:
                        # Reconstruct what Claude intended the file to be
                        if old_string in old_content:
                            claude_intended = old_content.replace(old_string, new_string)
                            
                            if current_content == claude_intended:
                                analysis["status"] = "unchanged"
                                analysis["diff_lines"] = [f"✅ Claude's edit to {relative_path} is intact"]
                            else:
                                analysis["status"] = "user_modified"
                                # Generate diff showing additional user changes
                                diff_lines = list(difflib.unified_diff(
                                    claude_intended.splitlines(keepends=True),
                                    current_content.splitlines(keepends=True),
                                    fromfile=f"After Claude's edit ({commit.hexsha[:8]})",
                                    tofile="Current version", 
                                    lineterm=""
                                ))
                                analysis["diff_lines"] = diff_lines[:50]
                                
                                # Check for conflicting changes to the same area
                                if old_string in current_content:
                                    analysis["has_conflicts"] = True
                                    analysis["user_changes_detected"].append(
                                        "⚠️  User may have reverted Claude's change"
                                    )
                        else:
                            analysis["status"] = "incomplete_data" 
                    else:
                        # No old_content available, just check if new_string is present
                        analysis["status"] = "unchanged"
                        analysis["diff_lines"] = [f"✅ Claude's change found in {relative_path}"]
                        
                else:
                    # Claude's change is not present - either reverted or file changed significantly
                    analysis["status"] = "user_modified"
                    analysis["has_conflicts"] = True
                    analysis["user_changes_detected"].append(
                        f"❌ Claude's change '{new_string[:50]}...' not found in current file"
                    )
                    
                    # Check if the old string is back
                    if old_string in current_content:
                        analysis["user_changes_detected"].append(
                            "🔄 Original content appears to be restored"
                        )
            
            # Add revert capability analysis
            analysis["revert_info"] = self._analyze_revert_capability(change_data, analysis["status"])
            
            return analysis
            
        except Exception as e:
            return {
                "commit_hash": commit.hexsha[:8], 
                "file_path": change_data.get("file_path", "unknown"),
                "status": "error",
                "error": str(e)
            }
    
    def _analyze_revert_capability(self, change_data: Dict, current_status: str) -> Dict:
        """Analyze whether a Claude change can be safely reverted."""
        revert_info = {
            "can_revert": False,
            "revert_type": "unknown", 
            "revert_command": None,
            "warnings": [],
            "confidence": "low",
            "parent_repo_info": {}
        }
        
        try:
            file_path = Path(change_data["file_path"])
            
            if not file_path.exists():
                revert_info["warnings"].append("❌ File no longer exists - cannot revert")
                return revert_info
            
            change_type = change_data.get("change_type", "unknown")
            current_content = file_path.read_text(encoding='utf-8')
            
            # Analyze parent repo status to understand user's changes
            claude_change_hash = change_data.get("parent_repo_hash")
            claude_change_status = change_data.get("parent_repo_status", {})
            current_parent_status = self._get_parent_repo_status()
            current_parent_hash = self._get_parent_repo_hash()
            
            revert_info["parent_repo_info"] = {
                "hash_at_claude_change": claude_change_hash,
                "current_hash": current_parent_hash,
                "user_committed_since_claude": claude_change_hash != current_parent_hash,
                "repo_has_uncommitted_changes": current_parent_status.get("has_changes", False) if current_parent_status else False
            }
            
            # Check if user has committed changes to the main repo since Claude's change
            user_committed_since = revert_info["parent_repo_info"]["user_committed_since_claude"]
            
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
                    current_parent_status.get("modified_files", []) + 
                    current_parent_status.get("added_files", []) +
                    current_parent_status.get("deleted_files", [])
                )
                file_in_user_changes = relative_path in all_changed_files
                
                if file_in_user_changes:
                    revert_info["warnings"].append(
                        f"⚠️  File has uncommitted changes in main repo - reverting Claude's change may conflict"
                    )
            
            if change_type == "write":
                # For writes, check if we can restore the original file or delete it
                old_content = change_data.get("old_content")
                
                if old_content is not None and old_content == "":
                    # File was created by Claude
                    revert_info["can_revert"] = True
                    revert_info["revert_type"] = "delete_file"
                    revert_info["revert_command"] = f"claude-git rollback {change_data.get('id', 'HASH')}"
                    revert_info["confidence"] = "high"
                    
                    if current_status == "user_modified":
                        revert_info["warnings"].append(
                            "⚠️  File has been modified since Claude created it - reverting will lose user changes"
                        )
                        revert_info["confidence"] = "medium"
                        
                    # Adjust confidence based on parent repo status
                    if user_committed_since or file_in_user_changes:
                        revert_info["confidence"] = "medium" if revert_info["confidence"] == "high" else "low"
                        
                elif old_content:
                    # File was overwritten by Claude
                    revert_info["can_revert"] = True
                    revert_info["revert_type"] = "restore_original"
                    revert_info["revert_command"] = f"claude-git rollback {change_data.get('id', 'HASH')}"
                    revert_info["confidence"] = "high"
                    
                    if current_status == "user_modified":
                        revert_info["warnings"].append(
                            "⚠️  File has been modified since Claude overwrote it - reverting will lose user changes"
                        )
                        revert_info["confidence"] = "low"
                        
                    # Adjust confidence based on parent repo status  
                    if user_committed_since or file_in_user_changes:
                        revert_info["confidence"] = "medium" if revert_info["confidence"] == "high" else "low"
                        if user_committed_since and not file_in_user_changes:
                            revert_info["warnings"].append(
                                "✅ User committed main repo changes - reverting Claude's change is safer"
                            )
                        
            elif change_type == "edit":
                # For edits, check if we can reverse the string replacement
                old_string = change_data.get("old_string", "")
                new_string = change_data.get("new_string", "")
                
                if old_string and new_string:
                    if new_string in current_content:
                        # Claude's change is still present and can be reversed
                        revert_info["can_revert"] = True
                        revert_info["revert_type"] = "reverse_edit"
                        revert_info["revert_command"] = f"claude-git rollback {change_data.get('id', 'HASH')}"
                        
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
                            revert_info["warnings"].append(
                                "⚠️  File has uncommitted changes - reverting may conflict"
                            )
                            
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