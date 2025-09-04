#!/usr/bin/env python3
"""
Unified hook script for Claude Code integration.

This script can be used as:
- PreToolUse hook: Detects when Claude starts working and initializes session tracking
- Stop hook: Creates logical commits with thinking text when Claude finishes working
- Generic tool hook: Accumulates changes during Claude's session

The script auto-detects the hook type based on the input data structure.
"""

from claude_git.hooks.git_native_handler import main

if __name__ == "__main__":
    main()
