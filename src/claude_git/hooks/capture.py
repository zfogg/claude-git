#!/usr/bin/env python3
"""Hook script for capturing Claude changes."""

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from claude_git.core.repository import ClaudeGitRepository
from claude_git.models.change import Change, ChangeType


def extract_latest_tool_from_transcript(transcript_path: str, debug_log: Path) -> Dict[str, Any]:
    """Extract the latest tool call from the transcript file."""
    try:
        with open(transcript_path, 'r') as f:
            lines = f.readlines()
        
        # Look for the last tool call in the transcript
        for line in reversed(lines):
            try:
                entry = json.loads(line.strip())
                # Look for assistant messages with content array containing tool_use
                if entry.get("type") == "assistant" and "message" in entry:
                    content = entry["message"].get("content", [])
                    if isinstance(content, list):
                        for item in reversed(content):  # Get the last tool in the message
                            if item.get("type") == "tool_use":
                                tool_name = item.get("name", "")
                                if tool_name in ["Edit", "Write", "MultiEdit"]:
                                    parameters = item.get("input", {})
                                    return {
                                        "name": tool_name,
                                        "parameters": parameters
                                    }
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


def determine_change_type(tool_name: str) -> ChangeType:
    """Determine the change type from tool name."""
    tool_mapping = {
        "Edit": ChangeType.EDIT,
        "Write": ChangeType.WRITE,
        "MultiEdit": ChangeType.MULTI_EDIT,
    }
    return tool_mapping.get(tool_name, ChangeType.EDIT)


def get_file_content_before_change(file_path: Path) -> str:
    """Get the content of a file before Claude's change."""
    try:
        if file_path.exists():
            return file_path.read_text(encoding='utf-8')
        return ""
    except Exception:
        return ""


def extract_change_info(tool_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract change information from tool data."""
    tool_name = tool_data.get("name", "")
    parameters = tool_data.get("parameters", {})
    
    change_info = {
        "tool_name": tool_name,
        "file_path": parameters.get("file_path"),
        "old_string": parameters.get("old_string"),
        "new_string": parameters.get("new_string"),
        "content": parameters.get("content"),
        "edits": parameters.get("edits", []),
    }
    
    return change_info


def create_change_record(tool_data: Dict[str, Any], session_id: str) -> Change:
    """Create a Change record from tool data."""
    change_info = extract_change_info(tool_data)
    
    # Check if file_path is None and handle gracefully
    file_path_str = change_info["file_path"]
    if not file_path_str:
        # Log the error and exit gracefully
        debug_log = Path.home() / ".claude" / "claude-git-debug.log"
        with open(debug_log, "a") as f:
            f.write(f"Error: file_path is None in tool data: {tool_data}\n")
        return None
    
    file_path = Path(file_path_str)
    
    # Get content before change for Edit operations
    old_content = None
    if change_info["tool_name"] == "Edit":
        old_content = get_file_content_before_change(file_path)
    
    # For Write operations, get new content
    new_content = change_info.get("content", "")
    if change_info["tool_name"] == "Edit":
        # For edits, we'll need to reconstruct the new content
        # This is complex and might need the actual file reading after the change
        new_content = file_path.read_text(encoding='utf-8') if file_path.exists() else ""
    
    change = Change(
        id=str(uuid.uuid4()),
        session_id=session_id,
        timestamp=datetime.now(),
        change_type=determine_change_type(change_info["tool_name"]),
        file_path=file_path,
        old_content=old_content,
        new_content=new_content,
        old_string=change_info.get("old_string"),
        new_string=change_info.get("new_string"),
        tool_input=tool_data,
    )
    
    return change


def main():
    """Main hook function."""
    # Debug: log that the hook was called
    debug_log = Path.home() / ".claude" / "claude-git-debug.log"
    with open(debug_log, "a") as f:
        f.write(f"Hook called at {datetime.now()}: argv={sys.argv}\n")
    
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
    
    if not hook_input:
        with open(debug_log, "a") as f:
            f.write("No hook input provided\n")
        sys.exit(0)  # Exit gracefully instead of error
    
    with open(debug_log, "a") as f:
        f.write(f"Hook input: {hook_input[:200]}...\n")
    
    hook_data = parse_hook_input(hook_input)
    
    # The JSON structure from Claude Code looks like:
    # {"session_id": "...", "transcript_path": "...", "cwd": "...", "tool": {...}, ...}
    # or it might have tool data in different structure
    
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
        print("No git repository found", file=sys.stderr)
        sys.exit(1)
    
    # Initialize or get existing Claude Git repository
    claude_repo = ClaudeGitRepository(project_root)
    if not claude_repo.exists():
        claude_repo.init()
    
    # Get or create current session
    session = claude_repo.get_or_create_current_session()
    
    # Create change record
    change = create_change_record(tool_data, session.id)
    
    if change is None:
        with open(debug_log, "a") as f:
            f.write("Failed to create change record, skipping\n")
        sys.exit(0)
    
    # Store the change
    claude_repo.add_change(change)
    
    print(f"Captured change: {change.id} in session: {session.id}")


if __name__ == "__main__":
    main()