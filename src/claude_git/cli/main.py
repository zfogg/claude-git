"""Main CLI interface for Claude Git."""

# Test comment for testmon
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import click
import git as gitpython
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from claude_git.core.git_native_repository import GitNativeRepository
from claude_git.core.repository import ClaudeGitRepository

console = Console()


def run_claude_git_command(
    claude_git_dir: Path, git_args: List[str]
) -> subprocess.CompletedProcess:
    """Helper function to run git commands in the .claude-git directory."""
    cmd = ["git", "-C", str(claude_git_dir)] + git_args
    return subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603


def get_git_native_repo_or_exit(project_root: Path) -> GitNativeRepository:
    """Get GitNativeRepository instance or exit with error message."""
    git_native_repo = GitNativeRepository(project_root)
    if not git_native_repo.exists():
        console.print(
            "[red]Claude Git not initialized. Run 'claude-git init' first.[/red]"
        )
        raise click.Abort()
    return git_native_repo


@click.group()
@click.version_option()
def main():
    """Claude Git - Parallel version control for AI changes."""


@main.command()
@click.option(
    "--project-path",
    type=click.Path(exists=True),
    default=".",
    help="Path to project directory",
)
def init(project_path: str):
    """Initialize Claude Git in a project."""
    project_root = Path(project_path).resolve()

    if not (project_root / ".git").exists():
        console.print("[red]Error: Not a git repository[/red]")
        raise click.Abort()

    # Use git-native dual-repository architecture (now the default)
    git_native_repo = GitNativeRepository(project_root)

    try:
        git_native_repo.init()
        console.print(f"[green]✅ Initialized Claude Git in {project_root}[/green]")
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise click.Abort() from e


@main.command()
def status():
    """Show Claude Git status."""
    project_root = _find_project_root()
    if not project_root:
        return

    # Try git-native architecture first
    git_native_repo = GitNativeRepository(project_root)
    if git_native_repo.exists():
        # Show git-native status
        console.print(f"[bold]Project:[/bold] {project_root}")
        console.print("[bold]Architecture:[/bold] Git-native")

        session_active = (
            git_native_repo._session_active
            if hasattr(git_native_repo, "_session_active")
            else False
        )
        console.print(
            f"[bold]Active session:[/bold] {'Yes' if session_active else 'No'}"
        )

        # Show accumulated changes
        if hasattr(git_native_repo, "_accumulated_changes"):
            console.print(
                f"[bold]Accumulated changes:[/bold] "
                f"{len(git_native_repo._accumulated_changes)}"
            )

        # Show recent commits
        try:
            import subprocess

            result = subprocess.run(  # noqa: S603, S607
                [
                    "git",
                    "-C",
                    str(git_native_repo.claude_git_dir),
                    "log",
                    "--oneline",
                    "-5",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                console.print("[bold]Recent commits:[/bold]")
                for line in result.stdout.strip().split("\n"):
                    console.print(f"  {line}")
        except Exception:
            pass
        return

    # Fall back to legacy architecture
    claude_repo = ClaudeGitRepository(project_root)
    if not claude_repo.exists():
        console.print(
            "[red]Claude Git not initialized. Run 'claude-git init' first.[/red]"
        )
        return

    sessions = claude_repo.list_sessions()
    active_sessions = [s for s in sessions if s.is_active]

    console.print(f"[bold]Project:[/bold] {project_root}")
    console.print("[bold]Architecture:[/bold] Legacy")
    console.print(f"[bold]Total sessions:[/bold] {len(sessions)}")
    console.print(f"[bold]Active sessions:[/bold] {len(active_sessions)}")

    if active_sessions:
        for session in active_sessions[:3]:  # Show up to 3 active sessions
            commits = claude_repo.get_commits_for_session(session.id)
            console.print(f"  • {session.branch_name} ({len(commits)} commits)")


@main.command()
@click.option("--limit", default=10, help="Number of commits to show")
@click.option("--oneline", is_flag=True, help="Show compact one-line format")
def log(limit: int, oneline: bool):
    """Show Claude's recent commits."""
    project_root = _find_project_root()
    if not project_root:
        return

    # Try git-native architecture first
    git_native_repo = GitNativeRepository(project_root)
    if git_native_repo.exists():
        try:
            git_args = [
                "git",
                "-C",
                str(git_native_repo.claude_git_dir),
                "log",
                f"--max-count={limit}",
            ]
            if oneline:
                git_args.append("--oneline")

            # Use git directly for log output with pager
            import subprocess

            subprocess.run(git_args, check=True)  # noqa: S603
            return
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            return

    # Fall back to legacy architecture
    claude_repo = ClaudeGitRepository(project_root)
    if not claude_repo.exists():
        console.print(
            "[red]Claude Git not initialized. Run 'claude-git init' first.[/red]"
        )
        return

    try:
        args = ["log", f"--max-count={limit}"]
        if oneline:
            args.append("--oneline")

        # Use pager-aware command for log output
        claude_repo.run_git_command_with_pager(args)
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")


@main.command(context_settings={"ignore_unknown_options": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.option("--limit", default=10, help="Number of recent changes to analyze")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed diff output")
@click.option("--parent-hash", help="Filter changes by parent repository hash")
@click.option("--no-index", is_flag=True, help="Compare arbitrary paths")
@click.option("--tool", "-t", help="Use specific diff tool (overrides git config)")
@click.option("--no-pager", is_flag=True, help="Don't pipe output through pager")
def diff(
    args,
    limit: int,
    verbose: bool,
    parent_hash: Optional[str],
    no_index: bool,
    tool: Optional[str],
    no_pager: bool,
):
    """Show meaningful diff of Claude's changes vs current file state.

    Supports git-style arguments:
      claude-git diff                                    # Show recent changes
      claude-git diff <commit>                           # Changes from commit
      claude-git diff <commit>...<commit>                # Show changes between commits
      claude-git diff <commit>...<commit> <path>         # Changes for path
      claude-git diff HEAD~1                             # Show changes from HEAD~1
      claude-git diff HEAD~1 src/                        # Changes in src/
      claude-git diff -- path/to/file                    # Limit to specific paths
      claude-git diff --parent-hash abc123               # Filter by parent repo hash
      claude-git diff HEAD~2...HEAD src/ tests/          # Range with multiple paths
    """
    project_root = _find_project_root()
    if not project_root:
        return

    # Try git-native architecture first
    git_native_repo = GitNativeRepository(project_root)
    if git_native_repo.exists():
        try:
            # Handle git-native diff with proper argument processing
            if parent_hash:
                _handle_git_native_parent_hash_diff(
                    git_native_repo, parent_hash, args, no_pager
                )
                return

            # For standard git-native diff, delegate to git with proper args
            import subprocess

            # Build git command with proper argument order
            if no_pager:
                diff_args = [
                    "git",
                    "--no-pager",
                    "-C",
                    str(git_native_repo.claude_git_dir),
                    "diff",
                ]
            else:
                diff_args = ["git", "-C", str(git_native_repo.claude_git_dir), "diff"]

            # Process arguments to handle git-style syntax
            processed_args = _process_git_diff_args(list(args))
            diff_args.extend(processed_args)

            # Execute git diff
            result = subprocess.run(  # noqa: S603
                diff_args, capture_output=True, text=True
            )

            if result.returncode != 0:
                console.print(f"[red]Git diff error: {result.stderr}[/red]")
                return

            # Output the diff
            if result.stdout:
                if no_pager:
                    print(result.stdout)
                else:
                    _pipe_to_pager(result.stdout)

            return
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            return

    # Fall back to legacy architecture
    claude_repo = ClaudeGitRepository(project_root)
    if not claude_repo.exists():
        console.print(
            "[red]Claude Git not initialized. Run 'claude-git init' first.[/red]"
        )
        return

    try:
        # Parse git-style arguments
        parsed_args = _parse_diff_args(args)

        # Handle different diff modes
        if no_index:
            _handle_no_index_diff(claude_repo, parsed_args, verbose, tool, no_pager)
            return

        if parsed_args.get("commit_range"):
            _handle_commit_range_diff(
                claude_repo, parsed_args, parent_hash, verbose, tool, no_pager
            )
            return

        if parsed_args.get("single_commit"):
            _handle_single_commit_diff(
                claude_repo, parsed_args, parent_hash, verbose, tool, no_pager
            )
            return

        # Default behavior - show recent changes like git diff
        diff_results = claude_repo.get_meaningful_diff(
            limit, parent_hash=parent_hash, paths=parsed_args.get("paths")
        )

        if not diff_results["changes_analyzed"]:
            return  # No output if no changes, like git diff

        # Collect diff output for paging
        diff_output = ""
        for change in diff_results["changes_analyzed"]:
            diff_output += _get_git_style_diff_text(change, tool) + "\n"

        # Show output with paging if needed
        if not no_pager:
            _pipe_to_pager(diff_output)
        else:
            print(diff_output)

    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")


@main.command()
def sessions():
    """List all Claude sessions."""
    project_root = _find_project_root()
    if not project_root:
        return

    claude_repo = ClaudeGitRepository(project_root)
    if not claude_repo.exists():
        console.print(
            "[red]Claude Git not initialized. Run 'claude-git init' first.[/red]"
        )
        return

    sessions = claude_repo.list_sessions()

    if not sessions:
        console.print("[yellow]No sessions found[/yellow]")
        return

    table = Table(title="Claude Sessions")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Branch", style="green")
    table.add_column("Start Time", style="magenta")
    table.add_column("Duration", style="blue")
    table.add_column("Changes", style="yellow")
    table.add_column("Status", style="red")

    for session in sessions:
        session_id_short = session.id[:8]
        branch_name = session.branch_name
        start_time = session.start_time.strftime("%Y-%m-%d %H:%M")

        if session.is_active:
            duration = "Active"
            status = "🟢 Active"
        else:
            duration_sec = session.duration
            duration = f"{duration_sec / 60:.0f}m" if duration_sec else "Unknown"
            status = "⚫ Ended"

        # Get change count from session's tracked commit IDs
        change_count = str(len(session.change_ids))

        table.add_row(
            session_id_short, branch_name, start_time, duration, change_count, status
        )

    console.print(table)


@main.command(context_settings={"ignore_unknown_options": True})
@click.argument("git_args", nargs=-1, type=click.UNPROCESSED)
def git(git_args):
    """Run git commands on the Claude repository."""
    project_root = _find_project_root()
    if not project_root:
        return

    claude_repo = ClaudeGitRepository(project_root)
    if not claude_repo.exists():
        console.print(
            "[red]Claude Git not initialized. Run 'claude-git init' first.[/red]"
        )
        return

    try:
        # Convert git_args tuple to list
        args = list(git_args)

        # Commands that should use pager
        pager_commands = {"log", "diff", "show", "blame", "reflog"}

        if args and args[0] in pager_commands:
            # Use pager-aware command for output that benefits from paging
            claude_repo.run_git_command_with_pager(args)
        else:
            # Use regular command for simple output
            result = claude_repo.run_git_command(args)
            if result:
                console.print(result)
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")


@main.command()
@click.argument("commit_hash", required=False)
def show(commit_hash: Optional[str]):
    """Show detailed information about a commit."""
    project_root = _find_project_root()
    if not project_root:
        return

    claude_repo = ClaudeGitRepository(project_root)
    if not claude_repo.exists():
        console.print(
            "[red]Claude Git not initialized. Run 'claude-git init' first.[/red]"
        )
        return

    try:
        # Use git show command with pager
        args = ["show"]
        if commit_hash:
            args.append(commit_hash)

        # Use pager-aware command for show output
        claude_repo.run_git_command_with_pager(args)

        # Also show parent repo hash if available
        if commit_hash:
            try:
                commit = claude_repo.repo.commit(commit_hash)
                json_files = [
                    f for f in commit.tree.traverse() if f.name.endswith(".json")
                ]
                if json_files:
                    import json

                    change_data = json.loads(
                        json_files[0].data_stream.read().decode("utf-8")
                    )
                    if (
                        "parent_repo_hash" in change_data
                        and change_data["parent_repo_hash"]
                    ):
                        console.print(
                            f"\n[bold]Parent repo hash:[/bold] {change_data['parent_repo_hash']}"
                        )
                        console.print(
                            "[dim]Use this hash to sync changes back to your main repository[/dim]"
                        )
            except Exception:
                pass

    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")


@main.command()
def capture():
    """Capture a change from Claude hook (internal command)."""
    # This will be called by the hook


@main.command()
@click.argument("commit_hash")
@click.option(
    "--dry-run", is_flag=True, help="Show what would be applied without making changes"
)
def apply(commit_hash: str, dry_run: bool):
    """Apply a Claude change to the main project files."""
    project_root = _find_project_root()
    if not project_root:
        return

    claude_repo = ClaudeGitRepository(project_root)
    if not claude_repo.exists():
        console.print(
            "[red]Claude Git not initialized. Run 'claude-git init' first.[/red]"
        )
        return

    try:
        # Get the patch file for this commit
        commit = claude_repo.repo.commit(commit_hash)
        console.print(
            f"[bold]Applying commit:[/bold] {commit.hexsha[:8]} - {commit.message.split()[0]}"
        )

        # Find patch files in this commit
        patch_files = [f for f in commit.tree.traverse() if f.name.endswith(".patch")]

        if not patch_files:
            console.print("[red]No patch file found in this commit[/red]")
            return

        for patch_file in patch_files:
            patch_content = patch_file.data_stream.read().decode("utf-8")

            if dry_run:
                console.print("\n[bold]Would apply patch:[/bold]")
                console.print(patch_content)
            else:
                console.print("[yellow]Manual patch application required:[/yellow]")
                console.print("Copy the patch content and apply with: git apply")
                console.print("\n[bold]Patch content:[/bold]")
                console.print(patch_content)

    except Exception as e:
        console.print(f"[red]Error applying change: {e}[/red]")


@main.command()
@click.argument("commit_hash")
def rollback(commit_hash: str):
    """Generate a reverse patch to undo a Claude change."""
    project_root = _find_project_root()
    if not project_root:
        return

    claude_repo = ClaudeGitRepository(project_root)
    if not claude_repo.exists():
        console.print(
            "[red]Claude Git not initialized. Run 'claude-git init' first.[/red]"
        )
        return

    try:
        # Get the commit and create reverse patch
        commit = claude_repo.repo.commit(commit_hash)
        console.print(
            f"[bold]Creating rollback for:[/bold] {commit.hexsha[:8]} - {commit.message.split()[0]}"
        )

        # Find JSON files to get the original change data
        json_files = [f for f in commit.tree.traverse() if f.name.endswith(".json")]

        for json_file in json_files:
            change_data = json.loads(json_file.data_stream.read().decode("utf-8"))

            # Create reverse patch
            if change_data["old_string"] and change_data["new_string"]:
                reverse_patch = f"""--- {change_data["file_path"]}
+++ {change_data["file_path"]}
@@ -1,1 +1,1 @@
-{change_data["new_string"]}
+{change_data["old_string"]}
"""
                console.print("[bold]Reverse patch to undo this change:[/bold]")
                console.print(reverse_patch)
            else:
                console.print(
                    f"[yellow]Complex change - manual rollback required for {change_data['file_path']}[/yellow]"
                )

    except Exception as e:
        console.print(f"[red]Error creating rollback: {e}[/red]")


@main.command()
@click.argument("commit_ref", required=False)
@click.option(
    "--dry-run", is_flag=True, help="Show what would be reverted without making changes"
)
@click.option(
    "--interactive",
    "-i",
    is_flag=True,
    help="Interactively choose which changes to revert",
)
@click.option("--status", is_flag=True, help="Show revert history and restore options")
def revert(commit_ref: str, dry_run: bool, interactive: bool, status: bool):
    """Revert Claude's changes from a specific commit or range.

    Supports git-style commit references:
      claude-git revert HEAD                     # Revert most recent Claude change
      claude-git revert HEAD~1                   # Revert Claude change from 1 commit ago
      claude-git revert <commit-hash>            # Revert specific commit
      claude-git revert HEAD~5..HEAD            # Revert range of commits
      claude-git revert HEAD~2...HEAD~1         # Revert commits in range
    """
    project_root = _find_project_root()
    if not project_root:
        return

    claude_repo = ClaudeGitRepository(project_root)
    if not claude_repo.exists():
        console.print(
            "[red]Claude Git not initialized. Run 'claude-git init' first.[/red]"
        )
        return

    # Handle status flag - show revert history
    if status:
        _show_revert_status(claude_repo)
        return

    # Require commit_ref if not using status
    if not commit_ref:
        console.print(
            "[red]Error: COMMIT_REF is required when not using --status[/red]"
        )
        console.print("Use 'claude-git revert --status' to see revert history")
        return

    try:
        # Parse the commit reference using our existing logic
        if ".." in commit_ref or "..." in commit_ref:
            # Range of commits
            _revert_commit_range(claude_repo, commit_ref, dry_run, interactive)
        else:
            # Single commit
            _revert_single_commit(claude_repo, commit_ref, dry_run, interactive)

    except Exception as e:
        console.print(f"[red]Error reverting changes: {e}[/red]")


@main.command()
@click.argument("commit_ref")
@click.option(
    "--dry-run", is_flag=True, help="Show what would be restored without making changes"
)
@click.option(
    "--interactive",
    "-i",
    is_flag=True,
    help="Interactively choose which changes to restore",
)
@click.option("--force", is_flag=True, help="Force restore even if there are conflicts")
def restore(commit_ref: str, dry_run: bool, interactive: bool, force: bool):
    """Restore Claude's changes to a specific commit state (fast-forward navigation).

    This command allows you to move forward to a later Claude commit state,
    effectively re-applying changes that may have been reverted.

    Supports git-style commit references:
      claude-git restore HEAD                      # Restore to latest Claude state
      claude-git restore HEAD~1                    # Restore to 1 commit ago state
      claude-git restore <commit-hash>             # Restore to specific commit state
      claude-git restore HEAD~5..HEAD             # Restore range of commits
    """
    project_root = _find_project_root()
    if not project_root:
        return
    claude_repo = ClaudeGitRepository(project_root)
    if not claude_repo.exists():
        console.print(
            "[red]Claude Git not initialized. Run 'claude-git init' first.[/red]"
        )
        return
    try:
        # Parse the commit reference using our existing logic
        if ".." in commit_ref or "..." in commit_ref:
            # Range of commits
            _restore_commit_range(claude_repo, commit_ref, dry_run, interactive, force)
        else:
            # Single commit
            _restore_single_commit(claude_repo, commit_ref, dry_run, interactive, force)

    except Exception as e:
        console.print(f"[red]Error restoring changes: {e}[/red]")


@main.command()
@click.argument("parent_hash")
def find_by_parent(parent_hash: str):
    """Find Claude changes made at a specific parent repo hash."""
    project_root = _find_project_root()
    if not project_root:
        return

    claude_repo = ClaudeGitRepository(project_root)
    if not claude_repo.exists():
        console.print(
            "[red]Claude Git not initialized. Run 'claude-git init' first.[/red]"
        )
        return

    try:
        # Search through commits for matching parent hash
        matching_commits = []

        for commit in claude_repo.repo.iter_commits():
            try:
                json_files = [
                    f
                    for f in commit.tree.traverse()
                    if f.name.endswith(".json") and "changes/" in str(f.path)
                ]
                for json_file in json_files:
                    try:
                        change_data = json.loads(
                            json_file.data_stream.read().decode("utf-8")
                        )
                        # Skip if not a change record (must have 'id' field)
                        if not change_data.get("id"):
                            continue
                        parent_repo_hash = change_data.get("parent_repo_hash", "")
                        if (
                            parent_repo_hash
                            and parent_repo_hash.startswith(parent_hash)
                        ) or parent_hash in commit.message:
                            matching_commits.append((commit, change_data))
                            break
                    except (json.JSONDecodeError, KeyError):
                        continue
            except Exception:
                continue

        if not matching_commits:
            console.print(
                f"[yellow]No Claude changes found for parent hash: {parent_hash}[/yellow]"
            )
            return

        console.print(
            f"[bold]Claude changes for parent repo hash {parent_hash}:[/bold]"
        )
        console.print()

        for commit, change_data in matching_commits:
            console.print(
                f"[cyan]{commit.hexsha[:8]}[/cyan] - {commit.message.split()[0]} {commit.message.split()[1] if len(commit.message.split()) > 1 else ''}"
            )
            console.print(f"  File: {change_data.get('file_path', 'unknown')}")
            console.print(f"  Time: {change_data.get('timestamp', 'unknown')}")
            console.print(
                f"  Parent: {change_data.get('parent_repo_hash', 'unknown')[:8]}"
            )
            console.print()

    except Exception as e:
        console.print(f"[red]Error searching changes: {e}[/red]")


@main.command()
@click.option("--session-id", help="Check conflicts for specific session")
@click.option("--limit", default=10, help="Number of recent changes to check")
def conflicts(session_id: Optional[str], limit: int):
    """Show potential conflicts between Claude and human changes."""
    project_root = _find_project_root()
    if not project_root:
        return

    claude_repo = ClaudeGitRepository(project_root)
    if not claude_repo.exists():
        console.print(
            "[red]Claude Git not initialized. Run 'claude-git init' first.[/red]"
        )
        return

    try:
        # Get recent commits to analyze
        if session_id:
            session = claude_repo.get_session(session_id)
            if not session:
                console.print(f"[red]Session {session_id} not found[/red]")
                return
            commits = claude_repo.get_commits_for_session(session_id)[:limit]
        else:
            # Get recent commits from all sessions
            args = ["log", f"--max-count={limit}", "--format=%H"]
            result = claude_repo.run_git_command(args)
            commit_hashes = result.strip().split("\n") if result.strip() else []
            commits = [claude_repo.repo.commit(h) for h in commit_hashes if h]

        conflicts_found = 0

        for commit in commits:
            # Find JSON files in this commit
            json_files = [
                f
                for f in commit.tree.traverse()
                if f.name.endswith(".json") and "changes/" in str(f.path)
            ]

            for json_file in json_files:
                try:
                    change_data = json.loads(
                        json_file.data_stream.read().decode("utf-8")
                    )
                    if not change_data.get("id"):  # Skip non-change files
                        continue

                    conflict_analysis = change_data.get("conflict_analysis", {})

                    if conflict_analysis.get("has_conflicts"):
                        conflicts_found += 1

                        console.print(
                            f"\n[bold red]⚠️  Conflict detected in commit {commit.hexsha[:8]}[/bold red]"
                        )
                        console.print(
                            f"[bold]File:[/bold] {change_data.get('file_path')}"
                        )
                        console.print(
                            f"[bold]Time:[/bold] {change_data.get('timestamp')}"
                        )

                        if conflict_analysis.get("same_file_modified"):
                            console.print(
                                "[yellow]• Both you and Claude modified the same file[/yellow]"
                            )

                        if conflict_analysis.get("related_files_modified"):
                            related_files = ", ".join(
                                conflict_analysis["related_files_modified"]
                            )
                            console.print(
                                f"[yellow]• Related files also modified: {related_files}[/yellow]"
                            )

                        if conflict_analysis.get("recommendations"):
                            console.print("[bold]Recommendations:[/bold]")
                            for rec in conflict_analysis["recommendations"]:
                                console.print(f"  {rec}")

                        # Show human modifications summary
                        human_mods = conflict_analysis.get("human_modifications", [])
                        if human_mods:
                            mod_summary = {}
                            for mod in human_mods:
                                mod_type = mod["type"]
                                mod_summary[mod_type] = mod_summary.get(mod_type, 0) + 1

                            summary_parts = [
                                f"{count} {mod_type}"
                                for mod_type, count in mod_summary.items()
                            ]
                            console.print(
                                f"[dim]Human changes: {', '.join(summary_parts)}[/dim]"
                            )

                except (json.JSONDecodeError, KeyError):
                    continue

        if conflicts_found == 0:
            console.print("[green]✅ No conflicts detected in recent changes[/green]")
        else:
            console.print(f"\n[bold]Found {conflicts_found} potential conflicts[/bold]")
            console.print(
                "[dim]Use 'claude-git resolve <commit-hash>' for resolution assistance[/dim]"
            )

    except Exception as e:
        console.print(f"[red]Error checking conflicts: {e}[/red]")


@main.command()
@click.argument("commit_hash")
def resolve(commit_hash: str):
    """Get conflict resolution assistance for a specific commit."""
    project_root = _find_project_root()
    if not project_root:
        return

    claude_repo = ClaudeGitRepository(project_root)
    if not claude_repo.exists():
        console.print(
            "[red]Claude Git not initialized. Run 'claude-git init' first.[/red]"
        )
        return

    try:
        commit = claude_repo.repo.commit(commit_hash)
        console.print(
            f"[bold]Conflict resolution for commit {commit.hexsha[:8]}[/bold]"
        )

        # Find the change data
        json_files = [
            f
            for f in commit.tree.traverse()
            if f.name.endswith(".json") and "changes/" in str(f.path)
        ]

        if not json_files:
            console.print("[red]No change data found in this commit[/red]")
            return

        change_data = json.loads(json_files[0].data_stream.read().decode("utf-8"))
        conflict_analysis = change_data.get("conflict_analysis", {})

        if not conflict_analysis.get("has_conflicts"):
            console.print("[green]No conflicts detected for this change[/green]")
            return

        console.print("\n[bold]Claude's Change:[/bold]")
        console.print(f"File: {change_data.get('file_path')}")
        console.print(f"Type: {change_data.get('change_type')}")

        if change_data.get("old_string") and change_data.get("new_string"):
            console.print(
                f"Changed: '{change_data['old_string']}' → '{change_data['new_string']}'"
            )

        console.print("\n[bold red]Conflicts Detected:[/bold red]")
        for rec in conflict_analysis.get("recommendations", []):
            console.print(f"• {rec}")

        console.print("\n[bold]Resolution Options:[/bold]")
        console.print("[green]1.[/green] Review changes manually and apply selectively")
        console.print("[green]2.[/green] Use git merge tools to resolve conflicts")
        console.print(
            "[green]3.[/green] Apply Claude's change and manually fix conflicts"
        )
        console.print("[green]4.[/green] Skip this change and continue with others")

        # Show current parent repo status
        current_status = claude_repo._get_parent_repo_status()
        if current_status and current_status.get("has_changes"):
            console.print(
                "\n[yellow]⚠️  Parent repository currently has uncommitted changes[/yellow]"
            )
            console.print(
                "[dim]Consider committing or stashing changes before applying Claude's modifications[/dim]"
            )

    except Exception as e:
        console.print(f"[red]Error analyzing conflict: {e}[/red]")


@main.command()
@click.option("--session-id", help="Analyze specific session")
@click.option("--include-clean", is_flag=True, help="Include changes without conflicts")
def analyze(session_id: Optional[str], include_clean: bool):
    """Analyze patterns in Claude's changes and provide intelligent merge suggestions."""
    project_root = _find_project_root()
    if not project_root:
        return

    claude_repo = ClaudeGitRepository(project_root)
    if not claude_repo.exists():
        console.print(
            "[red]Claude Git not initialized. Run 'claude-git init' first.[/red]"
        )
        return

    try:
        # Get changes to analyze
        if session_id:
            session = claude_repo.get_session(session_id)
            if not session:
                console.print(f"[red]Session {session_id} not found[/red]")
                return
            commits = claude_repo.get_commits_for_session(session_id)
            console.print(f"[bold]Analysis for session {session_id[:8]}...[/bold]")
        else:
            # Get recent commits from all sessions
            args = ["log", "--max-count=50", "--format=%H"]
            result = claude_repo.run_git_command(args)
            commit_hashes = result.strip().split("\n") if result.strip() else []
            commits = [claude_repo.repo.commit(h) for h in commit_hashes if h]
            console.print("[bold]Analysis of recent Claude changes[/bold]")

        # Analyze patterns
        analysis = {
            "total_changes": 0,
            "conflict_changes": 0,
            "file_types": {},
            "change_types": {},
            "conflict_patterns": {
                "same_file_conflicts": 0,
                "related_file_conflicts": 0,
                "high_activity_periods": 0,
            },
            "recommendations": [],
            "merge_strategy": None,
        }

        human_activity_score = 0
        claude_activity_score = 0

        for commit in commits:
            json_files = [
                f
                for f in commit.tree.traverse()
                if f.name.endswith(".json") and "changes/" in str(f.path)
            ]

            for json_file in json_files:
                try:
                    change_data = json.loads(
                        json_file.data_stream.read().decode("utf-8")
                    )
                    if not change_data.get("id"):
                        continue

                    analysis["total_changes"] += 1
                    claude_activity_score += 1

                    # Track file types
                    file_path = change_data.get("file_path", "")
                    file_ext = Path(file_path).suffix or "no_extension"
                    analysis["file_types"][file_ext] = (
                        analysis["file_types"].get(file_ext, 0) + 1
                    )

                    # Track change types
                    change_type = change_data.get("change_type", "unknown")
                    analysis["change_types"][change_type] = (
                        analysis["change_types"].get(change_type, 0) + 1
                    )

                    # Analyze conflicts
                    conflict_analysis = change_data.get("conflict_analysis", {})
                    if conflict_analysis.get("has_conflicts"):
                        analysis["conflict_changes"] += 1

                        if conflict_analysis.get("same_file_modified"):
                            analysis["conflict_patterns"]["same_file_conflicts"] += 1

                        if conflict_analysis.get("related_files_modified"):
                            analysis["conflict_patterns"]["related_file_conflicts"] += 1

                        # Count human activity
                        human_mods = conflict_analysis.get("human_modifications", [])
                        human_activity_score += len(human_mods)

                        # Check for high activity periods
                        if len(human_mods) > 3:
                            analysis["conflict_patterns"]["high_activity_periods"] += 1

                except (json.JSONDecodeError, KeyError):
                    continue

        # Generate intelligent recommendations
        if analysis["total_changes"] == 0:
            console.print("[yellow]No Claude changes found to analyze[/yellow]")
            return

        conflict_ratio = analysis["conflict_changes"] / analysis["total_changes"]
        human_claude_ratio = human_activity_score / max(claude_activity_score, 1)

        console.print("\n[bold]📊 Change Analysis Summary[/bold]")
        console.print(f"Total changes: {analysis['total_changes']}")
        console.print(
            f"Conflicts detected: {analysis['conflict_changes']} ({conflict_ratio:.1%})"
        )
        console.print(f"Human/Claude activity ratio: {human_claude_ratio:.2f}")

        # File type analysis
        if analysis["file_types"]:
            console.print("\n[bold]📁 File Types Modified[/bold]")
            sorted_types = sorted(
                analysis["file_types"].items(), key=lambda x: x[1], reverse=True
            )
            for file_type, count in sorted_types[:5]:
                console.print(f"  {file_type}: {count} changes")

        # Determine merge strategy
        if conflict_ratio < 0.1:
            analysis["merge_strategy"] = "safe_auto_merge"
            strategy_desc = "🟢 Safe Auto-Merge"
            strategy_detail = (
                "Low conflict rate - most changes can be applied automatically"
            )
        elif conflict_ratio < 0.3:
            analysis["merge_strategy"] = "selective_merge"
            strategy_desc = "🟡 Selective Merge"
            strategy_detail = "Moderate conflicts - review each change before applying"
        else:
            analysis["merge_strategy"] = "careful_manual_merge"
            strategy_desc = "🔴 Careful Manual Merge"
            strategy_detail = (
                "High conflict rate - manual review required for all changes"
            )

        console.print(f"\n[bold]🎯 Recommended Merge Strategy: {strategy_desc}[/bold]")
        console.print(f"  {strategy_detail}")

        # Specific recommendations
        recommendations = []

        if analysis["conflict_patterns"]["same_file_conflicts"] > 2:
            recommendations.append(
                "⚠️  Multiple same-file conflicts detected. Consider using git merge tools."
            )

        if analysis["conflict_patterns"]["high_activity_periods"] > 0:
            recommendations.append(
                "📊 High human activity detected. Coordinate changes or use feature branches."
            )

        if human_claude_ratio > 2:
            recommendations.append(
                "👥 Heavy human modification activity. Consider pair programming workflow."
            )

        if (
            analysis["change_types"].get("edit", 0)
            > analysis["change_types"].get("write", 0) * 3
        ):
            recommendations.append(
                "✏️  Many small edits detected. Consider batching related changes."
            )

        # Workflow recommendations based on file types
        python_files = analysis["file_types"].get(".py", 0)
        js_files = analysis["file_types"].get(".js", 0) + analysis["file_types"].get(
            ".ts", 0
        )

        if python_files > 0:
            recommendations.append(
                "🐍 Python files modified. Run tests before merging changes."
            )
        if js_files > 0:
            recommendations.append(
                "🟨 JavaScript/TypeScript files modified. Check linting and build."
            )

        if recommendations:
            console.print("\n[bold]💡 Intelligent Recommendations[/bold]")
            for i, rec in enumerate(recommendations, 1):
                console.print(f"  {i}. {rec}")

        # Next steps
        console.print("\n[bold]🚀 Suggested Next Steps[/bold]")
        if analysis["merge_strategy"] == "safe_auto_merge":
            console.print("  1. Review changes with: claude-git log --oneline")
            console.print("  2. Apply clean changes: claude-git apply <commit-hash>")
            console.print("  3. Test and commit to main repository")
        elif analysis["merge_strategy"] == "selective_merge":
            console.print("  1. Check conflicts: claude-git conflicts")
            console.print("  2. Resolve conflicts: claude-git resolve <commit-hash>")
            console.print("  3. Apply non-conflicting changes first")
        else:
            console.print("  1. Review all conflicts: claude-git conflicts --limit 20")
            console.print("  2. Plan merge strategy with team")
            console.print("  3. Use git merge tools for complex conflicts")

    except Exception as e:
        console.print(f"[red]Error during analysis: {e}[/red]")


@main.command()
def setup_hooks():
    """Set up Claude Code hooks for session-based change tracking."""
    from claude_git.cli.setup_hooks import main as setup_hooks_main

    setup_hooks_main()


def _process_git_diff_args(args):
    """Process git diff arguments for git-native execution."""
    processed_args = []

    for arg in args:
        # Handle HEAD~ syntax
        if (
            arg.startswith(("HEAD~", "-"))
            or ".." in arg
            or len(arg) >= 7
            and all(c in "0123456789abcdef" for c in arg)
        ):
            processed_args.append(arg)
        else:
            # File paths or other arguments
            processed_args.append(arg)

    return processed_args


def _handle_git_native_parent_hash_diff(git_native_repo, parent_hash, args, no_pager):
    """Handle diff filtering by parent repository hash."""
    import subprocess

    # Find claude-git commits that correspond to this parent repo hash
    try:
        # Get all commits with the parent repo hash in their message
        grep_cmd = [
            "git",
            "-C",
            str(git_native_repo.claude_git_dir),
            "log",
            f"--grep=Parent-Repo: {parent_hash}",
            "--pretty=format:%H",
        ]
        result = subprocess.run(grep_cmd, capture_output=True, text=True)

        if result.returncode != 0:
            console.print(
                f"[red]No commits found for parent repo hash: {parent_hash}[/red]"
            )
            return

        commit_hashes = result.stdout.strip().split("\n")
        if not commit_hashes or commit_hashes == [""]:
            console.print(
                f"[red]No commits found for parent repo hash: {parent_hash}[/red]"
            )
            return

        # Show diff for these commits
        console.print(
            f"[green]Showing changes from parent repo hash: {parent_hash}[/green]"
        )

        for commit_hash in commit_hashes:
            if not commit_hash.strip():
                continue

            # Show the commit diff
            diff_cmd = [
                "git",
                "-C",
                str(git_native_repo.claude_git_dir),
                "show",
                commit_hash.strip(),
            ]
            if no_pager:
                diff_cmd.append("--no-pager")

            result = subprocess.run(diff_cmd, capture_output=True, text=True)

            if result.returncode == 0 and result.stdout:
                if no_pager:
                    print(result.stdout)
                else:
                    _pipe_to_pager(result.stdout)
            else:
                console.print(
                    f"[yellow]Warning: Could not show diff for commit {commit_hash.strip()}[/yellow]"
                )

    except Exception as e:
        console.print(f"[red]Error processing parent hash diff: {e}[/red]")


def _parse_diff_args(args):
    """Parse git-style diff arguments."""
    parsed = {"commit_range": None, "single_commit": None, "paths": [], "options": []}

    # Split args at -- separator
    if "--" in args:
        separator_idx = args.index("--")
        commit_args = list(args[:separator_idx])
        parsed["paths"] = list(args[separator_idx + 1 :])
    else:
        commit_args = list(args)
        # If no --, and we have args that look like paths (contain / or .), treat as paths
        if commit_args and not any("..." in arg or ".." in arg for arg in commit_args):
            # Check if args look like git commit refs
            potential_commits = []
            potential_paths = []

            for arg in commit_args:
                if (
                    arg.startswith(("HEAD", "-"))
                    or len(arg) >= 7
                    and all(c in "0123456789abcdef" for c in arg)
                ):
                    potential_commits.append(arg)
                else:
                    potential_paths.append(arg)

            # If we have both potential commits and paths, use the first as commit and rest as paths
            if potential_commits and potential_paths:
                commit_args = potential_commits
                parsed["paths"] = potential_paths
            elif potential_paths and not potential_commits:
                # All look like paths
                commit_args = []
                parsed["paths"] = potential_paths
            # else: all look like commits, keep as is

    # Process commit arguments - handle commit ranges with paths
    commit_found = False
    for i, arg in enumerate(commit_args):
        if "..." in arg:
            # Range syntax: commit1...commit2
            parsed["commit_range"] = arg
            commit_found = True
            # Remaining args after range are paths (if not using -- separator)
            if "--" not in args:
                parsed["paths"].extend(commit_args[i + 1 :])
            break
        if ".." in arg:
            # Range syntax: commit1..commit2 (two-dot diff: A..B shows diff between A and B)
            parsed["commit_range"] = arg
            commit_found = True
            # Remaining args after range are paths (if not using -- separator)
            if "--" not in args:
                parsed["paths"].extend(commit_args[i + 1 :])
            break
        if arg.startswith("-"):
            # Option
            parsed["options"].append(arg)
        elif not parsed["single_commit"] and not commit_found:
            # Single commit
            parsed["single_commit"] = arg
            commit_found = True
            # Remaining args after commit are paths (if not using -- separator)
            if "--" not in args:
                parsed["paths"].extend(commit_args[i + 1 :])
            break

    return parsed


def _resolve_commit_ref_for_parent_repo(parent_repo, ref):
    """Resolve commit reference for the parent repository (not .claude-git)."""
    try:
        if ref.startswith("HEAD"):
            # Handle HEAD~n syntax
            if ref == "HEAD":
                return parent_repo.head.commit.hexsha
            if "~" in ref:
                distance = int(ref.split("~")[1]) if ref.split("~")[1].isdigit() else 1
                commit = parent_repo.head.commit
                for _i in range(distance):
                    if commit.parents:
                        commit = commit.parents[0]
                    else:
                        # Not enough parents - this commit reference doesn't exist
                        raise ValueError(
                            f"ambiguous argument '{ref}': unknown revision or path not in the working tree"
                        )
                return commit.hexsha
        else:
            # Try to resolve as commit hash
            commit = parent_repo.commit(ref)
            return commit.hexsha
    except Exception as e:
        # Re-raise with git-like error message for invalid references
        if "ambiguous argument" in str(e):
            raise  # Already has proper error message
        raise ValueError(
            f"ambiguous argument '{ref}': unknown revision or path not in the working tree"
        ) from e


def _resolve_commit_ref(claude_repo, ref):
    """Resolve commit reference (HEAD, HEAD~1, etc.) to actual commit hash."""
    try:
        if ref.startswith("HEAD"):
            # Handle HEAD~n syntax
            if ref == "HEAD":
                return claude_repo.repo.head.commit.hexsha
            if "~" in ref:
                distance = int(ref.split("~")[1]) if ref.split("~")[1].isdigit() else 1
                commit = claude_repo.repo.head.commit
                actual_distance = 0
                for _i in range(distance):
                    if commit.parents:
                        commit = commit.parents[0]
                        actual_distance += 1
                    else:
                        # Not enough parents - this commit reference doesn't exist
                        raise ValueError(
                            f"ambiguous argument '{ref}': unknown revision or path not in the working tree"
                        )
                return commit.hexsha
        else:
            # Try to resolve as commit hash
            commit = claude_repo.repo.commit(ref)
            return commit.hexsha
    except Exception as e:
        # Re-raise with git-like error message for invalid references
        if "ambiguous argument" in str(e):
            raise  # Already has proper error message
        raise ValueError(
            f"ambiguous argument '{ref}': unknown revision or path not in the working tree"
        ) from e


def _handle_no_index_diff(claude_repo, parsed_args, verbose, tool=None, no_pager=False):
    """Handle --no-index diff for arbitrary file comparison."""
    paths = parsed_args.get("paths", [])
    if len(paths) != 2:
        console.print("[red]Error: --no-index requires exactly 2 paths[/red]")
        return

    console.print(
        f"[yellow]--no-index comparison not yet implemented for paths: {paths[0]} {paths[1]}[/yellow]"
    )


def _handle_commit_range_diff(
    claude_repo, parsed_args, parent_hash, verbose, tool=None, no_pager=False
):
    """Handle commit range diff (commit1...commit2)."""
    commit_range = parsed_args["commit_range"]

    if "..." in commit_range:
        # Three-dot syntax: A...B
        # For git diff, this means diff between merge-base(A,B) and B
        start_ref, end_ref = commit_range.split("...")
        start_commit = _resolve_commit_ref(claude_repo, start_ref)
        end_commit = _resolve_commit_ref(claude_repo, end_ref)

        # Find merge base between the two commits
        try:
            merge_base = claude_repo.repo.merge_base(start_commit, end_commit)
            if merge_base:
                # Use merge base as the actual start commit
                actual_start = merge_base[0].hexsha
            else:
                actual_start = start_commit
        except Exception:
            actual_start = start_commit

        console.print(
            f"[bold]Claude Changes Between {actual_start[:8]}...{end_commit[:8]} (three-dot)[/bold]\n"
        )
        commits_range = f"{actual_start}..{end_commit}"
    else:
        # Two-dot syntax: A..B
        # For git diff, this is the same as "git diff A B"
        start_ref, end_ref = commit_range.split("..")
        start_commit = _resolve_commit_ref(claude_repo, start_ref)
        end_commit = _resolve_commit_ref(claude_repo, end_ref)

        console.print(
            f"[bold]Claude Changes Between {start_commit[:8]}..{end_commit[:8]} (two-dot)[/bold]\n"
        )
        commits_range = f"{start_commit}..{end_commit}"

    # Get commits in range
    try:
        commits_in_range = list(claude_repo.repo.iter_commits(commits_range))
        if not commits_in_range:
            console.print("[yellow]No commits found in range[/yellow]")
            return

        for commit in commits_in_range:
            # Analyze this specific commit
            diff_results = claude_repo.get_meaningful_diff_for_commit(
                commit.hexsha, parent_hash=parent_hash, paths=parsed_args.get("paths")
            )
            if diff_results and diff_results.get("changes_analyzed"):
                # Collect diff output for paging
                diff_output = ""
                for change in diff_results["changes_analyzed"]:
                    diff_output += _get_git_style_diff_text(change, tool) + "\n"

                # Show output with paging if needed
                if not no_pager:
                    _pipe_to_pager(diff_output.rstrip())
                else:
                    print(diff_output.rstrip())

    except Exception as e:
        console.print(f"[red]Error processing commit range: {e}[/red]")


def _handle_single_commit_diff(
    claude_repo, parsed_args, parent_hash, verbose, tool=None, no_pager=False
):
    """Handle single commit diff - behaves like 'git diff <commit>' (diff from commit to working dir)."""
    commit_ref = parsed_args["single_commit"]

    # Test if the commit reference is valid by resolving it in the .claude-git repository
    try:
        claude_git_repo = gitpython.Repo(claude_repo.claude_git_dir)
        _resolve_commit_ref_for_parent_repo(claude_git_repo, commit_ref)
    except ValueError as e:
        # Print git-like error and exit with error code
        # Use regular print for stderr to avoid Rich console issues
        print(f"fatal: {e}", file=sys.stderr)
        sys.exit(128)  # Git uses exit code 128 for invalid references

    # Use git diff on .claude-git/files to show Claude's changes
    try:
        # Check if .claude-git directory exists and is a git repository
        if (
            not claude_repo.claude_git_dir.exists()
            or not (claude_repo.claude_git_dir / ".git").exists()
        ):
            return  # No Claude git repository exists

        # Check if .claude-git/files directory exists - if not, no Claude changes exist
        claude_files_dir = claude_repo.project_root / ".claude-git" / "files"
        if not claude_files_dir.exists():
            return  # No Claude changes exist, return empty like git diff

        # Run git diff in the .claude-git repository to show Claude's commit history
        cmd = ["git", "diff", commit_ref, "HEAD", "files/"] + (
            parsed_args.get("paths", [])
        )

        git_diff_result = subprocess.run(
            cmd, cwd=claude_repo.claude_git_dir, capture_output=True, text=True
        )

        if git_diff_result.returncode != 0:
            console.print(
                f"[red]Error running git diff: {git_diff_result.stderr}[/red]"
            )
            return

        if not git_diff_result.stdout.strip():
            return  # No changes, like git diff with no output

        # Process the diff output to clean up paths and filter out metadata
        diff_lines = git_diff_result.stdout.split("\n")
        filtered_output = []

        for line in diff_lines:
            if line.startswith("diff --git"):
                # Convert files/path back to just path
                # Example: "diff --git a/files/src/main.py b/files/src/main.py"
                # becomes: "diff --git a/src/main.py b/src/main.py"
                line = line.replace("a/files/", "a/").replace("b/files/", "b/")
                filtered_output.append(line)
                # Add comment showing cumulative Claude changes
                filtered_output.append(f"# Claude changes from {commit_ref} to HEAD")
            elif line.startswith("new file mode"):
                # Handle new file mode lines
                filtered_output.append(line)
            elif line.startswith("index "):
                # Handle git index lines
                filtered_output.append(line)
            elif line.startswith("--- a/files/"):
                # Fix path in diff header
                line = line.replace("--- a/files/", "--- a/")
                filtered_output.append(line)
            elif line.startswith("--- /dev/null"):
                # Handle new files (no changes needed)
                filtered_output.append(line)
            elif line.startswith("+++ b/files/"):
                # Fix path in diff header
                line = line.replace("+++ b/files/", "+++ b/")
                filtered_output.append(line)
            elif line.startswith("+++ /dev/null"):
                # Handle deleted files (no changes needed)
                filtered_output.append(line)
            else:
                filtered_output.append(line)

        # Show output with paging if needed
        final_output = "\n".join(filtered_output).rstrip()

        if final_output:
            if not no_pager:
                _pipe_to_pager(final_output)
            else:
                print(final_output)

    except Exception as e:
        console.print(f"[red]Error processing single commit diff: {e}[/red]")


def _get_git_style_diff_text(change, external_tool: Optional[str] = None):
    """Get git diff style text for a change, optionally using external diff tool."""
    file_path = change["file_path"]
    diff_lines = change.get("diff_lines", [])

    # If no diff lines, skip (like git diff when there's nothing to show)
    if not diff_lines:
        return ""

    # Skip single-line status messages (these are legacy format)
    if len(diff_lines) == 1 and (
        diff_lines[0].startswith("✅") or diff_lines[0].startswith("❌")
    ):
        return ""

    # For external diff tools, try to use them for individual file diffs
    if external_tool and len(diff_lines) > 1:
        if _try_external_diff_for_change(change, external_tool):
            return f"# Opened {file_path} in {external_tool}"

    output = ""

    # For file not found, show deletion
    if change["status"] == "file_not_found":
        output += f"diff --git a/{file_path} b/{file_path}\n"
        output += "deleted file mode 100644\n"
        return output
    if change["status"] == "error":
        return ""  # Skip error files

    # Show git-style diff header
    output += f"diff --git a/{file_path} b/{file_path}\n"

    # Add commit info as a comment if available
    commit_hash = change.get("commit_hash")
    commit_message = change.get("commit_message", "")
    if commit_hash:
        output += f"# Claude change {commit_hash}: {commit_message}\n"

    # Show the actual diff content
    if diff_lines and len(diff_lines) > 1:
        for line in diff_lines:
            # Skip the git header lines that are already shown
            if line.startswith(("diff --git", "index ")):
                continue
            output += line + "\n"
    else:
        # Fallback for changes without proper diff
        change_type = change.get("change_type", "unknown")
        if change_type == "write":
            output += "new file mode 100644\n"
            output += f"+++ b/{file_path}\n"
            output += "@@ -0,0 +1,1 @@\n"
            output += "+# New file created by Claude\n"
        elif change_type == "edit":
            output += f"--- a/{file_path}\n"
            output += f"+++ b/{file_path}\n"
            output += "@@ -1,1 +1,1 @@\n"
            output += "-# Modified by Claude\n"
            output += "+# Modified by Claude\n"

    return output


def _display_git_style_diff(change):
    """Display a change in git diff style (legacy function for compatibility)."""
    output = _get_git_style_diff_text(change)
    if output:
        # Print with colors
        for line in output.splitlines():
            _print_colored_diff_line(line)


def _print_colored_diff_line(line):
    """Print a diff line with git-style colors."""
    # Use Rich console for colored output similar to git
    if line.startswith("+"):
        console.print(line, style="green")
    elif line.startswith("-"):
        console.print(line, style="red")
    elif line.startswith("@@"):
        console.print(line, style="cyan")
    elif line.startswith("+++"):
        console.print(line, style="green")
    elif line.startswith("---"):
        console.print(line, style="red")
    elif line.startswith(("index ", "diff --git")):
        console.print(line, style="white")
    else:
        # Regular line
        print(line)


def _display_change_analysis(change, verbose=False):
    """Display analysis for a single change (legacy format)."""
    status_color = {
        "unchanged": "green",
        "user_modified": "yellow",
        "file_not_found": "red",
        "error": "red",
    }.get(change["status"], "white")

    status_icon = {
        "unchanged": "✅",
        "user_modified": "📝",
        "file_not_found": "❌",
        "error": "💥",
    }.get(change["status"], "❓")

    console.print(
        f"[bold {status_color}]{status_icon} {change['file_path']}[/bold {status_color}]"
    )
    console.print(
        f"   [dim]Commit: {change['commit_hash']} - {change['commit_message']}[/dim]"
    )

    # Show tool call information
    change_type = change.get("change_type", "unknown")
    tool_icons = {"write": "📝", "edit": "✏️ ", "delete": "🗑️ ", "unknown": "❓"}
    tool_icon = tool_icons.get(change_type, "❓")
    console.print(f"   [dim]{tool_icon} Tool: {change_type.title()}[/dim]")

    # Show parent repo hash if available
    parent_hash = change.get("parent_repo_hash")
    if parent_hash:
        console.print(f"   [dim]Parent repo: {parent_hash[:8]}[/dim]")
    else:
        console.print("   [dim]Parent repo: unknown[/dim]")

    # Show revert information
    revert_info = change.get("revert_info", {})
    if revert_info.get("can_revert", False):
        confidence_color = {"high": "green", "medium": "yellow", "low": "red"}.get(
            revert_info.get("confidence", "low"), "white"
        )
        console.print(
            f"   [bold {confidence_color}]🔄 Can revert ({revert_info['confidence']} confidence)[/bold {confidence_color}]"
        )
        if revert_info.get("revert_command"):
            console.print(f"   [dim]Command: {revert_info['revert_command']}[/dim]")
    else:
        console.print("   [red]❌ Cannot safely revert[/red]")

    # Show warnings
    for warning in revert_info.get("warnings", []):
        console.print(f"   {warning}")

    # Show user change detection
    for user_change in change.get("user_changes_detected", []):
        console.print(f"   {user_change}")

    # Show diff content if verbose or if there are conflicts
    if verbose or change.get("has_conflicts", False):
        diff_lines = change.get("diff_lines", [])
        if diff_lines and len(diff_lines) > 1:  # Skip single-line status messages
            console.print("\n   [bold]Diff:[/bold]")
            diff_text = "\n".join(diff_lines)
            # Use syntax highlighting for diff
            syntax = Syntax(diff_text, "diff", theme="monokai", word_wrap=True)
            console.print(Panel(syntax, border_style="blue", padding=(0, 1)))

    console.print()


def _add_to_gitignore(project_root: Path) -> None:
    """Add .claude-git/ to the project's .gitignore file."""
    gitignore_path = project_root / ".gitignore"
    claude_git_entry = ".claude-git/"

    try:
        # Read existing .gitignore content
        if gitignore_path.exists():
            existing_content = gitignore_path.read_text(encoding="utf-8")
            lines = existing_content.splitlines()
        else:
            existing_content = ""
            lines = []

        # Check if .claude-git/ is already in .gitignore
        if any(
            line.strip()
            in [".claude-git/", ".claude-git", "/.claude-git/", "/.claude-git"]
            for line in lines
        ):
            console.print("[dim]  .claude-git already in .gitignore[/dim]")
            return

        # Add .claude-git/ entry
        if existing_content and not existing_content.endswith("\n"):
            # Add newline if file doesn't end with one
            new_content = existing_content + "\n"
        else:
            new_content = existing_content

        # Add claude-git entry with a comment
        if lines:  # If .gitignore has content, add some spacing
            new_content += "\n# Claude Git tracking directory\n"
        else:
            new_content += "# Claude Git tracking directory\n"
        new_content += claude_git_entry + "\n"

        # Write updated .gitignore
        gitignore_path.write_text(new_content, encoding="utf-8")

        if gitignore_path.stat().st_size == len(new_content.encode("utf-8")):
            console.print("[dim]  Added .claude-git/ to .gitignore[/dim]")
        else:
            console.print(
                "[yellow]  Warning: .gitignore may not have been updated correctly[/yellow]"
            )

    except Exception as e:
        console.print(f"[yellow]  Warning: Could not update .gitignore: {e}[/yellow]")


def _revert_single_commit(
    claude_repo, commit_ref: str, dry_run: bool, interactive: bool
):
    """Revert changes from a single commit."""
    # Resolve the commit reference to a hash
    commit_hash = _resolve_commit_ref(claude_repo, commit_ref)

    console.print(f"[bold]Reverting Claude changes from {commit_hash[:8]}[/bold]")

    # Enhanced safety check - warn about potential conflicts
    safety_check = _check_revert_safety(claude_repo, commit_hash)
    if safety_check["warnings"]:
        console.print("[yellow]⚠️  Safety warnings:[/yellow]")
        for warning in safety_check["warnings"]:
            console.print(f"  • {warning}")

        if not safety_check["safe_to_revert"] and not click.confirm(
            "Continue with revert despite warnings?", default=False
        ):
            console.print("[yellow]Revert cancelled[/yellow]")
            return

    # Try the traditional approach first (metadata-based)
    diff_results = claude_repo.get_meaningful_diff_for_commit(commit_hash)
    traditional_changes = []

    if diff_results and diff_results.get("changes_analyzed"):
        for change in diff_results["changes_analyzed"]:
            if interactive:
                # Show the change and ask user
                console.print(f"\n[bold]Change in {change['file_path']}:[/bold]")
                _display_git_style_diff(change)

                if click.confirm("Revert this change?", default=True):
                    traditional_changes.append(change)
            else:
                traditional_changes.append(change)

    # Try git-native approach (restore to parent commit state)
    git_native_reverted = 0
    if not traditional_changes:
        console.print(
            f"[dim]Using git-native revert approach for commit {commit_hash[:8]}[/dim]"
        )
        git_native_reverted = _revert_using_git_native_approach(
            claude_repo, commit_hash, dry_run, interactive
        )

    # Apply traditional reverts
    traditional_reverted = 0
    for change in traditional_changes:
        if _revert_single_change(change, dry_run, claude_repo.project_root):
            traditional_reverted += 1

    total_reverted = traditional_reverted + git_native_reverted

    if dry_run:
        if total_reverted > 0:
            console.print(f"[green]Would revert {total_reverted} change(s)[/green]")
        else:
            console.print(
                f"[yellow]No changes to revert in commit {commit_hash[:8]}[/yellow]"
            )
    else:
        if total_reverted > 0:
            console.print(
                f"[green]Successfully reverted {total_reverted} change(s)[/green]"
            )
            # Track this revert for restore navigation
            _track_revert(claude_repo, commit_hash)
        else:
            console.print(
                f"[yellow]No changes were reverted from commit {commit_hash[:8]}[/yellow]"
            )


def _revert_commit_range(
    claude_repo, commit_range: str, dry_run: bool, interactive: bool
):
    """Revert changes from a range of commits."""
    # Parse the range using our existing logic
    if "..." in commit_range:
        start_ref, end_ref = commit_range.split("...")
    else:
        start_ref, end_ref = commit_range.split("..")

    start_commit = _resolve_commit_ref(claude_repo, start_ref)
    end_commit = _resolve_commit_ref(claude_repo, end_ref)

    console.print(
        f"[bold]Reverting Claude changes from {start_commit[:8]}..{end_commit[:8]}[/bold]"
    )

    # Get commits in range
    try:
        commits_in_range = list(
            claude_repo.repo.iter_commits(f"{start_commit}..{end_commit}")
        )
        if not commits_in_range:
            console.print("[yellow]No commits found in range[/yellow]")
            return

        all_changes = []
        for commit in reversed(commits_in_range):  # Process in chronological order
            diff_results = claude_repo.get_meaningful_diff_for_commit(commit.hexsha)
            if diff_results and diff_results.get("changes_analyzed"):
                all_changes.extend(diff_results["changes_analyzed"])

        if not all_changes:
            console.print("[yellow]No Claude changes found in commit range[/yellow]")
            return

        console.print(f"Found {len(all_changes)} Claude change(s) to revert")

        changes_to_revert = []

        for change in all_changes:
            if interactive:
                # Show the change and ask user
                console.print(
                    f"\n[bold]Change in {change['file_path']} (commit {change['commit_hash']}):[/bold]"
                )
                _display_git_style_diff(change)

                if click.confirm("Revert this change?", default=True):
                    changes_to_revert.append(change)
            else:
                changes_to_revert.append(change)

        if not changes_to_revert:
            console.print("[yellow]No changes selected for reverting[/yellow]")
            return

        # Apply the reverts (in reverse chronological order to avoid conflicts)
        reverted_count = 0
        for change in reversed(changes_to_revert):
            if _revert_single_change(change, dry_run, claude_repo.project_root):
                reverted_count += 1

        if dry_run:
            console.print(f"[green]Would revert {reverted_count} change(s)[/green]")
        else:
            console.print(
                f"[green]Successfully reverted {reverted_count} change(s)[/green]"
            )

    except Exception as e:
        console.print(f"[red]Error processing commit range: {e}[/red]")


def _revert_single_change(change, dry_run: bool, project_root: Path) -> bool:
    """Revert a single change. Returns True if successful."""
    try:
        file_path = change["file_path"]
        current_file = project_root / file_path

        if not current_file.exists():
            console.print(
                f"[yellow]File {file_path} no longer exists - skipping[/yellow]"
            )
            return False

        change_type = change.get("change_type", "unknown")

        if change_type == "write":
            # For writes, we cannot safely revert file creation without risking user data
            console.print(
                f"[yellow]Cannot safely revert file creation for {file_path} - user may have modified it[/yellow]"
            )
            return False

        if change_type == "edit":
            # For edits, try to reverse the change
            return _revert_edit_change(change, current_file, dry_run)

        console.print(
            f"[yellow]Unknown change type '{change_type}' for {file_path} - skipping[/yellow]"
        )
        return False

    except Exception as e:
        console.print(
            f"[red]Error reverting change in {change.get('file_path', 'unknown')}: {e}[/red]"
        )
        return False


def _revert_edit_change(change, current_file: Path, dry_run: bool) -> bool:
    """Revert an edit change by undoing the string replacement."""
    try:
        # Get the old and new strings from the change metadata
        tool_input = change.get("tool_input", {})
        if not tool_input:
            console.print(
                f"[yellow]No tool input found for {current_file.name} - cannot revert edit[/yellow]"
            )
            return False

        params = tool_input.get("parameters", {})
        old_string = params.get("old_string", "")
        new_string = params.get("new_string", "")

        if not old_string or not new_string:
            console.print(
                f"[yellow]Missing old/new strings for {current_file.name} - cannot revert edit[/yellow]"
            )
            return False

        # Read current file content
        current_content = current_file.read_text(encoding="utf-8")

        # Check if the new_string is still in the file (i.e., the change hasn't been overwritten)
        if new_string not in current_content:
            console.print(
                f"[yellow]Claude's change in {current_file.name} appears to have been overwritten - cannot safely revert[/yellow]"
            )
            return False

        # Replace new_string back to old_string
        reverted_content = current_content.replace(new_string, old_string)

        if reverted_content == current_content:
            console.print(
                f"[yellow]No changes made to {current_file.name} - already reverted?[/yellow]"
            )
            return False

        if dry_run:
            console.print(f"[yellow]Would revert edit in {current_file.name}[/yellow]")
            # Show what would change
            import difflib

            diff_lines = list(
                difflib.unified_diff(
                    current_content.splitlines(keepends=True),
                    reverted_content.splitlines(keepends=True),
                    fromfile=f"current {current_file.name}",
                    tofile=f"reverted {current_file.name}",
                    lineterm="",
                )
            )
            for line in diff_lines[:10]:  # Show first 10 lines of diff
                console.print(line.rstrip())
        else:
            # Write the reverted content
            current_file.write_text(reverted_content, encoding="utf-8")
            console.print(f"[green]Reverted edit in {current_file.name}[/green]")

        return True

    except Exception as e:
        console.print(f"[red]Error reverting edit in {current_file.name}: {e}[/red]")
        return False


def _get_git_config(key: str) -> Optional[str]:
    """Get a git config value."""
    try:
        result = subprocess.run(
            ["git", "config", "--get", key], capture_output=True, text=True, check=False
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except Exception:
        return None


def _get_pager() -> Optional[str]:
    """Get the user's preferred pager for diff output."""
    # Check git's diff-specific pager first (this is what git diff uses)
    pager = _get_git_config("pager.diff")
    if pager:
        return pager

    # Check environment variable
    pager = os.environ.get("PAGER")
    if pager:
        return pager

    # Check git's general pager config
    pager = _get_git_config("core.pager")
    if pager:
        return pager

    # Default fallbacks
    for default_pager in ["less", "more", "cat"]:
        if shutil.which(default_pager):
            if default_pager == "less":
                return "less -FRX"  # Git's default less options
            return default_pager

    return None


def _try_external_diff_for_change(change, diff_tool: str) -> bool:
    """Try to use external diff tool for a specific change."""
    try:
        # Get the current file path
        file_path = change["file_path"]
        current_file = Path.cwd() / file_path

        if not current_file.exists():
            return False

        # Create temporary file with the before content
        # We need to reconstruct what the file looked like before Claude's change
        diff_lines = change.get("diff_lines", [])
        if not diff_lines:
            return False

        # Try to reconstruct the before content from the diff
        before_content = _reconstruct_before_content_from_diff(diff_lines, current_file)
        if before_content is None:
            return False

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=f"_before_{current_file.name}", delete=False
        ) as f_before:
            f_before.write(before_content)
            before_path = f_before.name

        try:
            # Run the configured diff tool
            cmd = _build_diff_command(
                diff_tool, before_path, str(current_file), file_path
            )
            if cmd:
                subprocess.run(cmd, check=False)
                return True
        finally:
            # Clean up temp file
            with contextlib.suppress(Exception):
                os.unlink(before_path)

    except Exception:
        pass

    return False


def _reconstruct_before_content_from_diff(
    diff_lines: List[str], current_file: Path
) -> Optional[str]:
    """Reconstruct the file content before Claude's changes from the diff."""
    try:
        current_content = current_file.read_text(encoding="utf-8")

        # Simple approach: reverse the diff by swapping + and - lines
        # This is a basic implementation - could be made more robust
        current_content.splitlines(keepends=True)

        # For now, just return None to use the built-in diff display
        # This could be enhanced later to properly reverse unified diffs
        return None

    except Exception:
        return None


def _use_external_diff_tool(
    file_before: Path, file_after: Path, file_path: str
) -> bool:
    """Use external diff tool if configured."""
    diff_tool = _get_git_config("diff.tool")
    if not diff_tool:
        return False

    try:
        # Create temporary files for the diff
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=f"_before_{Path(file_path).name}", delete=False
        ) as f_before:
            if file_before.exists():
                f_before.write(file_before.read_text(encoding="utf-8"))
            before_path = f_before.name

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=f"_after_{Path(file_path).name}", delete=False
        ) as f_after:
            if file_after.exists():
                f_after.write(file_after.read_text(encoding="utf-8"))
            after_path = f_after.name

        # Run the configured diff tool
        cmd = _build_diff_command(diff_tool, before_path, after_path, file_path)
        if cmd:
            subprocess.run(cmd, check=False)
            return True

    except Exception as e:
        console.print(
            f"[yellow]Warning: Could not use external diff tool: {e}[/yellow]"
        )
    finally:
        # Clean up temp files
        try:
            if "before_path" in locals():
                os.unlink(before_path)
            if "after_path" in locals():
                os.unlink(after_path)
        except Exception:
            pass

    return False


def _build_diff_command(
    diff_tool: str, before_path: str, after_path: str, file_path: str
) -> Optional[List[str]]:
    """Build the command for the external diff tool."""
    # Common diff tools and their command structures
    diff_commands = {
        "vimdiff": ["vim", "-d", before_path, after_path],
        "vimdiff3": ["vim", "-d", before_path, after_path],
        "code": ["code", "--diff", before_path, after_path],
        "meld": ["meld", before_path, after_path],
        "kdiff3": ["kdiff3", before_path, after_path],
        "diffmerge": ["diffmerge", before_path, after_path],
        "bc": ["bcomp", before_path, after_path],  # Beyond Compare
        "bc3": ["bcomp", before_path, after_path],
        "araxis": ["compare", before_path, after_path],
    }

    if diff_tool in diff_commands:
        return diff_commands[diff_tool]

    # Fallback: try to run the tool directly
    if shutil.which(diff_tool):
        return [diff_tool, before_path, after_path]

    return None


def _pipe_to_pager(content: str) -> None:
    """Pipe content through the user's pager if appropriate."""
    # Don't use pager if output is being redirected or if it's short
    if not sys.stdout.isatty():
        print(content)
        return

    lines = content.count("\n")
    if lines < 24:  # Less than a screen
        print(content)
        return

    pager = _get_pager()
    if not pager:
        print(content)
        return

    try:
        # Split pager command (e.g., "less -FRX" -> ["less", "-FRX"])
        pager_cmd = pager.split()

        proc = subprocess.Popen(
            pager_cmd, stdin=subprocess.PIPE, text=True, errors="replace"
        )
        proc.communicate(input=content)
        proc.wait()
    except Exception:
        # Fallback to direct output
        print(content)


def _restore_single_commit(
    claude_repo, commit_ref: str, dry_run: bool, interactive: bool, force: bool
):
    """Restore changes to a specific commit state."""
    # Resolve the commit reference to a hash
    commit_hash = _resolve_commit_ref(claude_repo, commit_ref)

    console.print(f"[bold]Restoring to Claude commit state {commit_hash[:8]}[/bold]")

    # First, check safety if not forced
    if not force:
        safety_check = _check_restore_safety(claude_repo, commit_hash)
        if not safety_check["safe_to_restore"]:
            console.print("[red]⚠️  Unsafe to restore:[/red]")
            for warning in safety_check["warnings"]:
                console.print(f"  • {warning}")
            if not click.confirm("Continue anyway?", default=False):
                console.print("[yellow]Restore cancelled[/yellow]")
                return

    # Get all files in the target commit state using git-native approach
    files_to_restore = _get_files_at_commit(claude_repo, commit_hash)

    if not files_to_restore:
        console.print(f"[yellow]No files found in commit {commit_hash[:8]}[/yellow]")
        return

    changes_to_restore = []

    # Find files to restore/modify
    for file_path, file_content in files_to_restore.items():
        current_file = claude_repo.project_root / file_path

        # Check if current file content differs from target state
        current_content = ""
        if current_file.exists():
            try:
                current_content = current_file.read_text(encoding="utf-8")
            except Exception:
                current_content = ""

        if current_content != file_content:
            change_info = {
                "file_path": file_path,
                "current_content": current_content,
                "target_content": file_content,
                "action": "create" if not current_file.exists() else "modify",
            }

            if interactive:
                # Show the change and ask user
                console.print(f"\n[bold]File: {file_path}[/bold]")
                if change_info["action"] == "create":
                    console.print(
                        f"[green]+ Create new file ({len(file_content)} chars)[/green]"
                    )
                else:
                    console.print("[yellow]~ Modify existing file[/yellow]")
                    console.print(f"  Current: {len(current_content)} chars")
                    console.print(f"  Target:  {len(file_content)} chars")

                if click.confirm("Restore this file?", default=True):
                    changes_to_restore.append(change_info)
            else:
                changes_to_restore.append(change_info)

    # Note: We don't automatically delete files that don't exist at target commit
    # because user may have their own files. Restore only modifies tracked Claude files.

    if not changes_to_restore:
        console.print(
            "[green]Already at target commit state - nothing to restore[/green]"
        )
        return

    # Apply the restores using git-native approach for exactness
    restored_count = 0
    for change in changes_to_restore:
        if _apply_git_native_restore_change(change, dry_run, claude_repo):
            restored_count += 1

    if dry_run:
        console.print(f"[green]Would restore {restored_count} file(s)[/green]")
    else:
        console.print(
            f"[green]Successfully restored {restored_count} file(s) to commit {commit_hash[:8]}[/green]"
        )


def _restore_commit_range(
    claude_repo, commit_range: str, dry_run: bool, interactive: bool, force: bool
):
    """Restore changes for a range of commits."""
    console.print(f"[bold]Restoring commit range: {commit_range}[/bold]")

    # For ranges, we restore to the final state of the range
    # Parse range to get target commit
    if "..." in commit_range:
        start_ref, end_ref = commit_range.split("...", 1)
    else:
        start_ref, end_ref = commit_range.split("..", 1)

    # Restore to the end commit state
    _restore_single_commit(claude_repo, end_ref, dry_run, interactive, force)


def _check_revert_safety(claude_repo, commit_hash: str) -> Dict:
    """Check if it's safe to revert the specified commit."""
    safety_info = {"safe_to_revert": True, "warnings": [], "conflicts": []}

    try:
        # Check current parent repo status
        current_status = claude_repo._get_parent_repo_status()
        if current_status and current_status.get("has_changes", False):
            safety_info["warnings"].append(
                "Working directory has uncommitted changes - revert may cause conflicts"
            )
            safety_info["safe_to_revert"] = False

        # Get files that would be affected by revert using git-native approach
        try:
            affected_files = _get_files_at_commit(claude_repo, commit_hash)

            for file_path in affected_files:
                claude_repo.project_root / file_path

                # Check if file was modified by user
                if current_status:
                    modified_files = current_status.get("modified_files", [])
                    if str(file_path) in modified_files:
                        safety_info["conflicts"].append(file_path)
                        safety_info["warnings"].append(
                            f"File {file_path} has user modifications - revert may conflict"
                        )
                        safety_info["safe_to_revert"] = False

        except Exception as e:
            safety_info["warnings"].append(f"Could not analyze affected files: {e}")

        # Check if we have many conflicts
        if len(safety_info["conflicts"]) > 0:
            safety_info["warnings"].append(
                f"Found {len(safety_info['conflicts'])} file(s) with potential conflicts"
            )

    except Exception as e:
        safety_info["warnings"].append(f"Error checking revert safety: {e}")
        safety_info["safe_to_revert"] = False

    return safety_info


def _check_restore_safety(claude_repo, target_commit_hash: str) -> Dict:
    """Check if it's safe to restore to the target commit state."""
    safety_info = {"safe_to_restore": True, "warnings": [], "conflicts": []}

    try:
        # Check current parent repo status
        current_status = claude_repo._get_parent_repo_status()
        if current_status and current_status.get("has_changes", False):
            safety_info["warnings"].append(
                "Working directory has uncommitted changes - restore may conflict"
            )
            safety_info["safe_to_restore"] = False

        # Get files that would be affected by restore
        target_files = _get_files_at_commit(claude_repo, target_commit_hash)

        for file_path in target_files:
            claude_repo.project_root / file_path

            # Check if file was modified by user since last Claude change
            if current_status:
                modified_files = current_status.get("modified_files", [])
                if str(file_path) in modified_files:
                    safety_info["conflicts"].append(file_path)
                    safety_info["warnings"].append(
                        f"File {file_path} has user modifications - restore will overwrite them"
                    )
                    safety_info["safe_to_restore"] = False

        if safety_info["conflicts"]:
            safety_info["warnings"].append(
                f"Found {len(safety_info['conflicts'])} file(s) with potential conflicts"
            )

    except Exception as e:
        safety_info["warnings"].append(f"Error checking restore safety: {e}")
        safety_info["safe_to_restore"] = False

    return safety_info


def _get_files_at_commit(claude_repo, commit_hash: str) -> Dict[str, str]:
    """Get all files and their content at a specific commit using git-native approach."""
    files = {}

    try:
        # Use git to get the file tree at the specific commit in .claude-git repo
        result = claude_repo.run_git_command(
            ["ls-tree", "-r", "--name-only", commit_hash, "files/"]
        )

        if not result or not result.strip():
            return files

        file_paths = result.strip().split("\n")

        for git_file_path in file_paths:
            if git_file_path.startswith("files/"):
                # Remove "files/" prefix to get actual file path
                actual_file_path = git_file_path[6:]  # Remove "files/"

                # Get file content at this commit
                try:
                    content_result = claude_repo.run_git_command(
                        ["show", f"{commit_hash}:{git_file_path}"]
                    )
                    files[actual_file_path] = content_result
                except Exception:
                    # File might not exist at this commit
                    continue

    except Exception as e:
        console.print(
            f"[yellow]Warning: Error getting files at commit {commit_hash[:8]}: {e}[/yellow]"
        )

    return files


def _apply_restore_change(change_info: Dict, dry_run: bool, project_root: Path) -> bool:
    """Apply a single restore change. Returns True if successful."""
    try:
        file_path = change_info["file_path"]
        target_content = change_info["target_content"]
        current_file = project_root / file_path

        if dry_run:
            action = change_info["action"]
            if action == "create":
                console.print(f"[green]Would create {file_path}[/green]")
            else:
                console.print(f"[yellow]Would modify {file_path}[/yellow]")
            return True

        # Ensure parent directory exists
        current_file.parent.mkdir(parents=True, exist_ok=True)

        # Write the target content
        current_file.write_text(target_content, encoding="utf-8")

        action = change_info["action"]
        if action == "create":
            console.print(f"[green]Created {file_path}[/green]")
        else:
            console.print(f"[blue]Restored {file_path}[/blue]")

        return True

    except Exception as e:
        console.print(
            f"[red]Error restoring {change_info.get('file_path', 'unknown')}: {e}[/red]"
        )
        return False


def _revert_using_git_native_approach(
    claude_repo, commit_hash: str, dry_run: bool, interactive: bool
) -> int:
    """Revert by restoring to the parent commit state (git-native approach)."""
    try:
        # Get the parent commit of the commit we're reverting
        parent_commits = (
            claude_repo.run_git_command(
                ["rev-list", "--parents", "-n", "1", commit_hash]
            )
            .strip()
            .split()
        )

        if len(parent_commits) < 2:
            console.print(
                f"[yellow]Cannot find parent commit for {commit_hash[:8]} - may be initial commit[/yellow]"
            )
            return 0

        parent_hash = parent_commits[1]  # First parent
        console.print(f"[dim]Reverting to parent state: {parent_hash[:8]}[/dim]")

        # Get files that differ between parent and the commit we're reverting
        current_files = _get_files_at_commit(claude_repo, commit_hash)
        parent_files = _get_files_at_commit(claude_repo, parent_hash)

        changes_to_apply = []

        # Find files that were added or modified in the commit we're reverting
        for file_path, commit_content in current_files.items():
            current_file = claude_repo.project_root / file_path

            if file_path in parent_files:
                # File was modified - restore to parent version
                parent_content = parent_files[file_path]
                if commit_content != parent_content:
                    current_content = ""
                    if current_file.exists():
                        with contextlib.suppress(Exception):
                            current_content = current_file.read_text(encoding="utf-8")

                    if current_content != parent_content:
                        change_info = {
                            "file_path": file_path,
                            "action": "restore_to_parent",
                            "target_content": parent_content,
                        }

                        if interactive:
                            console.print(
                                f"\n[bold]Revert {file_path} to parent state?[/bold]"
                            )
                            console.print(
                                f"  [dim]Current: {len(current_content)} chars[/dim]"
                            )
                            console.print(
                                f"  [dim]Parent:  {len(parent_content)} chars[/dim]"
                            )
                            if click.confirm("Revert this file?", default=True):
                                changes_to_apply.append(change_info)
                        else:
                            changes_to_apply.append(change_info)
            else:
                # File was added in the commit we're reverting - cannot safely delete user files
                if current_file.exists():
                    console.print(
                        f"[yellow]Cannot safely delete {file_path} (user may have modified it)[/yellow]"
                    )

        # Apply the changes
        reverted_count = 0

        # Restore modified files
        for change in changes_to_apply:
            if _apply_git_native_revert_change(
                change, dry_run, claude_repo.project_root
            ):
                reverted_count += 1

        # Note: We don't delete files that were added in reverted commits
        # because user may have modified them. Only modify existing tracked files.

        return reverted_count

    except Exception as e:
        console.print(f"[red]Error in git-native revert: {e}[/red]")
        return 0


def _apply_git_native_revert_change(
    change_info: Dict, dry_run: bool, project_root: Path
) -> bool:
    """Apply a git-native revert change."""
    try:
        file_path = change_info["file_path"]
        target_content = change_info["target_content"]
        current_file = project_root / file_path

        if dry_run:
            console.print(f"[yellow]Would revert {file_path} to parent state[/yellow]")
            return True

        # Write the parent content
        current_file.write_text(target_content, encoding="utf-8")
        console.print(f"[blue]Reverted {file_path} to parent state[/blue]")
        return True

    except Exception as e:
        console.print(
            f"[red]Error reverting {change_info.get('file_path', 'unknown')}: {e}[/red]"
        )
        return False


def _apply_git_native_restore_change(
    change_info: Dict, dry_run: bool, claude_repo
) -> bool:
    """Apply a git-native restore change for exact file state matching."""
    try:
        file_path = change_info["file_path"]
        target_content = change_info["target_content"]
        current_file = claude_repo.project_root / file_path

        if dry_run:
            action = change_info["action"]
            if action == "create":
                console.print(f"[green]Would create {file_path}[/green]")
            else:
                console.print(f"[yellow]Would restore {file_path}[/yellow]")
            return True

        # Ensure parent directory exists
        current_file.parent.mkdir(parents=True, exist_ok=True)

        # Write the target content with exact binary match
        if isinstance(target_content, str):
            current_file.write_text(target_content, encoding="utf-8", newline="\n")
        else:
            current_file.write_bytes(target_content)

        action = change_info["action"]
        if action == "create":
            console.print(f"[green]Created {file_path}[/green]")
        else:
            console.print(f"[blue]Restored {file_path}[/blue]")

        return True

    except Exception as e:
        console.print(
            f"[red]Error restoring {change_info.get('file_path', 'unknown')}: {e}[/red]"
        )
        return False


def _track_revert(claude_repo, commit_hash: str):
    """Track a revert operation for easy restore navigation."""
    try:
        from datetime import datetime

        revert_history_file = claude_repo.claude_git_dir / "revert_history.json"

        # Load existing history
        history = []
        if revert_history_file.exists():
            try:
                history = json.loads(revert_history_file.read_text())
            except Exception:
                history = []

        # Add new revert entry
        revert_entry = {
            "commit_hash": commit_hash,
            "reverted_at": datetime.now().isoformat(),
            "parent_repo_hash": claude_repo._get_parent_repo_hash(),
            "restore_command": f"claude-git restore {commit_hash}",
        }

        # Keep only last 20 reverts to avoid bloat
        history.insert(0, revert_entry)
        history = history[:20]

        # Save history
        revert_history_file.write_text(json.dumps(history, indent=2))

    except Exception as e:
        console.print(f"[yellow]Warning: Could not track revert: {e}[/yellow]")


def _show_revert_status(claude_repo):
    """Show revert history and restore navigation options."""
    revert_history_file = claude_repo.claude_git_dir / "revert_history.json"

    if not revert_history_file.exists():
        console.print("[yellow]No revert history found.[/yellow]")
        console.print(
            "Revert some changes first, then use 'claude-git revert --status' to see restore options."
        )
        return

    try:
        history = json.loads(revert_history_file.read_text())

        if not history:
            console.print("[yellow]No revert history found.[/yellow]")
            return

        console.print("[bold cyan]Claude Git Revert History[/bold cyan]")
        console.print(
            "[dim]Recent reverts (newest first). Use these commands to restore to previous states:[/dim]\n"
        )

        for i, entry in enumerate(history):
            commit_hash = entry["commit_hash"]
            reverted_at = entry.get("reverted_at", "unknown")
            restore_cmd = entry.get(
                "restore_command", f"claude-git restore {commit_hash}"
            )

            # Format timestamp
            try:
                from datetime import datetime

                dt = datetime.fromisoformat(reverted_at.replace("Z", "+00:00"))
                time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                time_str = reverted_at

            # Show commit info
            try:
                # Get commit message from claude-git log
                result = claude_repo.run_git_command(
                    ["show", "--format=%s", "--no-patch", commit_hash]
                )
                commit_msg = result.strip() if result else "No message"
            except:
                commit_msg = "Unknown commit"

            console.print(
                f"[dim]{i + 1:2}.[/dim] [bold yellow]{commit_hash[:8]}[/bold yellow] - {commit_msg[:60]}"
            )
            console.print(f"    [dim]Reverted: {time_str}[/dim]")
            console.print(f"    [green]Restore: {restore_cmd}[/green]")
            if i < len(history) - 1:  # Don't add newline after last entry
                console.print()

        console.print(
            f"\n[dim]Showing {len(history)} recent reverts. Use the restore commands above to return to previous states.[/dim]"
        )

    except Exception as e:
        console.print(f"[red]Error reading revert history: {e}[/red]")


@main.group("hooks")
def hooks():
    """Manage hooks for claude-git integration."""


@hooks.group("claude")
def claude_hooks():
    """Manage Claude Code hooks."""


@hooks.group("git")
def git_hooks():
    """Manage git repository hooks."""


@claude_hooks.command("install")
@click.option(
    "--force", is_flag=True, help="Overwrite existing hooks without prompting"
)
def install_claude_hooks(force: bool):
    """Install Claude Code hooks for automatic session tracking."""
    try:
        claude_dir = Path.home() / ".claude"
        hooks_dir = claude_dir / "hooks"
        settings_file = claude_dir / "settings.json"

        # Create hooks directory if it doesn't exist
        hooks_dir.mkdir(parents=True, exist_ok=True)

        # Define hook files to create
        project_root = _find_project_root()
        if not project_root:
            return

        project_root / "src" / "claude_git" / "hooks"

        hooks_to_install = [
            ("session_start.sh", _get_session_start_hook_content()),
            ("session_end.sh", _get_session_end_hook_content()),
        ]

        console.print("[bold]Installing Claude Code hooks...[/bold]")

        # Install hook files
        for hook_name, hook_content in hooks_to_install:
            hook_file = hooks_dir / hook_name

            if hook_file.exists() and not force:
                existing_content = hook_file.read_text()
                if existing_content.strip() != hook_content.strip():
                    if not click.confirm(
                        f"Hook {hook_name} exists with different content. Overwrite?"
                    ):
                        console.print(f"[yellow]Skipped {hook_name}[/yellow]")
                        continue

            hook_file.write_text(hook_content)
            hook_file.chmod(0o755)  # Make executable
            console.print(f"[green]✅ Installed {hook_name}[/green]")

        # Update Claude Code settings
        _update_claude_settings(settings_file, force)

        console.print(
            "[bold green]✅ Claude Code hooks installed successfully![/bold green]"
        )
        console.print(
            "[dim]Hooks will trigger automatically during Claude Code sessions[/dim]"
        )

    except Exception as e:
        console.print(f"[red]Error installing Claude hooks: {e}[/red]")
        raise click.Abort()


@claude_hooks.command("uninstall")
@click.option(
    "--keep-settings", is_flag=True, help="Keep hook configuration in settings.json"
)
def uninstall_claude_hooks(keep_settings: bool):
    """Uninstall Claude Code hooks."""
    try:
        claude_dir = Path.home() / ".claude"
        hooks_dir = claude_dir / "hooks"
        settings_file = claude_dir / "settings.json"

        hooks_to_remove = ["session_start.sh", "session_end.sh"]

        console.print("[bold]Uninstalling Claude Code hooks...[/bold]")

        for hook_name in hooks_to_remove:
            hook_file = hooks_dir / hook_name
            if hook_file.exists():
                hook_file.unlink()
                console.print(f"[green]✅ Removed {hook_name}[/green]")
            else:
                console.print(f"[dim]Hook {hook_name} not found[/dim]")

        if not keep_settings and settings_file.exists():
            _remove_claude_hooks_from_settings(settings_file)

        console.print("[bold green]✅ Claude Code hooks uninstalled![/bold green]")

    except Exception as e:
        console.print(f"[red]Error uninstalling Claude hooks: {e}[/red]")
        raise click.Abort()


@git_hooks.command("install")
@click.option(
    "--force", is_flag=True, help="Overwrite existing git hooks without prompting"
)
def install_git_hooks(force: bool):
    """Install git hooks for automatic user change detection."""
    project_root = _find_project_root()
    if not project_root:
        return

    try:
        git_hooks_dir = project_root / ".git" / "hooks"
        if not git_hooks_dir.exists():
            console.print("[red]Error: Not in a git repository[/red]")
            return

        console.print("[bold]Installing git hooks...[/bold]")

        # Git hooks to install
        hooks_to_install = [
            ("post-commit", _get_post_commit_hook_content()),
            ("post-merge", _get_post_merge_hook_content()),
        ]

        for hook_name, hook_content in hooks_to_install:
            hook_file = git_hooks_dir / hook_name

            if hook_file.exists() and not force:
                existing_content = hook_file.read_text()
                if "claude-git" not in existing_content:
                    if not click.confirm(
                        f"Git hook {hook_name} exists. Add claude-git integration?"
                    ):
                        console.print(f"[yellow]Skipped {hook_name}[/yellow]")
                        continue
                    # Append to existing hook
                    hook_content = existing_content + "\n\n" + hook_content
                elif existing_content.strip() != hook_content.strip():
                    if not click.confirm(
                        f"Git hook {hook_name} exists with different claude-git content. Overwrite?"
                    ):
                        console.print(f"[yellow]Skipped {hook_name}[/yellow]")
                        continue

            hook_file.write_text(hook_content)
            hook_file.chmod(0o755)  # Make executable
            console.print(f"[green]✅ Installed {hook_name}[/green]")

        console.print("[bold green]✅ Git hooks installed successfully![/bold green]")
        console.print("[dim]Git hooks will detect user changes automatically[/dim]")

    except Exception as e:
        console.print(f"[red]Error installing git hooks: {e}[/red]")
        raise click.Abort()


@git_hooks.command("uninstall")
def uninstall_git_hooks():
    """Uninstall claude-git integration from git hooks."""
    project_root = _find_project_root()
    if not project_root:
        return

    try:
        git_hooks_dir = project_root / ".git" / "hooks"
        if not git_hooks_dir.exists():
            console.print("[red]Error: Not in a git repository[/red]")
            return

        console.print("[bold]Uninstalling git hooks...[/bold]")

        hooks_to_clean = ["post-commit", "post-merge"]

        for hook_name in hooks_to_clean:
            hook_file = git_hooks_dir / hook_name
            if hook_file.exists():
                content = hook_file.read_text()
                if "claude-git" in content:
                    # Remove claude-git sections
                    lines = content.split("\n")
                    filtered_lines = []
                    skip_claude_git = False

                    for line in lines:
                        if "# Claude-git integration" in line:
                            skip_claude_git = True
                            continue
                        if skip_claude_git and (
                            line.strip() == "" or line.startswith("#")
                        ):
                            continue
                        if skip_claude_git and not line.startswith(" "):
                            skip_claude_git = False

                        if not skip_claude_git:
                            filtered_lines.append(line)

                    new_content = "\n".join(filtered_lines).strip()

                    if new_content:
                        hook_file.write_text(new_content)
                        console.print(
                            f"[green]✅ Cleaned claude-git from {hook_name}[/green]"
                        )
                    else:
                        hook_file.unlink()
                        console.print(f"[green]✅ Removed empty {hook_name}[/green]")
                else:
                    console.print(
                        f"[dim]No claude-git integration found in {hook_name}[/dim]"
                    )
            else:
                console.print(f"[dim]Git hook {hook_name} not found[/dim]")

        console.print("[bold green]✅ Git hooks cleaned![/bold green]")

    except Exception as e:
        console.print(f"[red]Error uninstalling git hooks: {e}[/red]")
        raise click.Abort()


def _get_session_start_hook_content() -> str:
    """Get the content for session_start.sh hook."""
    return """#!/bin/bash
# Claude Code Session Start Hook - Initialize claude-git session
# Called when Claude Code session starts

PROJECT_ROOT=$(pwd)

# Check if this is a claude-git project
if [ ! -d ".claude-git" ]; then
    # Not a claude-git project, skip silently
    exit 0
fi

echo "🚀 Starting Claude Code session - initializing claude-git tracking..."

# Get current main repo commit for session context
MAIN_REPO_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
SESSION_ID="session-$(echo $MAIN_REPO_COMMIT | cut -c1-7)"

echo "📋 Session ID: $SESSION_ID"
echo "📍 Main repo commit: $MAIN_REPO_COMMIT"

# Initialize session in claude-git
cd "$PROJECT_ROOT"
python -m claude_git.cli.main session-start \\
  --session-id="$SESSION_ID" \\
  --main-repo-commit="$MAIN_REPO_COMMIT" \\
  2>/dev/null || echo "⚠️  Warning: claude-git session-start failed"

echo "✅ Claude session initialized"
"""


def _get_session_end_hook_content() -> str:
    """Get the content for session_end.sh hook."""
    return """#!/bin/bash
# Claude Code Session End Hook - Create commit with thinking text and changes
# Called when Claude Code session ends
# $1 = path to transcript file (provided by Claude Code)

TRANSCRIPT_PATH="$1"
PROJECT_ROOT=$(pwd)

# Check if this is a claude-git project
if [ ! -d ".claude-git" ]; then
    # Not a claude-git project, skip silently
    exit 0
fi

echo "🔄 Ending Claude Code session - creating commit with thinking text..."

# Get current main repo commit
MAIN_REPO_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo "unknown")

# Create session commit with thinking text extracted from transcript
cd "$PROJECT_ROOT"

if [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ]; then
    echo "📋 Extracting thinking text from transcript: $TRANSCRIPT_PATH"

    # Use python module to create session commit with thinking extraction
    python -m claude_git.cli.main session-end \\
      --transcript="$TRANSCRIPT_PATH" \\
      --main-repo-commit="$MAIN_REPO_COMMIT" \\
      2>/dev/null || {
        echo "⚠️  Warning: claude-git session-end failed, creating basic commit..."

        # Fallback: create basic commit without thinking extraction
        python -m claude_git.cli.main session-end \\
          --main-repo-commit="$MAIN_REPO_COMMIT" \\
          2>/dev/null || echo "❌ Could not create session commit"
    }
else
    echo "⚠️  No transcript provided, creating basic session commit..."
    python -m claude_git.cli.main session-end \\
      --main-repo-commit="$MAIN_REPO_COMMIT" \\
      2>/dev/null || echo "❌ Could not create session commit"
fi

echo "✅ Claude session ended - changes committed to .claude-git"
"""


def _get_post_commit_hook_content() -> str:
    """Get the content for post-commit git hook."""
    return """# Claude-git integration - detect user commits
if [ -d ".claude-git" ]; then
    echo "📝 User commit detected - syncing to claude-git..."
    python -m claude_git.cli.main sync-user-changes 2>/dev/null || true
fi
"""


def _get_post_merge_hook_content() -> str:
    """Get the content for post-merge git hook."""
    return """# Claude-git integration - detect user merges
if [ -d ".claude-git" ]; then
    echo "🔀 User merge detected - syncing to claude-git..."
    python -m claude_git.cli.main sync-user-changes 2>/dev/null || true
fi
"""


def _update_claude_settings(settings_file: Path, force: bool) -> None:
    """Update Claude Code settings to include hook configuration."""
    import json

    settings = {}
    if settings_file.exists():
        settings = json.loads(settings_file.read_text())

    hooks_config = {
        "SessionStart": [
            {
                "matcher": ".*",
                "hooks": [
                    {
                        "type": "command",
                        "command": str(
                            Path.home() / ".claude" / "hooks" / "session_start.sh"
                        ),
                    }
                ],
            }
        ],
        "SessionEnd": [
            {
                "matcher": ".*",
                "hooks": [
                    {
                        "type": "command",
                        "command": str(
                            Path.home() / ".claude" / "hooks" / "session_end.sh"
                        ),
                    }
                ],
            }
        ],
        "Stop": [
            {
                "matcher": ".*",
                "hooks": [
                    {
                        "type": "command",
                        "command": str(
                            Path.home() / ".claude" / "hooks" / "session_end.sh"
                        ),
                    }
                ],
            }
        ],
        "PostToolUse": [
            {
                "matcher": "(Edit|Write|MultiEdit)",
                "hooks": [
                    {
                        "type": "command",
                        "command": f'python3 "{_find_project_root() / "src" / "claude_git" / "hooks" / "capture.py"}"',
                    }
                ],
            }
        ],
    }

    # Update hooks configuration
    if "hooks" not in settings:
        settings["hooks"] = {}

    for hook_type, hook_config in hooks_config.items():
        if hook_type in settings["hooks"]:
            # Hook type already exists - ADD to existing hooks instead of replacing
            existing_hooks = settings["hooks"][hook_type]

            # Extract the command from our new hook config
            new_hook_command = hook_config[0]["hooks"][0]["command"]

            # Check if our hook is already installed by searching ALL hooks at ANY index
            already_installed = False
            for hook_config_item in existing_hooks:
                for hook in hook_config_item.get("hooks", []):
                    if hook.get("command") == new_hook_command:
                        already_installed = True
                        break
                if already_installed:
                    break

            if not already_installed:
                if not force and not click.confirm(
                    f"Add claude-git hook to existing {hook_type} hooks?"
                ):
                    console.print(f"[yellow]⚠️ Skipped {hook_type} hook[/yellow]")
                    continue
                # Add our hook to the existing hooks
                existing_hooks.extend(hook_config)
                console.print(
                    f"[green]✅ Added claude-git hook to existing {hook_type} hooks[/green]"
                )
            else:
                console.print(
                    f"[yellow]⚠️ Claude-git {hook_type} hook already installed[/yellow]"
                )
        else:
            # Hook type doesn't exist - create it
            settings["hooks"][hook_type] = hook_config
            console.print(f"[green]✅ Added {hook_type} hook configuration[/green]")

    # Write updated settings
    settings_file.write_text(json.dumps(settings, indent=2))
    console.print("[green]✅ Updated Claude Code settings[/green]")


def _remove_claude_hooks_from_settings(settings_file: Path) -> None:
    """Remove claude-git hooks from Claude Code settings."""
    import json

    if not settings_file.exists():
        return

    settings = json.loads(settings_file.read_text())

    if "hooks" in settings:
        hooks_to_remove = ["SessionStart", "SessionEnd", "PostToolUse"]
        for hook_type in hooks_to_remove:
            if hook_type in settings["hooks"]:
                del settings["hooks"][hook_type]
                console.print(f"[green]✅ Removed {hook_type} from settings[/green]")

    settings_file.write_text(json.dumps(settings, indent=2))
    console.print("[green]✅ Cleaned Claude Code settings[/green]")


@main.command("sync-user-changes")
def sync_user_changes():
    """Sync user changes from main repo to claude-git repo (called by git hooks)."""
    project_root = _find_project_root()
    if not project_root:
        return

    git_native_repo = get_git_native_repo_or_exit(project_root)

    try:
        # Get the latest main repo commit
        main_commit = git_native_repo._get_main_repo_commit()
        console.print(
            f"[green]📁 Syncing user changes from commit: {main_commit[:8]}[/green]"
        )

        # Perform initial file sync to copy all files from main repo
        git_native_repo._initial_file_sync()
        console.print("[green]✅ User changes synced to claude-git[/green]")

    except Exception as e:
        console.print(f"[red]⚠️  Failed to sync user changes: {e}[/red]")


@main.command("session-start")
@click.option("--session-id", type=str, help="Unique session identifier")
@click.option(
    "--main-repo-commit",
    type=str,
    required=True,
    help="Current commit hash of main repository",
)
def session_start(session_id: Optional[str], main_repo_commit: str):
    """Initialize a Claude Code session for change tracking."""
    project_root = _find_project_root()
    if not project_root:
        return

    git_native_repo = get_git_native_repo_or_exit(project_root)

    if not session_id:
        session_id = f"session-{main_repo_commit[:7]}"

    console.print(f"[green]🚀 Starting Claude session: {session_id}[/green]")
    console.print(f"[dim]Main repo commit: {main_repo_commit}[/dim]")
    console.print(f"[dim]Project: {project_root}[/dim]")

    # Initialize session tracking (this just acknowledges the session start)
    # The actual accumulation happens via PostToolUse hooks
    git_native_repo._session_active = True
    console.print("[green]✅ Claude session tracking initialized[/green]")


@main.command("session-end")
@click.option(
    "--transcript",
    type=click.Path(exists=True),
    help="Path to Claude Code transcript file",
)
@click.option(
    "--main-repo-commit",
    type=str,
    required=True,
    help="Current commit hash of main repository",
)
def session_end(transcript: Optional[str], main_repo_commit: str):
    """Create commit with thinking text extracted from transcript."""
    project_root = _find_project_root()
    if not project_root:
        return

    git_native_repo = get_git_native_repo_or_exit(project_root)

    try:
        session_id = f"session-{main_repo_commit[:7]}"
        console.print(f"[green]✅ Ending Claude session: {session_id}[/green]")

        # Extract thinking text from transcript if provided
        thinking_text = ""
        conversation_history = []

        if transcript:
            console.print(f"[dim]Extracting thinking from: {transcript}[/dim]")
            thinking_text, conversation_history = _extract_thinking_from_transcript(
                transcript
            )

        # Accumulate current changes if not already in session
        if not git_native_repo._session_active:
            git_native_repo.session_start(session_id=session_id, use_branching=False)

            # Detect and accumulate recent file changes
            _accumulate_recent_changes(git_native_repo, main_repo_commit)

        # Create actual session commit with conversation history
        commit_hash = git_native_repo.session_end(thinking_text=thinking_text)

        if commit_hash and conversation_history:
            # Add conversation history to git notes
            _add_conversation_to_git_notes(
                git_native_repo.claude_git_dir,
                commit_hash,
                conversation_history,
                main_repo_commit,
                session_id,
            )
            console.print(
                f"[green]✅ Session commit created: {commit_hash[:8]} (with conversation history)[/green]"
            )
        elif commit_hash:
            console.print(
                f"[green]✅ Session commit created: {commit_hash[:8]}[/green]"
            )
        else:
            console.print("[yellow]⚠️  No changes to commit[/yellow]")

    except Exception as e:
        console.print(f"[red]Error ending session: {e}[/red]")
        raise click.Abort() from e


def _extract_thinking_from_transcript(transcript_path: str) -> tuple[str, list]:
    """Extract Claude's thinking text and conversation from transcript file."""
    thinking_messages = []
    conversation = []

    try:
        with open(transcript_path) as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)

                    # Extract conversation
                    if data.get("type") == "message":
                        role = data.get("role")
                        content_items = data.get("content", [])

                        for item in content_items:
                            if item.get("type") == "text":
                                text_content = item.get("text", "")
                                is_thinking = data.get("thinking", False)

                                conversation.append(
                                    {
                                        "role": role,
                                        "content": text_content,
                                        "thinking": is_thinking,
                                    }
                                )

                                # Extract thinking specifically
                                if is_thinking and role == "assistant":
                                    thinking_messages.append(text_content)

    except Exception as e:
        print(f"Error parsing transcript: {e}")
        return "", []

    # Process thinking messages into commit-friendly text
    thinking_text = _process_thinking_messages(thinking_messages)
    return thinking_text, conversation


def _add_conversation_to_git_notes(
    claude_git_dir: Path,
    commit_hash: str,
    conversation: list,
    main_repo_commit: str,
    session_id: str,
) -> None:
    """Add full conversation history to git notes for the commit."""
    try:
        # Format conversation for human readability
        formatted_conversation = _format_conversation_for_display(conversation)

        # Create structured git notes content
        notes_content = f"""=== CLAUDE SESSION SUMMARY ===
Session: {session_id}
Main-Repo: {main_repo_commit}
Timestamp: {datetime.now().isoformat()}

{formatted_conversation}

=== END CONVERSATION ==="""

        # Add to git notes
        result = subprocess.run(
            ["git", "notes", "add", "-m", notes_content, commit_hash],
            cwd=claude_git_dir,
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            print(
                f"✅ Added conversation history to git notes ({len(conversation)} messages)"
            )
        else:
            print(f"⚠️  Warning: Failed to add git notes: {result.stderr}")

    except Exception as e:
        print(f"❌ Error adding conversation to git notes: {e}")


def _accumulate_recent_changes(git_native_repo, main_repo_commit: str) -> None:
    """Only accumulate changes that Claude made via explicit tool use."""
    print("📝 Session-end only processes tool use changes (no auto-generated files)")

    # During session end, we should only commit changes that were explicitly
    # accumulated via tool use (Write, Edit, MultiEdit, Delete).
    # The _accumulated_changes list already contains only these explicit changes.

    # If no session was active, we don't try to detect/accumulate anything
    # because we only want to track explicit Claude tool use
    if len(git_native_repo._accumulated_changes) == 0:
        print("ℹ️  No tool use changes to accumulate")
        return

    print(f"📝 Using {len(git_native_repo._accumulated_changes)} changes from tool use")

    # Handle any file deletions that might have happened
    _handle_deleted_files(git_native_repo)


def _handle_deleted_files(git_native_repo) -> None:
    """Handle files that were deleted by Claude and should be removed from claude-git repo."""
    try:
        # Check if any previously tracked files are now missing
        result = subprocess.run(
            ["git", "ls-files"],
            capture_output=True,
            text=True,
            cwd=str(git_native_repo.project_root),
        )

        if result.returncode != 0:
            return

        # Check each tracked file to see if it still exists
        for tracked_file in result.stdout.strip().split("\n"):
            if not tracked_file.strip():
                continue

            file_path = git_native_repo.project_root / tracked_file
            claude_file_path = git_native_repo.claude_git_dir / tracked_file

            # If file was deleted from main repo but still exists in claude-git
            if not file_path.exists() and claude_file_path.exists():
                print(f"🗑️  Removing deleted file from claude-git: {tracked_file}")

                # Remove from claude-git repo
                try:
                    git_native_repo.claude_repo.index.remove([tracked_file])

                    # Accumulate the deletion
                    git_native_repo.accumulate_change(
                        file_path=tracked_file,
                        tool_name="Delete",
                        tool_input={"file_path": tracked_file, "deleted": True},
                    )
                except Exception as e:
                    print(f"⚠️  Could not remove {tracked_file}: {e}")

    except Exception as e:
        print(f"⚠️  Error handling deleted files: {e}")


def _format_conversation_for_display(conversation: list) -> str:
    """Format conversation history in a readable way for git notes display."""
    if not conversation:
        return "No conversation history available"

    formatted_lines = []
    formatted_lines.append("=== CONVERSATION HISTORY ===")
    formatted_lines.append("")

    for i, message in enumerate(conversation, 1):
        role = message.get("role", "unknown")
        content = message.get("content", "")

        # Create readable role prefix
        if role == "user":
            prefix = f"[{i}] 👤 USER:"
        elif role == "assistant":
            if message.get("thinking", False):
                prefix = f"[{i}] 🧠 CLAUDE (thinking):"
            else:
                prefix = f"[{i}] 🤖 CLAUDE:"
        else:
            prefix = f"[{i}] {role.upper()}:"

        formatted_lines.append(prefix)
        formatted_lines.append("")

        # Add content with proper indentation
        if content:
            content_lines = content.strip().split("\n")
            for line in content_lines:
                if line.strip():
                    formatted_lines.append(f"    {line}")
                else:
                    formatted_lines.append("")

        formatted_lines.append("")

    return "\n".join(formatted_lines)


def _process_thinking_messages(thinking_messages: list) -> str:
    """Process thinking messages into readable commit message text."""
    if not thinking_messages:
        return "Claude session work"

    # Remove duplicates while preserving order
    unique_thoughts = []
    seen = set()
    for thought in thinking_messages:
        if (
            thought not in seen and len(thought.strip()) > 10
        ):  # Filter out very short thoughts
            unique_thoughts.append(thought.strip())
            seen.add(thought)

    # Join with proper formatting for git commit message
    if unique_thoughts:
        # Limit to prevent extremely long commit messages
        selected_thoughts = unique_thoughts[:3]  # Top 3 most important thoughts
        return "\n\n".join(selected_thoughts)
    return "Claude session work (thinking text filtered)"


def _find_project_root() -> Optional[Path]:
    """Find the project root directory."""
    current_dir = Path.cwd()

    for parent in [current_dir] + list(current_dir.parents):
        if (parent / ".git").exists():
            return parent

    console.print("[red]Error: Not in a git repository[/red]")
    return None


if __name__ == "__main__":
    main()
