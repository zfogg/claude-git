#!/usr/bin/env python3
"""Claude Code SessionEnd hook - creates logical commit with thinking text and chronological changes."""

import json
import sys
from datetime import datetime
from pathlib import Path

from claude_git.core.git_native_repository import GitNativeRepository


def extract_chronological_thinking_and_changes(
    transcript_path: str, debug_log: Path
) -> str:
    """Extract Claude's thinking and tool changes chronologically from transcript."""
    if not transcript_path or not Path(transcript_path).exists():
        return ""

    chronological_events = []

    try:
        with open(transcript_path) as f:
            lines = f.readlines()

        # Process transcript entries chronologically
        for line in lines:
            try:
                entry = json.loads(line.strip())

                # Look for assistant messages
                if (
                    entry.get("type") == "assistant"
                    and "message" in entry
                    and entry["message"].get("role") == "assistant"
                ):
                    content = entry["message"].get("content", [])
                    if isinstance(content, list):
                        for item in content:
                            # Extract thinking text
                            if item.get("type") == "text" and item.get(
                                "thinking", False
                            ):
                                thinking_text = item.get("text", "").strip()
                                if thinking_text:
                                    chronological_events.append(
                                        {
                                            "type": "thinking",
                                            "text": thinking_text,
                                            "timestamp": entry.get("timestamp", ""),
                                        }
                                    )

                            # Extract tool uses (file changes)
                            elif item.get("type") == "tool_use":
                                tool_name = item.get("name", "")
                                if tool_name in ["Edit", "Write", "MultiEdit"]:
                                    tool_input = item.get("input", {})
                                    file_path = tool_input.get("file_path", "unknown")

                                    # Create human-readable description
                                    if tool_name == "Write":
                                        action = f"Created {Path(file_path).name}"
                                    elif tool_name == "Edit":
                                        old_str = tool_input.get("old_string", "")
                                        new_str = tool_input.get("new_string", "")
                                        if old_str and new_str:
                                            action = f"Changed {Path(file_path).name}: '{old_str[:30]}...' → '{new_str[:30]}...'"
                                        else:
                                            action = f"Modified {Path(file_path).name}"
                                    elif tool_name == "MultiEdit":
                                        edits = tool_input.get("edits", [])
                                        action = f"Made {len(edits)} changes to {Path(file_path).name}"
                                    else:
                                        action = (
                                            f"{tool_name} on {Path(file_path).name}"
                                        )

                                    chronological_events.append(
                                        {
                                            "type": "file_change",
                                            "text": action,
                                            "tool": tool_name,
                                            "file": file_path,
                                            "timestamp": entry.get("timestamp", ""),
                                        }
                                    )

            except (json.JSONDecodeError, KeyError):
                continue

        # Build chronological commit message
        if not chronological_events:
            return ""

        # Group into narrative sections
        thinking_sections = []
        current_section = {"thinking": [], "actions": []}

        for event in chronological_events:
            if event["type"] == "thinking":
                # If we have actions accumulated, save current section
                if current_section["actions"]:
                    thinking_sections.append(current_section)
                    current_section = {"thinking": [], "actions": []}
                current_section["thinking"].append(event["text"])
            else:  # file_change
                current_section["actions"].append(event["text"])

        # Add final section if it has content
        if current_section["thinking"] or current_section["actions"]:
            thinking_sections.append(current_section)

        # Build narrative commit message
        message_parts = []

        for _i, section in enumerate(thinking_sections):
            if section["thinking"]:
                # Add thinking text
                thinking_text = "\n".join(section["thinking"])
                message_parts.append(thinking_text)

                if section["actions"]:
                    # Add actions that followed this thinking
                    message_parts.append(
                        "\n" + "\n".join(f"→ {action}" for action in section["actions"])
                    )

        return "\n\n".join(message_parts) if message_parts else ""

    except Exception as e:
        with open(debug_log, "a") as f:
            f.write(f"Error extracting chronological events: {e}\n")
        return ""


def main():
    """Handle Claude Code SessionEnd event."""
    debug_log = Path.home() / ".claude" / "claude-git-debug.log"

    with open(debug_log, "a") as f:
        f.write(f"SessionEnd hook called at {datetime.now()}\n")

    try:
        # Read hook input from stdin
        hook_input = sys.stdin.read().strip()
        if not hook_input:
            with open(debug_log, "a") as f:
                f.write("No hook input provided to SessionEnd\n")
            sys.exit(0)

        # Parse hook data
        hook_data = json.loads(hook_input)
        transcript_path = hook_data.get("transcript_path")

        with open(debug_log, "a") as f:
            f.write(f"SessionEnd hook data: transcript_path={transcript_path}\n")

        # Find the project root (look for .git directory)
        current_dir = Path.cwd()
        project_root = None

        for parent in [current_dir] + list(current_dir.parents):
            if (parent / ".git").exists():
                project_root = parent
                break

        if not project_root:
            with open(debug_log, "a") as f:
                f.write("No git repository found in SessionEnd\n")
            sys.exit(0)

        # Check if claude-git repository exists
        git_repo = GitNativeRepository(project_root)
        if not git_repo.exists():
            with open(debug_log, "a") as f:
                f.write("Claude-git not initialized, skipping SessionEnd\n")
            sys.exit(0)

        # Extract chronological thinking and changes from transcript
        thinking_and_changes = ""
        if transcript_path and Path(transcript_path).exists():
            thinking_and_changes = extract_chronological_thinking_and_changes(
                transcript_path, debug_log
            )

        # End session - creates logical commit with all accumulated changes
        commit_hash = git_repo.session_end(thinking_and_changes)

        if commit_hash:
            with open(debug_log, "a") as f:
                f.write(f"✅ Created logical commit: {commit_hash}\n")
            print(
                f"🎯 Claude-git: Session complete - created logical commit {commit_hash[:8]}"
            )
        else:
            with open(debug_log, "a") as f:
                f.write("ℹ️  Session ended with no changes to commit\n")
            print("ℹ️  Claude-git: Session ended with no changes")

    except Exception as e:
        with open(debug_log, "a") as f:
            f.write(f"❌ Error in SessionEnd hook: {e}\n")
        # Don't fail the hook - Claude Code should continue working
        sys.exit(0)


if __name__ == "__main__":
    main()
