"""
Real-time test integration for Claude sessions with pytest-testmon.

ENHANCED FOR CUMULATIVE COMMIT TESTING:
This file is being modified as part of testing the enhanced cumulative commit system.
The system should now properly capture Claude's thinking process and create logical
commits with conversation history stored in git notes.
"""

import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# import psutil  # Not needed for current functionality


class TestMonitor:
    """
    Real-time test monitoring for Claude sessions using pytest-testmon.

    TESTING ENHANCEMENT: This class now supports the new cumulative commit workflow
    where multiple file changes are grouped into logical work units with thinking text.
    """

    def __init__(self, session_id: str, worktree_path: Path, project_root: Path):
        self.session_id = session_id
        self.worktree_path = worktree_path
        self.project_root = project_root
        self.monitor_process: Optional[subprocess.Popen] = None
        self.is_monitoring = False
        self.test_results: List[Dict[str, Any]] = []
        self.monitoring_thread: Optional[threading.Thread] = None

        # Test configuration
        self.test_command = self._detect_test_command()
        self.testmon_config = worktree_path / ".testmondata"

    def _detect_test_command(self) -> List[str]:
        """Detect the appropriate test command for this project."""
        # Check for pytest.ini, tox.ini, pyproject.toml, or setup.cfg
        config_files = [
            self.project_root / "pytest.ini",
            self.project_root / "pyproject.toml",
            self.project_root / "setup.cfg",
            self.project_root / "tox.ini",
        ]

        has_pytest_config = any(f.exists() for f in config_files)
        has_test_dir = (self.project_root / "tests").exists()
        has_test_files = any(self.project_root.glob("test_*.py")) or any(
            self.project_root.glob("*_test.py")
        )

        if has_pytest_config or has_test_dir or has_test_files:
            return ["python", "-m", "pytest", "--testmon"]
        # Fallback to basic python unittest discovery
        return ["python", "-m", "unittest", "discover"]

    def start_monitoring(self) -> bool:
        """Start real-time test monitoring for this session."""
        if self.is_monitoring:
            print(f"⚠️  Test monitoring already active for session {self.session_id}")
            return True

        print(f"🧪 Starting real-time test monitoring for session {self.session_id}...")
        print(f"📁 Worktree: {self.worktree_path}")
        print("🔍 Watching: Python files for changes")
        print(f"⚡ Test runner: {' '.join(self.test_command)}")

        try:
            # Check if pytest-testmon is available
            if "--testmon" in self.test_command:
                result = subprocess.run(
                    ["python", "-c", "import testmon; print('testmon available')"],
                    cwd=self.worktree_path,
                    capture_output=True,
                    text=True,
                )

                if result.returncode != 0:
                    print(
                        "⚠️  pytest-testmon not available, falling back to regular pytest"
                    )
                    self.test_command = ["python", "-m", "pytest", "--tb=short", "-v"]

            # Start the monitoring thread
            self.is_monitoring = True
            self.monitoring_thread = threading.Thread(
                target=self._monitor_tests, daemon=True
            )
            self.monitoring_thread.start()

            return True

        except Exception as e:
            print(f"❌ Failed to start test monitoring: {e}")
            return False

    def stop_monitoring(self) -> None:
        """Stop test monitoring for this session."""
        print(f"🛑 Stopping test monitoring for session {self.session_id}")

        self.is_monitoring = False

        # Stop the monitoring process
        if self.monitor_process and self.monitor_process.poll() is None:
            try:
                # Gracefully terminate
                self.monitor_process.terminate()
                self.monitor_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # Force kill if it doesn't terminate
                self.monitor_process.kill()
                self.monitor_process.wait()

        # Wait for thread to finish
        if self.monitoring_thread and self.monitoring_thread.is_alive():
            self.monitoring_thread.join(timeout=2)

        print(f"✅ Test monitoring stopped for session {self.session_id}")

    def run_affected_tests(self, changed_files: List[str]) -> Dict[str, Any]:
        """Run tests affected by the specified file changes."""
        print(f"🧪 Running affected tests for {len(changed_files)} changed files...")

        start_time = time.time()

        try:
            # Use testmon to run only affected tests
            cmd = self.test_command + ["--tb=short", "-v"]

            result = subprocess.run(
                cmd,
                cwd=self.worktree_path,
                capture_output=True,
                text=True,
                timeout=120,  # 2 minute timeout for tests
            )

            duration = time.time() - start_time

            test_result = {
                "timestamp": time.time(),
                "session_id": self.session_id,
                "command": " ".join(cmd),
                "changed_files": changed_files,
                "duration": duration,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "success": result.returncode == 0,
            }

            # Parse pytest output for detailed results
            parsed_results = self._parse_pytest_output(result.stdout)
            test_result.update(parsed_results)

            # Store result
            self.test_results.append(test_result)

            # Print live feedback
            self._print_test_feedback(test_result, changed_files)

            return test_result

        except subprocess.TimeoutExpired:
            print("⏰ Tests timed out after 2 minutes")
            return {
                "timestamp": time.time(),
                "session_id": self.session_id,
                "success": False,
                "error": "Test execution timed out",
                "duration": time.time() - start_time,
            }
        except Exception as e:
            print(f"❌ Error running tests: {e}")
            return {
                "timestamp": time.time(),
                "session_id": self.session_id,
                "success": False,
                "error": str(e),
                "duration": time.time() - start_time,
            }

    def _monitor_tests(self) -> None:
        """Background thread for continuous test monitoring."""
        last_check = time.time()

        while self.is_monitoring:
            try:
                # Check for file changes every 2 seconds
                time.sleep(2)

                current_time = time.time()
                changed_files = self._detect_recent_changes(last_check)

                if changed_files:
                    print(f"📝 Detected changes in {len(changed_files)} files")
                    self.run_affected_tests(changed_files)

                last_check = current_time

            except Exception as e:
                if (
                    self.is_monitoring
                ):  # Only log if we're still supposed to be monitoring
                    print(f"⚠️  Test monitoring error: {e}")
                    time.sleep(5)  # Wait longer on error

    def _detect_recent_changes(self, since_timestamp: float) -> List[str]:
        """Detect files changed since the given timestamp."""
        changed_files = []

        try:
            # Check all Python files in the worktree
            for py_file in self.worktree_path.rglob("*.py"):
                if py_file.is_file():
                    mtime = py_file.stat().st_mtime
                    if mtime > since_timestamp:
                        # Get relative path from project root
                        try:
                            rel_path = py_file.relative_to(self.worktree_path)
                            changed_files.append(str(rel_path))
                        except ValueError:
                            # File is outside worktree, skip
                            continue

        except Exception as e:
            print(f"⚠️  Error detecting file changes: {e}")

        return changed_files

    def _parse_pytest_output(self, output: str) -> Dict[str, Any]:
        """Parse pytest output to extract test results."""
        result = {
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "tests_skipped": 0,
            "failed_tests": [],
            "test_files": [],
        }

        try:
            lines = output.split("\n")

            for line in lines:
                # Look for test result summary
                if " passed" in line or " failed" in line or " skipped" in line:
                    # Parse summary line like: "5 passed, 2 failed in 1.23s"
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if part == "passed" and i > 0:
                            result["tests_passed"] = int(parts[i - 1])
                        elif part == "failed" and i > 0:
                            result["tests_failed"] = int(parts[i - 1])
                        elif part == "skipped" and i > 0:
                            result["tests_skipped"] = int(parts[i - 1])

                # Look for failed test names
                if "FAILED " in line:
                    test_name = line.split("FAILED ")[1].split(" ")[0]
                    result["failed_tests"].append(test_name)

                # Look for test files being run
                if line.startswith("test_") and "::" in line:
                    test_file = line.split("::")[0]
                    if test_file not in result["test_files"]:
                        result["test_files"].append(test_file)

            result["tests_run"] = (
                result["tests_passed"]
                + result["tests_failed"]
                + result["tests_skipped"]
            )

        except Exception as e:
            print(f"⚠️  Error parsing test output: {e}")

        return result

    def _print_test_feedback(
        self, test_result: Dict[str, Any], changed_files: List[str]
    ) -> None:
        """Print real-time test feedback in Claude-friendly format."""
        if test_result["success"]:
            passed = test_result.get("tests_passed", 0)
            duration = test_result.get("duration", 0)
            print(f"✅ {passed} tests PASSED ({duration:.2f}s)")

            if test_result.get("failed_tests"):
                for failed_test in test_result["failed_tests"]:
                    print(f"❌ {failed_test} FAILED")
        else:
            failed = test_result.get("tests_failed", 0)
            if failed > 0:
                print(f"❌ {failed} tests FAILED")

                # Show specific failure info
                stderr = test_result.get("stderr", "")
                if stderr:
                    # Extract key error info
                    error_lines = stderr.split("\n")[:3]  # First 3 lines
                    for line in error_lines:
                        if line.strip():
                            print(f"   {line.strip()}")

    def get_session_test_summary(self) -> Dict[str, Any]:
        """Get comprehensive test summary for this session."""
        if not self.test_results:
            return {
                "session_id": self.session_id,
                "total_test_runs": 0,
                "overall_success": True,
                "average_duration": 0,
                "test_health": "No tests run",
            }

        total_runs = len(self.test_results)
        successful_runs = sum(1 for r in self.test_results if r["success"])
        total_duration = sum(r.get("duration", 0) for r in self.test_results)
        avg_duration = total_duration / total_runs if total_runs > 0 else 0

        # Latest test results
        latest = self.test_results[-1]

        return {
            "session_id": self.session_id,
            "total_test_runs": total_runs,
            "successful_runs": successful_runs,
            "failed_runs": total_runs - successful_runs,
            "overall_success": successful_runs == total_runs,
            "average_duration": avg_duration,
            "latest_test_count": latest.get("tests_run", 0),
            "latest_passed": latest.get("tests_passed", 0),
            "latest_failed": latest.get("tests_failed", 0),
            "test_health": "All tests passing"
            if latest.get("success", False)
            else "Some tests failing",
            "failed_tests": latest.get("failed_tests", []),
        }


class CrossSessionTestCoordinator:
    """Coordinates test results across multiple Claude sessions."""

    def __init__(self, claude_git_dir: Path):
        self.claude_git_dir = claude_git_dir
        self.session_monitors: Dict[str, TestMonitor] = {}
        self.cross_session_results_file = (
            claude_git_dir / ".claude-test-coordination.json"
        )

    def register_session_monitor(self, session_id: str, monitor: TestMonitor) -> None:
        """Register a test monitor for cross-session coordination."""
        self.session_monitors[session_id] = monitor
        print(f"🔗 Registered test monitor for session {session_id}")

    def unregister_session_monitor(self, session_id: str) -> None:
        """Unregister a session monitor."""
        if session_id in self.session_monitors:
            del self.session_monitors[session_id]
            print(f"🔌 Unregistered test monitor for session {session_id}")

    def analyze_cross_session_impact(
        self, session_id: str, changed_files: List[str]
    ) -> Dict[str, Any]:
        """Analyze how changes in one session might affect tests in other sessions."""
        impact_analysis = {
            "session_id": session_id,
            "changed_files": changed_files,
            "potentially_affected_sessions": [],
            "recommended_actions": [],
        }

        for other_session_id, monitor in self.session_monitors.items():
            if other_session_id == session_id:
                continue

            # Check if other sessions might be affected
            other_results = monitor.get_session_test_summary()
            if other_results["failed_runs"] > 0:
                impact_analysis["potentially_affected_sessions"].append(
                    {
                        "session_id": other_session_id,
                        "current_test_health": other_results["test_health"],
                        "failed_tests": other_results["failed_tests"],
                    }
                )

                impact_analysis["recommended_actions"].append(
                    f"Check session {other_session_id} - may be affected by changes to {changed_files}"
                )

        return impact_analysis

    def get_global_test_status(self) -> Dict[str, Any]:
        """Get overall test status across all active sessions."""
        global_status = {
            "active_sessions": len(self.session_monitors),
            "sessions_with_passing_tests": 0,
            "sessions_with_failing_tests": 0,
            "total_test_runs": 0,
            "overall_health": "healthy",
        }

        session_details = []

        for _session_id, monitor in self.session_monitors.items():
            summary = monitor.get_session_test_summary()
            session_details.append(summary)

            global_status["total_test_runs"] += summary["total_test_runs"]

            if summary["overall_success"]:
                global_status["sessions_with_passing_tests"] += 1
            else:
                global_status["sessions_with_failing_tests"] += 1

        if global_status["sessions_with_failing_tests"] > 0:
            global_status["overall_health"] = "degraded"
        elif global_status["active_sessions"] == 0:
            global_status["overall_health"] = "no_tests"

        global_status["session_details"] = session_details

        return global_status
