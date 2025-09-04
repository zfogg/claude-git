#!/usr/bin/env python3
"""Hook script for capturing Claude changes."""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from claude_git.core.git_native_repository import GitNativeRepository


def extract_latest_tool_from_transcript(
    transcript_path: str, debug_log: Path
) -> Dict[str, Any]:
    """Extract the latest tool call from the transcript file."""
    try:
        with open(transcript_path) as f:
            lines = f.readlines()

        # Look for the last tool call in the transcript
        for line in reversed(lines):
            try:
                entry = json.loads(line.strip())
                # Look for assistant messages with content array containing tool_use
                if entry.get("type") == "assistant" and "message" in entry:
                    content = entry["message"].get("content", [])
                    if isinstance(content, list):
                        for item in reversed(
                            content
                        ):  # Get the last tool in the message
                            if item.get("type") == "tool_use":
                                tool_name = item.get("name", "")
                                if tool_name in ["Edit", "Write", "MultiEdit"]:
                                    parameters = item.get("input", {})
                                    return {"name": tool_name, "parameters": parameters}
            except (json.JSONDecodeError, KeyError):
                continue

        with open(debug_log, "a") as f:
            f.write("No matching tool calls found in transcript\n")
        return {}

    except Exception as e:
        with open(debug_log, "a") as f:
            f.write(f"Error reading transcript: {e}\n")
        return {}


def parse_hook_input(hook_input: str) -> Dict[str, Any]:
    """Parse the hook input JSON."""
    try:
        return json.loads(hook_input)
    except json.JSONDecodeError as e:
        print(f"Error parsing hook input: {e}", file=sys.stderr)
        sys.exit(1)


def auto_commit_file_change(
    file_path: Path,
    project_root: Path,
    claude_git_dir: Path,
    debug_log: Path,
    tool_name: str = "FileChange",
) -> bool:
    """Auto-commit a file change to the claude-git fork."""
    try:
        from claude_git.core.git_native_repository import GitNativeRepository

        # Get relative path for commit message
        relative_path = file_path.relative_to(project_root)

        # Initialize git repo manager
        git_repo = GitNativeRepository(project_root)

        # Check if file exists or was deleted
        if file_path.exists():
            action = "modify"
        else:
            action = "delete"

        # Create auto-commit message
        message = f"{tool_name}: {action} {relative_path}"

        # Auto-commit the change (files are already in the fork from git clone)
        commit_hash = git_repo.auto_commit_change(message, [str(relative_path)])

        with open(debug_log, "a") as f:
            f.write(
                f"✅ Auto-committed {action} of {relative_path} -> {commit_hash[:8]}\n"
            )
        return True

    except Exception as e:
        with open(debug_log, "a") as f:
            f.write(f"❌ Error auto-committing {file_path}: {e}\n")
        return False


def extract_changed_files(tool_data: Dict[str, Any]) -> List[Path]:
    """Extract list of changed files from tool data."""
    tool_name = tool_data.get("name", "")
    parameters = tool_data.get("parameters", {})

    changed_files = []

    # Extract file path(s) depending on tool type
    if tool_name in ["Edit", "Write"] or tool_name == "MultiEdit":
        file_path_str = parameters.get("file_path")
        if file_path_str:
            changed_files.append(Path(file_path_str))

    return changed_files


def extract_thinking_text_from_transcript(
    transcript_path: str, debug_log: Path
) -> List[str]:
    """Extract Claude's thinking text from the transcript file."""
    try:
        with open(transcript_path) as f:
            lines = f.readlines()

        # Look for recent thinking messages in Claude Code format
        recent_thinking = []
        for line in lines[-100:]:  # Check last 100 lines for recent context
            try:
                entry = json.loads(line.strip())

                # Check if this is an assistant message entry
                if (
                    entry.get("type") == "assistant"
                    and "message" in entry
                    and entry["message"].get("role") == "assistant"
                ):
                    content = entry["message"].get("content", [])
                    if isinstance(content, list):
                        for item in content:
                            # Look for thinking text - it might be marked differently
                            if item.get("type") == "text" and item.get(
                                "thinking", False
                            ):
                                thinking_text = item.get("text", "").strip()
                                if thinking_text and len(thinking_text) < 500:
                                    recent_thinking.append(thinking_text)
                            # Also check for text without explicit thinking flag but with context
                            elif (
                                item.get("type") == "text"
                                and "thinking" not in item  # No explicit thinking field
                                and len(item.get("text", "")) < 200
                            ):  # Short, likely internal thought
                                text = item.get("text", "").strip()
                                # Filter for thinking-like patterns
                                if text and any(
                                    phrase in text.lower()
                                    for phrase in [
                                        "i need to",
                                        "let me",
                                        "i should",
                                        "i'll",
                                        "i want to",
                                        "thinking about",
                                        "looking at",
                                        "checking",
                                        "verifying",
                                    ]
                                ):
                                    recent_thinking.append(text)

            except (json.JSONDecodeError, KeyError):
                continue

        # Return the most recent thinking texts (last few)
        filtered_thinking = recent_thinking[-5:] if recent_thinking else []

        with open(debug_log, "a") as f:
            f.write(
                f"Extracted {len(filtered_thinking)} thinking texts from transcript\n"
            )

        return filtered_thinking

    except Exception as e:
        with open(debug_log, "a") as f:
            f.write(f"Error extracting thinking text: {e}\n")
        return []


def git_commit_change(
    claude_git_dir: Path,
    changed_files: List[Path],
    tool_data: Dict[str, Any],
    project_root: Path,
    debug_log: Path,
    transcript_path: str = None,
) -> bool:
    """Create a git commit for the changes."""
    try:
        import subprocess

        # Add changed files to git using relative paths
        for file_path in changed_files:
            # Get the relative path from project root
            relative_path = file_path.relative_to(project_root)
            git_add_result = subprocess.run(
                ["git", "-C", str(claude_git_dir), "add", str(relative_path)],
                capture_output=True,
                text=True,
            )
            if git_add_result.returncode != 0:
                with open(debug_log, "a") as f:
                    f.write(
                        f"Git add failed for {relative_path}: {git_add_result.stderr}\n"
                    )

        # Extract thinking text from transcript
        thinking_texts = []
        if transcript_path and Path(transcript_path).exists():
            thinking_texts = extract_thinking_text_from_transcript(
                transcript_path, debug_log
            )

        # Create enhanced commit message with thinking
        tool_name = tool_data.get("name", "unknown")
        file_names = [f.name for f in changed_files]

        if thinking_texts:
            # Use thinking text as primary message
            primary_message = "\n\n".join(thinking_texts)
            commit_msg = (
                f"{primary_message}\n\nTool: {tool_name} on {', '.join(file_names)}"
            )
        else:
            # Fallback to simple tool message
            commit_msg = f"Claude {tool_name}: {', '.join(file_names)}"

        # Commit the changes
        git_commit_result = subprocess.run(
            ["git", "-C", str(claude_git_dir), "commit", "-m", commit_msg],
            capture_output=True,
            text=True,
        )

        if git_commit_result.returncode != 0:
            with open(debug_log, "a") as f:
                f.write(f"Git commit failed: {git_commit_result.stderr}\n")
            return False

        return True

    except Exception as e:
        with open(debug_log, "a") as f:
            f.write(f"Error creating git commit: {e}\n")
        return False


def main():
    """Main hook function."""
    # Debug: log that the hook was called
    debug_log = Path.home() / ".claude" / "claude-git-debug.log"
    with open(debug_log, "a") as f:
        f.write(f"Git-native hook called at {datetime.now()}: argv={sys.argv}\n")

    # Get hook input - Claude Code passes JSON through stdin
    hook_input = ""
    try:
        # Read from stdin (this is how Claude Code passes the data)
        hook_input = sys.stdin.read().strip()
        if not hook_input and len(sys.argv) > 1:
            # Fallback to command line args for testing
            hook_input = sys.argv[1]
    except Exception as e:
        with open(debug_log, "a") as f:
            f.write(f"Error reading input: {e}\n")
        sys.exit(0)  # Exit gracefully

    if not hook_input:
        with open(debug_log, "a") as f:
            f.write("No hook input provided\n")
        sys.exit(0)  # Exit gracefully instead of error

    with open(debug_log, "a") as f:
        f.write(f"Hook input: {hook_input[:200]}...\n")

    hook_data = parse_hook_input(hook_input)

    # Check if this has tool information
    tool_data = hook_data.get("tool", {})
    if not tool_data:
        # Try to extract tool from transcript file
        transcript_path = hook_data.get("transcript_path")
        if transcript_path and Path(transcript_path).exists():
            with open(debug_log, "a") as f:
                f.write(f"No direct tool data, reading transcript: {transcript_path}\n")

            tool_data = extract_latest_tool_from_transcript(transcript_path, debug_log)
            if not tool_data:
                with open(debug_log, "a") as f:
                    f.write("No tool data found in transcript either\n")
                sys.exit(0)
        else:
            with open(debug_log, "a") as f:
                f.write("No tool data and no transcript path\n")
            sys.exit(0)

    tool_name = tool_data.get("name", "")
    if tool_name not in ["Edit", "Write", "MultiEdit"]:
        with open(debug_log, "a") as f:
            f.write(f"Tool {tool_name} not tracked, exiting\n")
        sys.exit(0)

    # Find the project root (look for .git directory)
    current_dir = Path.cwd()
    project_root = None

    for parent in [current_dir] + list(current_dir.parents):
        if (parent / ".git").exists():
            project_root = parent
            break

    if not project_root:
        with open(debug_log, "a") as f:
            f.write("No git repository found\n")
        sys.exit(0)

    # Check if claude-git repository exists
    claude_git_dir = project_root / ".claude-git"
    if not (claude_git_dir.exists() and (claude_git_dir / ".git").exists()):
        with open(debug_log, "a") as f:
            f.write("No claude-git repository found, skipping\n")
        sys.exit(0)

    # Initialize git-native repository manager
    git_repo = GitNativeRepository(project_root)
    if not git_repo.exists():
        with open(debug_log, "a") as f:
            f.write("Claude-git not properly initialized, skipping\n")
        sys.exit(0)

    # Extract changed files from tool data
    changed_files = extract_changed_files(tool_data)
    if not changed_files:
        with open(debug_log, "a") as f:
            f.write("No changed files found, skipping\n")
        sys.exit(0)

    # Accumulate changes for each file (session-based approach)
    # This will only add to accumulated changes if session is active,
    # or create immediate commit if no session is active
    for file_path in changed_files:
        try:
            git_repo.accumulate_change(
                str(file_path), tool_name, tool_data.get("parameters", {})
            )
            with open(debug_log, "a") as f:
                f.write(f"✅ Accumulated change: {tool_name} on {file_path}\n")
        except Exception as e:
            with open(debug_log, "a") as f:
                f.write(f"❌ Error accumulating change for {file_path}: {e}\n")


if __name__ == "__main__":
    main()
