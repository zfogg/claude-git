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
    file_path = Path(change_info["file_path"])
    
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
    if len(sys.argv) != 2:
        print("Usage: capture.py <hook_input_json>", file=sys.stderr)
        sys.exit(1)
    
    hook_input = sys.argv[1]
    hook_data = parse_hook_input(hook_input)
    
    # Check if this is a tool we care about
    tool_name = hook_data.get("tool", {}).get("name", "")
    if tool_name not in ["Edit", "Write", "MultiEdit"]:
        # Not a tool we track, exit silently
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
    change = create_change_record(hook_data.get("tool", {}), session.id)
    
    # Store the change
    claude_repo.add_change(change)
    
    print(f"Captured change: {change.id} in session: {session.id}")


if __name__ == "__main__":
    main()