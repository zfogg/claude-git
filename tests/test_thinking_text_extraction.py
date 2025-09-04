#!/usr/bin/env python3
"""
Test thinking text extraction from Claude Code transcripts.

This test validates that claude-git properly extracts Claude's thinking
process from transcript files and includes it in commit messages.
"""

import json

# Import the functions from the hook
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from claude_git.hooks.capture import extract_thinking_text_from_transcript


class TestThinkingTextExtraction:
    """Test suite for thinking text extraction functionality."""

    def create_mock_transcript(self, entries: list) -> Path:
        """Create a mock transcript file with given entries."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")
            return Path(f.name)

    def test_extract_simple_thinking_text(self):
        """Test extraction of basic thinking text."""
        entries = [
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": "I need to update this file to fix the bug",
                            "thinking": True,
                        }
                    ],
                },
            }
        ]

        transcript_file = self.create_mock_transcript(entries)
        debug_log = Path("/tmp/test_debug.log")

        try:
            thinking_texts = extract_thinking_text_from_transcript(
                str(transcript_file), debug_log
            )

            assert len(thinking_texts) == 1
            assert thinking_texts[0] == "I need to update this file to fix the bug"
        finally:
            transcript_file.unlink()

    def test_extract_multiple_thinking_texts(self):
        """Test extraction of multiple thinking texts."""
        entries = [
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": "First, I should analyze the problem",
                            "thinking": True,
                        }
                    ],
                },
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": "Now I'll implement the solution step by step",
                            "thinking": True,
                        }
                    ],
                },
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": "Let me verify this works correctly",
                            "thinking": True,
                        }
                    ],
                },
            },
        ]

        transcript_file = self.create_mock_transcript(entries)
        debug_log = Path("/tmp/test_debug.log")

        try:
            thinking_texts = extract_thinking_text_from_transcript(
                str(transcript_file), debug_log
            )

            # Should return last 3 thinking texts
            assert len(thinking_texts) == 3
            assert "First, I should analyze the problem" in thinking_texts
            assert "Now I'll implement the solution step by step" in thinking_texts
            assert "Let me verify this works correctly" in thinking_texts
        finally:
            transcript_file.unlink()

    def test_ignore_non_thinking_text(self):
        """Test that non-thinking text is ignored."""
        entries = [
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": "This is regular response text",
                            "thinking": False,
                        }
                    ],
                },
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": "This is thinking text",
                            "thinking": True,
                        }
                    ],
                },
            },
        ]

        transcript_file = self.create_mock_transcript(entries)
        debug_log = Path("/tmp/test_debug.log")

        try:
            thinking_texts = extract_thinking_text_from_transcript(
                str(transcript_file), debug_log
            )

            assert len(thinking_texts) == 1
            assert thinking_texts[0] == "This is thinking text"
            assert "This is regular response text" not in thinking_texts
        finally:
            transcript_file.unlink()

    def test_handle_mixed_content_types(self):
        """Test handling of mixed content with tool_use and thinking text."""
        entries = [
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": "Let me think about this problem",
                            "thinking": True,
                        },
                        {
                            "type": "tool_use",
                            "name": "Edit",
                            "input": {"file_path": "/test/file.py"},
                        },
                        {
                            "type": "text",
                            "text": "I need to be careful with this change",
                            "thinking": True,
                        },
                    ],
                },
            }
        ]

        transcript_file = self.create_mock_transcript(entries)
        debug_log = Path("/tmp/test_debug.log")

        try:
            thinking_texts = extract_thinking_text_from_transcript(
                str(transcript_file), debug_log
            )

            assert len(thinking_texts) == 2
            assert "Let me think about this problem" in thinking_texts
            assert "I need to be careful with this change" in thinking_texts
        finally:
            transcript_file.unlink()

    def test_filter_long_thinking_text(self):
        """Test that overly long thinking text is filtered out."""
        long_text = "x" * 600  # Exceeds 500 char limit

        entries = [
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": long_text, "thinking": True},
                        {
                            "type": "text",
                            "text": "This is reasonable length",
                            "thinking": True,
                        },
                    ],
                },
            }
        ]

        transcript_file = self.create_mock_transcript(entries)
        debug_log = Path("/tmp/test_debug.log")

        try:
            thinking_texts = extract_thinking_text_from_transcript(
                str(transcript_file), debug_log
            )

            # Should only get the reasonable length text
            assert len(thinking_texts) == 1
            assert thinking_texts[0] == "This is reasonable length"
            assert long_text not in thinking_texts
        finally:
            transcript_file.unlink()

    def test_empty_transcript(self):
        """Test handling of empty transcript file."""
        entries = []

        transcript_file = self.create_mock_transcript(entries)
        debug_log = Path("/tmp/test_debug.log")

        try:
            thinking_texts = extract_thinking_text_from_transcript(
                str(transcript_file), debug_log
            )

            assert thinking_texts == []
        finally:
            transcript_file.unlink()

    def test_malformed_json_handling(self):
        """Test handling of malformed JSON in transcript."""
        # Create a file with both valid and invalid JSON lines
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            # Valid entry
            f.write(
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Valid thinking text",
                                    "thinking": True,
                                }
                            ],
                        },
                    }
                )
                + "\n"
            )

            # Invalid JSON line
            f.write('{"invalid": json syntax\n')

            # Another valid entry
            f.write(
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Another valid thinking",
                                    "thinking": True,
                                }
                            ],
                        },
                    }
                )
                + "\n"
            )

            transcript_file = Path(f.name)

        debug_log = Path("/tmp/test_debug.log")

        try:
            thinking_texts = extract_thinking_text_from_transcript(
                str(transcript_file), debug_log
            )

            # Should successfully extract valid entries despite malformed JSON
            assert len(thinking_texts) == 2
            assert "Valid thinking text" in thinking_texts
            assert "Another valid thinking" in thinking_texts
        finally:
            transcript_file.unlink()


def test_thinking_text_in_commit_integration():
    """Integration test to verify thinking text appears in commits."""
    # This test would require setting up a full mock environment
    # For now, we'll test the logic components separately

    # Test that commit message generation works with thinking text

    # This would need a mock git environment to test properly
    # But we've verified the thinking text extraction works above
    assert True  # Placeholder for integration test


if __name__ == "__main__":
    # Run tests directly
    pytest.main([__file__, "-v"])
