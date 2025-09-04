#!/usr/bin/env python3
"""Git-native hook handlers for Claude Code integration.

This module provides hook handlers that integrate with the GitNativeRepository
to create logical commit boundaries based on Claude's work sessions.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from claude_git.core.git_native_repository import GitNativeRepository


def extract_thinking_text_from_transcript(transcript_path: str) -> Optional[str]:
    """Extract Claude's thinking text from JSONL transcript file.

    Args:
        transcript_path: Path to the Claude Code transcript JSONL file

    Returns:
        Combined thinking text from Claude's reasoning process, or None if not found
    """
    thinking_messages = []

    try:
        with open(transcript_path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue

                try:
                    entry = json.loads(line.strip())

                    # Look for assistant messages with thinking flag
                    if (
                        entry.get("type") == "message"
                        and entry.get("role") == "assistant"
                        and entry.get("thinking")
                    ):
                        content = entry.get("content", [])
                        if isinstance(content, list):
                            for item in content:
                                if item.get("type") == "text" and item.get("text"):
                                    thinking_messages.append(item["text"].strip())

                except json.JSONDecodeError:
                    continue

    except OSError:
        return None

    if not thinking_messages:
        return None

    # Combine thinking messages into coherent summary
    # Remove duplicates while preserving order
    unique_thoughts = []
    seen = set()
    for thought in thinking_messages:
        if thought and thought not in seen:
            unique_thoughts.append(thought)
            seen.add(thought)

    # Join thoughts with proper formatting for git commit message
    # Limit to top 5 most important thoughts to avoid overly long commit messages
    return "\n\n".join(unique_thoughts[:5]) if unique_thoughts else None


def extract_file_path_from_tool_data(tool_data: Dict[str, Any]) -> Optional[str]:
    """Extract file path from tool input parameters.

    Args:
        tool_data: Tool data containing name and parameters

    Returns:
        File path string, or None if not found
    """
    if not tool_data:
        return None

    parameters = tool_data.get("parameters", {})

    # Check common parameter names for file paths
    for param_name in ["file_path", "notebook_path", "path"]:
        if param_name in parameters and parameters[param_name]:
            return str(parameters[param_name])

    # For MultiEdit, look for file_path in the top level
    if "file_path" in parameters:
        return str(parameters["file_path"])

    return None


def extract_latest_tool_from_transcript(
    transcript_path: str,
) -> Optional[Dict[str, Any]]:
    """Extract the most recent file-modifying tool call from transcript.

    Args:
        transcript_path: Path to the Claude Code transcript JSONL file

    Returns:
        Tool data dict with name and parameters, or None if not found
    """
    try:
        with open(transcript_path, encoding="utf-8") as f:
            lines = f.readlines()

        # Look for the last tool call in the transcript
        for line in reversed(lines):
            if not line.strip():
                continue

            try:
                entry = json.loads(line.strip())

                # Look for assistant messages with tool_use content
                if entry.get("type") == "message" and entry.get("role") == "assistant":
                    content = entry.get("content", [])
                    if isinstance(content, list):
                        # Get the last tool in the message (most recent)
                        for item in reversed(content):
                            if item.get("type") == "tool_use":
                                tool_name = item.get("name", "")
                                # Only track file-modifying tools
                                if tool_name in [
                                    "Edit",
                                    "Write",
                                    "MultiEdit",
                                    "NotebookEdit",
                                ]:
                                    return {
                                        "name": tool_name,
                                        "parameters": item.get("input", {}),
                                    }

            except json.JSONDecodeError:
                continue

        return None

    except OSError:
        return None


def find_git_native_repository(
    start_path: Path = None,
) -> Optional[GitNativeRepository]:
    """Find and initialize GitNativeRepository from current or parent directories.

    Args:
        start_path: Path to start searching from (defaults to cwd)

    Returns:
        GitNativeRepository instance, or None if not found
    """
    if start_path is None:
        start_path = Path.cwd()

    # Look for git repository root
    current_dir = Path(start_path).resolve()
    for parent in [current_dir] + list(current_dir.parents):
        if (parent / ".git").exists():
            # Found git repo - check if claude-git is initialized
            git_native_repo = GitNativeRepository(parent)
            if git_native_repo.exists():
                return git_native_repo
            # Initialize it if it doesn't exist
            try:
                git_native_repo.init()
                return git_native_repo
            except Exception:
                return None

    return None


def handle_pre_tool_use_hook(hook_data: Dict[str, Any], debug_log: Path) -> None:
    """Handle PreToolUse hook - called when Claude is about to use a tool.

    This detects when Claude starts working and initializes session tracking.

    Args:
        hook_data: Hook data from Claude Code
        debug_log: Path to debug log file
    """
    with open(debug_log, "a") as f:
        f.write(f"[PreToolUse] Hook called at {datetime.now()}\n")

    # Find git-native repository
    git_repo = find_git_native_repository()
    if not git_repo:
        with open(debug_log, "a") as f:
            f.write("[PreToolUse] No git-native repository found\n")
        return

    # Extract session information
    session_id = hook_data.get("session_id", "unknown-session")

    # Start session if not already active
    if not git_repo._session_active:
        with open(debug_log, "a") as f:
            f.write(f"[PreToolUse] Starting Claude session: {session_id}\n")
        git_repo.session_start(session_id)

    # Extract tool information for change tracking preparation
    tool_data = hook_data.get("tool", {})
    tool_name = tool_data.get("name", "")

    with open(debug_log, "a") as f:
        f.write(f"[PreToolUse] Tool preparation: {tool_name}\n")


def handle_stop_hook(hook_data: Dict[str, Any], debug_log: Path) -> None:
    """Handle Stop hook - called when Claude stops working.

    This creates logical commits with thinking text when Claude finishes.

    Args:
        hook_data: Hook data from Claude Code
        debug_log: Path to debug log file
    """
    with open(debug_log, "a") as f:
        f.write(f"[Stop] Hook called at {datetime.now()}\n")

    # Find git-native repository
    git_repo = find_git_native_repository()
    if not git_repo:
        with open(debug_log, "a") as f:
            f.write("[Stop] No git-native repository found\n")
        return

    # Only proceed if we have an active session
    if not git_repo._session_active:
        with open(debug_log, "a") as f:
            f.write("[Stop] No active Claude session to end\n")
        return

    # Extract thinking text from transcript
    thinking_text = None
    transcript_path = hook_data.get("transcript_path")
    if transcript_path and Path(transcript_path).exists():
        with open(debug_log, "a") as f:
            f.write(f"[Stop] Extracting thinking text from: {transcript_path}\n")
        thinking_text = extract_thinking_text_from_transcript(transcript_path)

        if thinking_text:
            with open(debug_log, "a") as f:
                f.write(
                    f"[Stop] Extracted {len(thinking_text)} chars of thinking text\n"
                )
        else:
            with open(debug_log, "a") as f:
                f.write("[Stop] No thinking text found in transcript\n")

    # End session and create logical commit
    try:
        commit_hash = git_repo.session_end(thinking_text)
        if commit_hash:
            with open(debug_log, "a") as f:
                f.write(f"[Stop] Created logical commit: {commit_hash[:8]}\n")
        else:
            with open(debug_log, "a") as f:
                f.write("[Stop] No changes to commit\n")
    except Exception as e:
        with open(debug_log, "a") as f:
            f.write(f"[Stop] Error creating commit: {e}\n")


def handle_tool_completion_hook(hook_data: Dict[str, Any], debug_log: Path) -> None:
    """Handle tool completion - accumulate changes during Claude's session.

    This is called after each tool use to track file modifications.

    Args:
        hook_data: Hook data from Claude Code
        debug_log: Path to debug log file
    """
    with open(debug_log, "a") as f:
        f.write(f"[ToolCompletion] Hook called at {datetime.now()}\n")

    # Find git-native repository
    git_repo = find_git_native_repository()
    if not git_repo:
        with open(debug_log, "a") as f:
            f.write("[ToolCompletion] No git-native repository found\n")
        return

    # Extract tool information
    tool_data = hook_data.get("tool", {})
    if not tool_data:
        # Try to extract from transcript
        transcript_path = hook_data.get("transcript_path")
        if transcript_path and Path(transcript_path).exists():
            tool_data = extract_latest_tool_from_transcript(transcript_path)

    if not tool_data:
        with open(debug_log, "a") as f:
            f.write("[ToolCompletion] No tool data found\n")
        return

    tool_name = tool_data.get("name", "")
    if tool_name not in ["Edit", "Write", "MultiEdit", "NotebookEdit"]:
        with open(debug_log, "a") as f:
            f.write(f"[ToolCompletion] Tool {tool_name} not tracked\n")
        return

    # Extract file path
    file_path = extract_file_path_from_tool_data(tool_data)
    if not file_path:
        with open(debug_log, "a") as f:
            f.write("[ToolCompletion] No file path found in tool data\n")
        return

    # Accumulate the change
    try:
        git_repo.accumulate_change(file_path, tool_name, tool_data)
        with open(debug_log, "a") as f:
            f.write(
                f"[ToolCompletion] Accumulated change: {tool_name} on {file_path}\n"
            )
    except Exception as e:
        with open(debug_log, "a") as f:
            f.write(f"[ToolCompletion] Error accumulating change: {e}\n")


def parse_hook_input() -> Dict[str, Any]:
    """Parse hook input from stdin or command line arguments."""
    hook_input = ""

    try:
        # Read from stdin (primary method from Claude Code)
        hook_input = sys.stdin.read().strip()
        if not hook_input and len(sys.argv) > 1:
            # Fallback to command line args for testing
            hook_input = sys.argv[1]
    except Exception:
        pass

    if not hook_input:
        return {}

    try:
        return json.loads(hook_input)
    except json.JSONDecodeError:
        return {}


def main():
    """Main git-native hook handler entry point.

    This function determines which hook type is being called and routes
    to the appropriate handler based on the hook data.
    """
    # Set up debug logging
    debug_log = Path.home() / ".claude" / "claude-git-debug.log"
    debug_log.parent.mkdir(exist_ok=True)

    # Parse hook input
    hook_data = parse_hook_input()
    if not hook_data:
        with open(debug_log, "a") as f:
            f.write(f"Git-native hook called with no data at {datetime.now()}\n")
        return

    # Determine hook type and route appropriately
    hook_type = hook_data.get("hook_type", "unknown")

    with open(debug_log, "a") as f:
        f.write(f"Git-native hook called: type={hook_type} at {datetime.now()}\n")
        f.write(f"Hook data keys: {list(hook_data.keys())}\n")

    try:
        if hook_type == "PreToolUse":
            handle_pre_tool_use_hook(hook_data, debug_log)
        elif hook_type == "Stop":
            handle_stop_hook(hook_data, debug_log)
        elif hook_type == "ToolCompletion" or "tool" in hook_data:
            # Handle both explicit ToolCompletion and generic tool completion
            handle_tool_completion_hook(hook_data, debug_log)
        else:
            with open(debug_log, "a") as f:
                f.write(f"Unknown hook type: {hook_type}\n")
    except Exception as e:
        with open(debug_log, "a") as f:
            f.write(f"Error handling hook: {e}\n")


if __name__ == "__main__":
    main()
