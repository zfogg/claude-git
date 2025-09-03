"""Claude Git repository management using real git."""

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

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