"""
Demo script to test claude-git conversation tracking and thinking text extraction.

This script demonstrates how claude-git captures Claude's thinking process
and accumulates file changes during a session, creating logical commits with
rich context including thinking text and conversation history.
"""


class ConversationTracker:
    """Tracks conversation flow and thinking patterns for claude-git integration."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.conversation_history = []
        self.thinking_patterns = []

    def add_user_message(self, content: str):
        """Add a user message to the conversation history."""
        self.conversation_history.append(
            {"role": "user", "content": content, "timestamp": self._get_timestamp()}
        )

    def add_assistant_message(self, content: str, thinking: bool = False):
        """Add an assistant message, optionally marking it as thinking text."""
        message = {
            "role": "assistant",
            "content": content,
            "timestamp": self._get_timestamp(),
        }

        if thinking:
            message["thinking"] = True
            self.thinking_patterns.append(content)

        self.conversation_history.append(message)

    def get_thinking_summary(self) -> str:
        """Generate a summary of Claude's thinking process."""
        if not self.thinking_patterns:
            return "No thinking patterns captured"

        # Combine thinking patterns into a coherent narrative
        return "\n\n".join(self.thinking_patterns[:3])  # Limit to first 3 thoughts


def test_conversation_feature():
    """
    Test function to verify claude-git accumulation and thinking text extraction.

    ENHANCED SYSTEM: Now properly tracks tool use changes and extracts thinking!
    When I stop working, the hooks should:
    1. Extract my thinking process from the transcript
    2. Create ONE cumulative commit with all file changes
    3. Store the conversation (user message -> my response) in git notes
    4. Make git history meaningful and readable
    5. NO MORE cache file pollution - only tool use changes!
    """
    print("🧪 Testing enhanced cumulative commit system!")
    print("✅ This should create ONE intelligent commit containing:")
    print("   - Only files Claude edited with tools (no __pycache__)")
    print("   - Claude's actual thinking process as commit message")
    print("   - Complete conversation history in git notes")
    print("   - Rich context for future AI conflict resolution")
    print("   - Professional git workflow integration")

    # Simulate thinking process that should be captured
    thinking_demo = ConversationTracker("test-session-001")
    thinking_demo.add_user_message("test file changes and see if it works")
    thinking_demo.add_assistant_message(
        "I need to create multiple file changes to test if the hooks properly accumulate changes and extract thinking text from the transcript.",
        thinking=True,
    )

    return {
        "status": "testing_enhanced_system",
        "expected_files": ["demo_conversation_test.py", "test_cumulative_commits.py"],
        "thinking_captured": True,
        "conversation_tracked": True,
    }


if __name__ == "__main__":
    result = test_conversation_feature()
    print(f"Result: {result}")
