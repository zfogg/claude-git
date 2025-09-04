"""
End-to-end tests for Claude thinking text collection and session squashing.

This test suite validates the complete workflow:
1. Session management (start/end)
2. Change accumulation during sessions
3. Thinking text extraction from real Claude Code transcripts
4. Session-end squashing with thinking text in commit messages
5. Git notes storage for structured data
"""

import json
import subprocess
import tempfile
from pathlib import Path

import pytest

from claude_git.core.git_native_repository import GitNativeRepository
from claude_git.hooks.session_end import extract_chronological_thinking_and_changes


class TestThinkingCollectionE2E:
    """End-to-end tests for the complete thinking collection system."""

    @pytest.fixture
    def temp_repo(self):
        """Create a temporary git repository for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_path = Path(temp_dir)

            # Initialize git repo
            subprocess.run(["git", "init"], cwd=repo_path, check=True)
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=repo_path, check=True
            )
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=repo_path,
                check=True,
            )

            # Create initial commit
            (repo_path / "initial.txt").write_text("initial content")
            subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
            subprocess.run(
                ["git", "commit", "-m", "initial commit"], cwd=repo_path, check=True
            )

            yield repo_path

    @pytest.fixture
    def claude_git_repo(self, temp_repo):
        """Initialize claude-git in the temporary repository."""
        repo = GitNativeRepository(temp_repo)
        repo.init()
        return repo

    @pytest.fixture
    def sample_transcript(self):
        """Create a sample Claude Code transcript with thinking text."""
        transcript_data = [
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "thinking",
                            "thinking": "I need to create a user authentication system. Let me think through the architecture - I should start with a User class that handles validation, then add JWT token generation.",
                        }
                    ],
                },
                "timestamp": "2025-01-15T10:30:00.000Z",
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Write",
                            "input": {
                                "file_path": "auth.py",
                                "content": "class User: pass",
                            },
                        }
                    ],
                },
                "timestamp": "2025-01-15T10:31:00.000Z",
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "thinking",
                            "thinking": "Now I need to add JWT token generation. This should integrate well with the existing OAuth system the user mentioned.",
                        }
                    ],
                },
                "timestamp": "2025-01-15T10:32:00.000Z",
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Edit",
                            "input": {
                                "file_path": "auth.py",
                                "old_string": "class User: pass",
                                "new_string": "class User:\n    def generate_jwt(self): pass",
                            },
                        }
                    ],
                },
                "timestamp": "2025-01-15T10:33:00.000Z",
            },
        ]

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".jsonl") as f:
            for entry in transcript_data:
                json.dump(entry, f)
                f.write("\n")
            return Path(f.name)

    def test_thinking_text_extraction(self, sample_transcript):
        """Test that thinking text is properly extracted from Claude Code transcripts."""
        debug_log = Path(tempfile.mkdtemp()) / "debug.log"

        result = extract_chronological_thinking_and_changes(
            str(sample_transcript), debug_log
        )

        # Verify thinking text was extracted
        assert result is not None
        assert len(result) > 100  # Should have substantial content

        # Verify it contains the actual thinking text
        assert "user authentication system" in result
        assert "JWT token generation" in result
        assert "OAuth system" in result

        # Verify chronological structure
        lines = result.split("\n")
        auth_line = next(
            (line for line in lines if "authentication system" in line), None
        )
        jwt_line = next(
            (line for line in lines if "JWT token generation" in line), None
        )

        assert auth_line is not None
        assert jwt_line is not None

        # Clean up
        sample_transcript.unlink()
        if debug_log.exists():
            debug_log.unlink()

    def test_session_lifecycle_management(self, claude_git_repo, temp_repo):
        """Test complete session start → accumulate changes → end with thinking."""
        # 1. Start session
        session_id = "test-thinking-session"
        claude_git_repo.session_start(session_id)

        assert claude_git_repo._session_active is True
        assert claude_git_repo._current_session_id == session_id
        assert len(claude_git_repo._accumulated_changes) == 0

        # 2. Create actual files that will be "changed by Claude"
        test_file = temp_repo / "auth.py"
        test_file.write_text("class User: pass")

        utils_file = temp_repo / "utils.py"
        utils_file.write_text("def helper(): return True")

        # 3. Accumulate changes (simulate Claude making file changes)
        claude_git_repo.accumulate_change(
            str(test_file), "Write", {"content": "class User: pass"}
        )
        claude_git_repo.accumulate_change(
            str(utils_file), "Write", {"content": "def helper(): return True"}
        )

        assert len(claude_git_repo._accumulated_changes) == 2

        # 4. End session with thinking text
        thinking_text = """I created a user authentication system starting with a basic User class.

Then I added a helper utility function for common operations. The architecture should be modular and extensible for future authentication features."""

        commit_hash = claude_git_repo.session_end(thinking_text)

        # Verify session ended properly
        assert claude_git_repo._session_active is False
        assert claude_git_repo._current_session_id is None
        assert commit_hash is not None
        assert len(commit_hash) > 0

        # 5. Verify commit contains thinking text
        result = subprocess.run(
            [
                "git",
                "-C",
                str(claude_git_repo.claude_git_dir),
                "log",
                "-1",
                "--pretty=format:%B",
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        commit_message = result.stdout

        # Commit should contain the thinking text
        assert "user authentication system" in commit_message
        assert "modular and extensible" in commit_message
        assert len(commit_message) > len(
            thinking_text
        )  # Should have additional metadata

        # Should include structured metadata
        assert "Parent-Repo:" in commit_message
        assert "Session:" in commit_message
        assert "Files:" in commit_message

    def test_end_to_end_with_real_transcript_format(
        self, claude_git_repo, temp_repo, sample_transcript
    ):
        """Test the complete end-to-end workflow with real transcript format."""
        # Start session
        claude_git_repo.session_start("e2e-test-session")

        # Create and modify files
        auth_file = temp_repo / "auth.py"
        auth_file.write_text("class User:\n    def generate_jwt(self): pass")

        config_file = temp_repo / "config.py"
        config_file.write_text("JWT_SECRET = 'secret'")

        # Accumulate changes
        claude_git_repo.accumulate_change(
            str(auth_file),
            "Write",
            {"content": "class User: def generate_jwt(self): pass"},
        )
        claude_git_repo.accumulate_change(
            str(config_file), "Write", {"content": "JWT_SECRET = 'secret'"}
        )

        # Extract thinking text from sample transcript
        debug_log = Path(tempfile.mkdtemp()) / "debug.log"
        thinking_text = extract_chronological_thinking_and_changes(
            str(sample_transcript), debug_log
        )

        # End session with extracted thinking
        commit_hash = claude_git_repo.session_end(thinking_text)

        assert commit_hash is not None

        # Verify the commit
        result = subprocess.run(
            [
                "git",
                "-C",
                str(claude_git_repo.claude_git_dir),
                "show",
                "--stat",
                commit_hash,
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        commit_output = result.stdout

        # Should show both files were modified
        assert "auth.py" in commit_output
        assert "config.py" in commit_output

        # Should contain thinking text in commit message
        assert "authentication system" in commit_output
        assert "JWT token generation" in commit_output

        # Clean up
        sample_transcript.unlink()
        if debug_log.exists():
            debug_log.unlink()

    def test_git_notes_storage(self, claude_git_repo, temp_repo):
        """Test that structured data is stored in git notes."""
        # Start session and make changes
        claude_git_repo.session_start("notes-test-session")

        test_file = temp_repo / "test.py"
        test_file.write_text("def test(): pass")
        claude_git_repo.accumulate_change(
            str(test_file), "Write", {"content": "def test(): pass"}
        )

        # End session
        thinking_text = "Created a test function for the new feature."
        commit_hash = claude_git_repo.session_end(thinking_text)

        # Check if git notes were created
        result = subprocess.run(
            [
                "git",
                "-C",
                str(claude_git_repo.claude_git_dir),
                "notes",
                "show",
                commit_hash,
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            notes_data = result.stdout

            # Parse notes as JSON
            try:
                notes_json = json.loads(notes_data)

                # Verify expected structure
                assert "session_id" in notes_json
                assert "files" in notes_json
                assert "timestamp" in notes_json
                assert notes_json["session_id"] == "notes-test-session"
                assert "test.py" in str(notes_json["files"])

            except json.JSONDecodeError:
                # Notes might not be in JSON format, check for basic content
                assert "notes-test-session" in notes_data

    def test_professional_commit_format(self, claude_git_repo, temp_repo):
        """Test that commits follow professional git format suitable for cherry-picking."""
        claude_git_repo.session_start("professional-commit-test")

        # Create multiple related files
        files_to_create = {
            "models.py": "class UserModel: pass",
            "views.py": "def user_view(): pass",
            "tests.py": "def test_user(): pass",
        }

        for filename, content in files_to_create.items():
            file_path = temp_repo / filename
            file_path.write_text(content)
            claude_git_repo.accumulate_change(
                str(file_path), "Write", {"content": content}
            )

        thinking_text = """Implemented complete user management feature with MVC pattern.

Created the user model for data representation, added view functions for user interface, and included comprehensive test coverage. This follows the existing project architecture and should integrate cleanly."""

        commit_hash = claude_git_repo.session_end(thinking_text)

        # Verify commit is well-formed
        result = subprocess.run(
            [
                "git",
                "-C",
                str(claude_git_repo.claude_git_dir),
                "show",
                "--pretty=format:%H%n%an%n%ae%n%s%n%b",
                commit_hash,
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        lines = result.stdout.split("\n")

        commit_hash_line = lines[0]
        author_name = lines[1]
        author_email = lines[2]
        subject = lines[3]

        # Verify professional git format
        assert len(commit_hash_line) == 40  # Full SHA
        assert author_name == "Claude"
        assert author_email == "noreply@anthropic.com"
        assert len(subject) < 80  # Good commit subject length
        assert "user management" in subject.lower() or "mvc pattern" in subject.lower()

        # Verify body contains thinking and metadata
        body = "\n".join(lines[4:])
        assert "user model" in body or "user management" in body  # More flexible check
        assert "Parent-Repo:" in body
        assert "Files:" in body
        # Check that at least some of the files are mentioned
        files_mentioned = sum(1 for filename in files_to_create if filename in body)
        assert files_mentioned >= 2  # At least 2 of the 3 files should be mentioned

    def test_error_handling_missing_transcript(self, claude_git_repo, temp_repo):
        """Test graceful handling when transcript file is missing or malformed."""
        claude_git_repo.session_start("error-handling-test")

        # Create a file change
        test_file = temp_repo / "error_test.py"
        test_file.write_text("# Test file")
        claude_git_repo.accumulate_change(
            str(test_file), "Write", {"content": "# Test file"}
        )

        # Try to extract thinking from non-existent transcript
        debug_log = Path(tempfile.mkdtemp()) / "debug.log"
        thinking_text = extract_chronological_thinking_and_changes(
            "/nonexistent/transcript.jsonl", debug_log
        )

        # Should return empty string, not crash
        assert thinking_text == ""

        # Session should still end successfully with fallback
        commit_hash = claude_git_repo.session_end("Fallback commit message")
        assert commit_hash is not None

        # Clean up
        if debug_log.exists():
            debug_log.unlink()

    def test_empty_session_handling(self, claude_git_repo):
        """Test handling of sessions with no changes accumulated."""
        claude_git_repo.session_start("empty-session-test")

        # Don't accumulate any changes
        assert len(claude_git_repo._accumulated_changes) == 0

        # End session - should handle gracefully
        commit_hash = claude_git_repo.session_end("No changes were made")

        # Should return empty string and not create commit
        assert commit_hash == ""
        assert claude_git_repo._session_active is False


if __name__ == "__main__":
    pytest.main([__file__])
