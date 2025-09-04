#!/usr/bin/env python3
"""Setup Claude Code hooks for claude-git session management."""

import json
from pathlib import Path
from typing import Any, Dict


def get_claude_config_dir() -> Path:
    """Get Claude configuration directory."""
    return Path.home() / ".claude"


def get_project_claude_dir(project_root: Path) -> Path:
    """Get project-specific Claude directory."""
    return project_root / ".claude"


def create_hook_config(project_root: Path) -> Dict[str, Any]:
    """Create Claude Code hook configuration."""
    # Get paths to our hook scripts
    hooks_dir = Path(__file__).parent.parent / "hooks"

    session_start_script = hooks_dir / "session_start.py"
    session_end_script = hooks_dir / "session_end.py"
    post_tool_script = hooks_dir / "capture.py"

    # Make sure scripts are executable
    session_start_script.chmod(0o755)
    session_end_script.chmod(0o755)
    post_tool_script.chmod(0o755)

    return {
        "hooks": {
            "SessionStart": [
                {"hooks": [{"type": "command", "command": str(session_start_script)}]}
            ],
            "SessionEnd": [
                {"hooks": [{"type": "command", "command": str(session_end_script)}]}
            ],
            "PostToolUse": [
                {"hooks": [{"type": "command", "command": str(post_tool_script)}]}
            ],
        }
    }


def setup_global_hooks() -> bool:
    """Set up hooks in global Claude configuration."""
    try:
        claude_dir = get_claude_config_dir()
        claude_dir.mkdir(exist_ok=True)

        config_file = claude_dir / "claude_desktop_config.json"

        # Read existing config if it exists
        existing_config = {}
        if config_file.exists():
            with open(config_file) as f:
                existing_config = json.load(f)

        # Create hook config for current project
        project_root = Path.cwd()
        hook_config = create_hook_config(project_root)

        # Merge with existing config
        existing_config.update(hook_config)

        # Write updated config
        with open(config_file, "w") as f:
            json.dump(existing_config, f, indent=2)

        print(f"✅ Global Claude Code hooks configured in {config_file}")
        return True

    except Exception as e:
        print(f"❌ Error setting up global hooks: {e}")
        return False


def setup_project_hooks(project_root: Path) -> bool:
    """Set up hooks in project-specific Claude configuration."""
    try:
        claude_dir = get_project_claude_dir(project_root)
        claude_dir.mkdir(exist_ok=True)

        config_file = claude_dir / "claude_desktop_config.json"

        # Create hook config
        hook_config = create_hook_config(project_root)

        # Write config
        with open(config_file, "w") as f:
            json.dump(hook_config, f, indent=2)

        print(f"✅ Project Claude Code hooks configured in {config_file}")
        return True

    except Exception as e:
        print(f"❌ Error setting up project hooks: {e}")
        return False


def verify_hook_scripts() -> bool:
    """Verify that hook scripts exist and are executable."""
    hooks_dir = Path(__file__).parent.parent / "hooks"

    required_scripts = ["session_start.py", "session_end.py", "capture.py"]

    for script_name in required_scripts:
        script_path = hooks_dir / script_name
        if not script_path.exists():
            print(f"❌ Missing hook script: {script_path}")
            return False

        if not script_path.is_file():
            print(f"❌ Hook script is not a file: {script_path}")
            return False

        # Make executable
        script_path.chmod(0o755)

    print("✅ All hook scripts verified and made executable")
    return True


def main():
    """Main setup function."""
    print("🔧 Setting up Claude Code hooks for claude-git...")

    project_root = Path.cwd()

    # Verify git repository
    if not (project_root / ".git").exists():
        print("❌ Not a git repository. Run this command from your project root.")
        return False

    # Verify claude-git is initialized
    if not (project_root / ".claude-git").exists():
        print("❌ Claude-git not initialized. Run 'claude-git init' first.")
        return False

    # Verify hook scripts exist
    if not verify_hook_scripts():
        return False

    # Set up hooks (try project-specific first, fall back to global)
    success = False

    print("\n📁 Setting up project-specific hooks...")
    if setup_project_hooks(project_root):
        success = True
    else:
        print("⚠️  Failed to set up project hooks, trying global...")
        if setup_global_hooks():
            success = True

    if success:
        print("\n🎯 Claude Code hooks configured successfully!")
        print("\nNext steps:")
        print("1. Restart Claude Code to load the new hooks")
        print("2. Start coding - claude-git will now:")
        print("   • Start tracking when Claude begins working (SessionStart)")
        print("   • Accumulate all file changes during the session")
        print(
            "   • Create logical commits with thinking text when Claude stops (SessionEnd)"
        )
        print("\n💡 Tip: Check ~/.claude/claude-git-debug.log for hook activity")
        return True
    print("\n❌ Failed to configure Claude Code hooks")
    return False


if __name__ == "__main__":
    main()
