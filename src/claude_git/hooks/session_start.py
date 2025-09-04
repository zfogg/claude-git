#!/usr/bin/env python3
"""Claude Code SessionStart hook - begins accumulating changes for logical commit."""

import json
import sys
from datetime import datetime
from pathlib import Path

from claude_git.core.git_native_repository import GitNativeRepository


def main():
    """Handle Claude Code SessionStart event."""
    debug_log = Path.home() / ".claude" / "claude-git-debug.log"

    with open(debug_log, "a") as f:
        f.write(f"SessionStart hook called at {datetime.now()}\n")

    try:
        # Read hook input from stdin
        hook_input = sys.stdin.read().strip()
        if not hook_input:
            with open(debug_log, "a") as f:
                f.write("No hook input provided to SessionStart\n")
            sys.exit(0)

        # Parse hook data
        hook_data = json.loads(hook_input)

        with open(debug_log, "a") as f:
            f.write(f"SessionStart hook data: {json.dumps(hook_data, indent=2)}\n")

        # Find the project root (look for .git directory)
        current_dir = Path.cwd()
        project_root = None

        for parent in [current_dir] + list(current_dir.parents):
            if (parent / ".git").exists():
                project_root = parent
                break

        if not project_root:
            with open(debug_log, "a") as f:
                f.write("No git repository found in SessionStart\n")
            sys.exit(0)

        # Check if claude-git repository exists
        git_repo = GitNativeRepository(project_root)
        if not git_repo.exists():
            with open(debug_log, "a") as f:
                f.write("Claude-git not initialized, skipping SessionStart\n")
            sys.exit(0)

        # Generate session ID from timestamp and context
        session_id = f"session-{datetime.now().strftime('%Y-%m-%d-%H-%M')}"

        # Start session - this will commit any pending user changes first
        git_repo.session_start(session_id)

        with open(debug_log, "a") as f:
            f.write(f"✅ Started Claude session: {session_id}\n")

        # Optional: Print to user (will show in Claude Code output)
        print(f"🚀 Claude-git: Started session {session_id}")

    except Exception as e:
        with open(debug_log, "a") as f:
            f.write(f"❌ Error in SessionStart hook: {e}\n")
        # Don't fail the hook - Claude Code should continue working
        sys.exit(0)


if __name__ == "__main__":
    main()
