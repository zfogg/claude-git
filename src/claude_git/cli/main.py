"""Main CLI interface for Claude Git."""

import json
import os
import shutil
import stat
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax  
from rich.table import Table
from rich.text import Text

from claude_git.core.repository import ClaudeGitRepository

console = Console()

@click.group()
@click.version_option()
def main():
    """Claude Git - Parallel version control for AI changes."""
    pass


@main.command()
@click.option("--project-path", type=click.Path(exists=True), default=".",
              help="Path to project directory")
def init(project_path: str):
    """Initialize Claude Git in a project."""
    project_root = Path(project_path).resolve()

    if not (project_root / ".git").exists():
        console.print("[red]Error: Not a git repository[/red]")
        raise click.Abort()

    claude_repo = ClaudeGitRepository(project_root)

    if claude_repo.exists():
        console.print("[yellow]Claude Git already initialized in this project[/yellow]")
        return

    claude_repo.init()
    console.print(f"[green]✅ Initialized Claude Git in {project_root}[/green]")


@main.command()
def status():
    """Show Claude Git status."""
    project_root = _find_project_root()
    if not project_root:
        return

    claude_repo = ClaudeGitRepository(project_root)
    if not claude_repo.exists():
        console.print("[red]Claude Git not initialized. Run 'claude-git init' first.[/red]")
        return

    sessions = claude_repo.list_sessions()
    active_sessions = [s for s in sessions if s.is_active]

    console.print(f"[bold]Project:[/bold] {project_root}")
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

    claude_repo = ClaudeGitRepository(project_root)
    if not claude_repo.exists():
        console.print("[red]Claude Git not initialized. Run 'claude-git init' first.[/red]")
        return

    try:
        args = ["log", f"--max-count={limit}"]
        if oneline:
            args.append("--oneline")

        # Use pager-aware command for log output
        claude_repo.run_git_command_with_pager(args)
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")


@main.command()
@click.option("--limit", default=10, help="Number of recent changes to analyze")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed diff output")
def diff(limit: int, verbose: bool):
    """Show meaningful diff of Claude's changes vs current file state."""
    project_root = _find_project_root()
    if not project_root:
        return

    claude_repo = ClaudeGitRepository(project_root)
    if not claude_repo.exists():
        console.print("[red]Claude Git not initialized. Run 'claude-git init' first.[/red]")
        return

    try:
        # Get meaningful diff analysis
        diff_results = claude_repo.get_meaningful_diff(limit)
        
        if not diff_results["changes_analyzed"]:
            console.print("[yellow]No Claude changes found to analyze[/yellow]")
            return
            
        # Print summary
        summary = diff_results["summary"]
        console.print(f"\n[bold]Claude Changes Analysis[/bold] (last {summary['total_claude_changes']} changes)\n")
        
        # Summary table
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Status")
        table.add_column("Count", style="bold")
        table.add_column("Description")
        
        table.add_row("✅ Intact", str(summary['claude_changes_intact']), "Claude's changes are preserved")
        table.add_row("📝 Modified", str(summary['user_modified_after_claude']), "Files changed since Claude")
        table.add_row("⚠️  Conflicts", str(summary['conflicts']), "Changes that may conflict")
        
        console.print(table)
        console.print()
        
        # Show detailed analysis for each change
        for change in diff_results["changes_analyzed"]:
            status_color = {
                "unchanged": "green",
                "user_modified": "yellow", 
                "file_not_found": "red",
                "error": "red"
            }.get(change["status"], "white")
            
            status_icon = {
                "unchanged": "✅",
                "user_modified": "📝",
                "file_not_found": "❌",
                "error": "💥"
            }.get(change["status"], "❓")
            
            console.print(f"[bold {status_color}]{status_icon} {change['file_path']}[/bold {status_color}]")
            console.print(f"   [dim]Commit: {change['commit_hash']} - {change['commit_message']}[/dim]")
            
            # Show revert information
            revert_info = change.get("revert_info", {})
            if revert_info.get("can_revert", False):
                confidence_color = {"high": "green", "medium": "yellow", "low": "red"}.get(
                    revert_info.get("confidence", "low"), "white"
                )
                console.print(f"   [bold {confidence_color}]🔄 Can revert ({revert_info['confidence']} confidence)[/bold {confidence_color}]")
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
        console.print("[red]Claude Git not initialized. Run 'claude-git init' first.[/red]")
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
            if duration_sec:
                duration = f"{duration_sec/60:.0f}m"
            else:
                duration = "Unknown"
            status = "⚫ Ended"

        # Get change count from session's tracked commit IDs
        change_count = str(len(session.change_ids))

        table.add_row(session_id_short, branch_name, start_time, duration, change_count, status)

    console.print(table)


@main.command(context_settings=dict(ignore_unknown_options=True))
@click.argument("git_args", nargs=-1, type=click.UNPROCESSED)
def git(git_args):
    """Run git commands on the Claude repository."""
    project_root = _find_project_root()
    if not project_root:
        return

    claude_repo = ClaudeGitRepository(project_root)
    if not claude_repo.exists():
        console.print("[red]Claude Git not initialized. Run 'claude-git init' first.[/red]")
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
        console.print("[red]Claude Git not initialized. Run 'claude-git init' first.[/red]")
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
                json_files = [f for f in commit.tree.traverse() if f.name.endswith('.json')]
                if json_files:
                    import json
                    change_data = json.loads(json_files[0].data_stream.read().decode('utf-8'))
                    if 'parent_repo_hash' in change_data and change_data['parent_repo_hash']:
                        console.print(f"\n[bold]Parent repo hash:[/bold] {change_data['parent_repo_hash']}")
                        console.print("[dim]Use this hash to sync changes back to your main repository[/dim]")
            except Exception:
                pass

    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")


@main.command()
def capture():
    """Capture a change from Claude hook (internal command)."""
    # This will be called by the hook
    pass


@main.command()
@click.argument("commit_hash")
@click.option("--dry-run", is_flag=True, help="Show what would be applied without making changes")
def apply(commit_hash: str, dry_run: bool):
    """Apply a Claude change to the main project files."""
    project_root = _find_project_root()
    if not project_root:
        return

    claude_repo = ClaudeGitRepository(project_root)
    if not claude_repo.exists():
        console.print("[red]Claude Git not initialized. Run 'claude-git init' first.[/red]")
        return

    try:
        # Get the patch file for this commit
        commit = claude_repo.repo.commit(commit_hash)
        console.print(f"[bold]Applying commit:[/bold] {commit.hexsha[:8]} - {commit.message.split()[0]}")

        # Find patch files in this commit
        patch_files = [f for f in commit.tree.traverse() if f.name.endswith('.patch')]

        if not patch_files:
            console.print("[red]No patch file found in this commit[/red]")
            return

        for patch_file in patch_files:
            patch_content = patch_file.data_stream.read().decode('utf-8')

            if dry_run:
                console.print(f"\n[bold]Would apply patch:[/bold]")
                console.print(patch_content)
            else:
                console.print(f"[yellow]Manual patch application required:[/yellow]")
                console.print(f"Copy the patch content and apply with: git apply")
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
        console.print("[red]Claude Git not initialized. Run 'claude-git init' first.[/red]")
        return

    try:
        # Get the commit and create reverse patch
        commit = claude_repo.repo.commit(commit_hash)
        console.print(f"[bold]Creating rollback for:[/bold] {commit.hexsha[:8]} - {commit.message.split()[0]}")

        # Find JSON files to get the original change data
        json_files = [f for f in commit.tree.traverse() if f.name.endswith('.json')]

        for json_file in json_files:
            change_data = json.loads(json_file.data_stream.read().decode('utf-8'))

            # Create reverse patch
            if change_data['old_string'] and change_data['new_string']:
                reverse_patch = f"""--- {change_data['file_path']}
+++ {change_data['file_path']}
@@ -1,1 +1,1 @@
-{change_data['new_string']}
+{change_data['old_string']}
"""
                console.print("[bold]Reverse patch to undo this change:[/bold]")
                console.print(reverse_patch)
            else:
                console.print(f"[yellow]Complex change - manual rollback required for {change_data['file_path']}[/yellow]")

    except Exception as e:
        console.print(f"[red]Error creating rollback: {e}[/red]")


@main.command()
@click.argument("parent_hash")
def find_by_parent(parent_hash: str):
    """Find Claude changes made at a specific parent repo hash."""
    project_root = _find_project_root()
    if not project_root:
        return

    claude_repo = ClaudeGitRepository(project_root)
    if not claude_repo.exists():
        console.print("[red]Claude Git not initialized. Run 'claude-git init' first.[/red]")
        return

    try:
        # Search through commits for matching parent hash
        matching_commits = []

        for commit in claude_repo.repo.iter_commits():
            try:
                json_files = [f for f in commit.tree.traverse() 
                             if f.name.endswith('.json') and 'changes/' in str(f.path)]
                for json_file in json_files:
                    try:
                        change_data = json.loads(json_file.data_stream.read().decode('utf-8'))
                        # Skip if not a change record (must have 'id' field)
                        if not change_data.get('id'):
                            continue
                        parent_repo_hash = change_data.get('parent_repo_hash', '')
                        if (parent_repo_hash and parent_repo_hash.startswith(parent_hash)) or parent_hash in commit.message:
                            matching_commits.append((commit, change_data))
                            break
                    except (json.JSONDecodeError, KeyError):
                        continue
            except Exception:
                continue

        if not matching_commits:
            console.print(f"[yellow]No Claude changes found for parent hash: {parent_hash}[/yellow]")
            return

        console.print(f"[bold]Claude changes for parent repo hash {parent_hash}:[/bold]")
        console.print()

        for commit, change_data in matching_commits:
            console.print(f"[cyan]{commit.hexsha[:8]}[/cyan] - {commit.message.split()[0]} {commit.message.split()[1] if len(commit.message.split()) > 1 else ''}")
            console.print(f"  File: {change_data.get('file_path', 'unknown')}")
            console.print(f"  Time: {change_data.get('timestamp', 'unknown')}")
            console.print(f"  Parent: {change_data.get('parent_repo_hash', 'unknown')[:8]}")
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
        console.print("[red]Claude Git not initialized. Run 'claude-git init' first.[/red]")
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
            commit_hashes = result.strip().split('\n') if result.strip() else []
            commits = [claude_repo.repo.commit(h) for h in commit_hashes if h]

        conflicts_found = 0
        
        for commit in commits:
            # Find JSON files in this commit  
            json_files = [f for f in commit.tree.traverse() 
                         if f.name.endswith('.json') and 'changes/' in str(f.path)]
            
            for json_file in json_files:
                try:
                    change_data = json.loads(json_file.data_stream.read().decode('utf-8'))
                    if not change_data.get('id'):  # Skip non-change files
                        continue
                        
                    conflict_analysis = change_data.get('conflict_analysis', {})
                    
                    if conflict_analysis.get('has_conflicts'):
                        conflicts_found += 1
                        
                        console.print(f"\n[bold red]⚠️  Conflict detected in commit {commit.hexsha[:8]}[/bold red]")
                        console.print(f"[bold]File:[/bold] {change_data.get('file_path')}")
                        console.print(f"[bold]Time:[/bold] {change_data.get('timestamp')}")
                        
                        if conflict_analysis.get('same_file_modified'):
                            console.print("[yellow]• Both you and Claude modified the same file[/yellow]")
                            
                        if conflict_analysis.get('related_files_modified'):
                            related_files = ', '.join(conflict_analysis['related_files_modified'])
                            console.print(f"[yellow]• Related files also modified: {related_files}[/yellow]")
                        
                        if conflict_analysis.get('recommendations'):
                            console.print("[bold]Recommendations:[/bold]")
                            for rec in conflict_analysis['recommendations']:
                                console.print(f"  {rec}")
                                
                        # Show human modifications summary
                        human_mods = conflict_analysis.get('human_modifications', [])
                        if human_mods:
                            mod_summary = {}
                            for mod in human_mods:
                                mod_type = mod['type']
                                mod_summary[mod_type] = mod_summary.get(mod_type, 0) + 1
                            
                            summary_parts = [f"{count} {mod_type}" for mod_type, count in mod_summary.items()]
                            console.print(f"[dim]Human changes: {', '.join(summary_parts)}[/dim]")

                except (json.JSONDecodeError, KeyError):
                    continue
                    
        if conflicts_found == 0:
            console.print("[green]✅ No conflicts detected in recent changes[/green]")
        else:
            console.print(f"\n[bold]Found {conflicts_found} potential conflicts[/bold]")
            console.print("[dim]Use 'claude-git resolve <commit-hash>' for resolution assistance[/dim]")
            
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
        console.print("[red]Claude Git not initialized. Run 'claude-git init' first.[/red]")
        return

    try:
        commit = claude_repo.repo.commit(commit_hash)
        console.print(f"[bold]Conflict resolution for commit {commit.hexsha[:8]}[/bold]")
        
        # Find the change data
        json_files = [f for f in commit.tree.traverse() 
                     if f.name.endswith('.json') and 'changes/' in str(f.path)]
        
        if not json_files:
            console.print("[red]No change data found in this commit[/red]")
            return
            
        change_data = json.loads(json_files[0].data_stream.read().decode('utf-8'))
        conflict_analysis = change_data.get('conflict_analysis', {})
        
        if not conflict_analysis.get('has_conflicts'):
            console.print("[green]No conflicts detected for this change[/green]")
            return
            
        console.print(f"\n[bold]Claude's Change:[/bold]")
        console.print(f"File: {change_data.get('file_path')}")
        console.print(f"Type: {change_data.get('change_type')}")
        
        if change_data.get('old_string') and change_data.get('new_string'):
            console.print(f"Changed: '{change_data['old_string']}' → '{change_data['new_string']}'")
            
        console.print(f"\n[bold red]Conflicts Detected:[/bold red]")
        for rec in conflict_analysis.get('recommendations', []):
            console.print(f"• {rec}")
            
        console.print(f"\n[bold]Resolution Options:[/bold]")
        console.print("[green]1.[/green] Review changes manually and apply selectively")
        console.print("[green]2.[/green] Use git merge tools to resolve conflicts")
        console.print("[green]3.[/green] Apply Claude's change and manually fix conflicts")
        console.print("[green]4.[/green] Skip this change and continue with others")
        
        # Show current parent repo status
        current_status = claude_repo._get_parent_repo_status()
        if current_status and current_status.get('has_changes'):
            console.print(f"\n[yellow]⚠️  Parent repository currently has uncommitted changes[/yellow]")
            console.print("[dim]Consider committing or stashing changes before applying Claude's modifications[/dim]")
            
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
        console.print("[red]Claude Git not initialized. Run 'claude-git init' first.[/red]")
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
            commit_hashes = result.strip().split('\n') if result.strip() else []
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
                "high_activity_periods": 0
            },
            "recommendations": [],
            "merge_strategy": None
        }

        human_activity_score = 0
        claude_activity_score = 0
        
        for commit in commits:
            json_files = [f for f in commit.tree.traverse() 
                         if f.name.endswith('.json') and 'changes/' in str(f.path)]
            
            for json_file in json_files:
                try:
                    change_data = json.loads(json_file.data_stream.read().decode('utf-8'))
                    if not change_data.get('id'):
                        continue
                        
                    analysis["total_changes"] += 1
                    claude_activity_score += 1
                    
                    # Track file types
                    file_path = change_data.get('file_path', '')
                    file_ext = Path(file_path).suffix or 'no_extension'
                    analysis["file_types"][file_ext] = analysis["file_types"].get(file_ext, 0) + 1
                    
                    # Track change types
                    change_type = change_data.get('change_type', 'unknown')
                    analysis["change_types"][change_type] = analysis["change_types"].get(change_type, 0) + 1
                    
                    # Analyze conflicts
                    conflict_analysis = change_data.get('conflict_analysis', {})
                    if conflict_analysis.get('has_conflicts'):
                        analysis["conflict_changes"] += 1
                        
                        if conflict_analysis.get('same_file_modified'):
                            analysis["conflict_patterns"]["same_file_conflicts"] += 1
                            
                        if conflict_analysis.get('related_files_modified'):
                            analysis["conflict_patterns"]["related_file_conflicts"] += 1
                            
                        # Count human activity
                        human_mods = conflict_analysis.get('human_modifications', [])
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
        
        console.print(f"\n[bold]📊 Change Analysis Summary[/bold]")
        console.print(f"Total changes: {analysis['total_changes']}")
        console.print(f"Conflicts detected: {analysis['conflict_changes']} ({conflict_ratio:.1%})")
        console.print(f"Human/Claude activity ratio: {human_claude_ratio:.2f}")
        
        # File type analysis
        if analysis["file_types"]:
            console.print(f"\n[bold]📁 File Types Modified[/bold]")
            sorted_types = sorted(analysis["file_types"].items(), key=lambda x: x[1], reverse=True)
            for file_type, count in sorted_types[:5]:
                console.print(f"  {file_type}: {count} changes")
        
        # Determine merge strategy
        if conflict_ratio < 0.1:
            analysis["merge_strategy"] = "safe_auto_merge"
            strategy_desc = "🟢 Safe Auto-Merge"
            strategy_detail = "Low conflict rate - most changes can be applied automatically"
        elif conflict_ratio < 0.3:
            analysis["merge_strategy"] = "selective_merge"  
            strategy_desc = "🟡 Selective Merge"
            strategy_detail = "Moderate conflicts - review each change before applying"
        else:
            analysis["merge_strategy"] = "careful_manual_merge"
            strategy_desc = "🔴 Careful Manual Merge"
            strategy_detail = "High conflict rate - manual review required for all changes"
        
        console.print(f"\n[bold]🎯 Recommended Merge Strategy: {strategy_desc}[/bold]")
        console.print(f"  {strategy_detail}")
        
        # Specific recommendations
        recommendations = []
        
        if analysis["conflict_patterns"]["same_file_conflicts"] > 2:
            recommendations.append("⚠️  Multiple same-file conflicts detected. Consider using git merge tools.")
            
        if analysis["conflict_patterns"]["high_activity_periods"] > 0:
            recommendations.append("📊 High human activity detected. Coordinate changes or use feature branches.")
            
        if human_claude_ratio > 2:
            recommendations.append("👥 Heavy human modification activity. Consider pair programming workflow.")
            
        if analysis["change_types"].get("edit", 0) > analysis["change_types"].get("write", 0) * 3:
            recommendations.append("✏️  Many small edits detected. Consider batching related changes.")
            
        # Workflow recommendations based on file types
        python_files = analysis["file_types"].get(".py", 0)
        js_files = analysis["file_types"].get(".js", 0) + analysis["file_types"].get(".ts", 0)
        
        if python_files > 0:
            recommendations.append("🐍 Python files modified. Run tests before merging changes.")
        if js_files > 0:
            recommendations.append("🟨 JavaScript/TypeScript files modified. Check linting and build.")
            
        if recommendations:
            console.print(f"\n[bold]💡 Intelligent Recommendations[/bold]")
            for i, rec in enumerate(recommendations, 1):
                console.print(f"  {i}. {rec}")
        
        # Next steps
        console.print(f"\n[bold]🚀 Suggested Next Steps[/bold]")
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
    """Set up Claude Code hooks for change tracking."""
    settings_file = Path.home() / ".claude" / "settings.json"
    
    # Find the capture script
    capture_script_path = None
    claude_git_script = shutil.which("claude-git")
    if claude_git_script:
        claude_git_path = Path(claude_git_script).resolve()
        src_dir = claude_git_path.parent.parent / "src"
        capture_script = src_dir / "claude_git" / "hooks" / "capture.py"
        if capture_script.exists():
            capture_script_path = str(capture_script)
    
    if not capture_script_path:
        # Try to find it relative to the module
        try:
            import claude_git.hooks.capture
            capture_script_path = Path(claude_git.hooks.capture.__file__)
        except ImportError:
            console.print("[red]Could not find claude-git capture script.[/red]")
            return

    # Read existing settings
    try:
        if settings_file.exists():
            with settings_file.open() as f:
                settings = json.load(f)
        else:
            settings = {}
    except (json.JSONDecodeError, IOError):
        settings = {}
        
    # Ensure hooks section exists
    if "hooks" not in settings:
        settings["hooks"] = {}
    
    # Add PostToolUse hook for claude-git
    if "PostToolUse" not in settings["hooks"]:
        settings["hooks"]["PostToolUse"] = []
    
    # Create the hook configuration
    claude_git_hook = {
        "matcher": "(Edit|Write|MultiEdit)",
        "hooks": [
            {
                "type": "command",
                "command": f'python3 "{capture_script_path}"'
            }
        ]
    }
    
    # Check if claude-git hook already exists
    existing_hooks = settings["hooks"]["PostToolUse"]
    claude_git_exists = any(
        hook.get("matcher") == "(Edit|Write|MultiEdit)" and 
        any("claude-git" in h.get("command", "") for h in hook.get("hooks", []))
        for hook in existing_hooks
    )
    
    if not claude_git_exists:
        settings["hooks"]["PostToolUse"].append(claude_git_hook)
        
        # Write updated settings
        settings_file.parent.mkdir(exist_ok=True)
        with settings_file.open('w') as f:
            json.dump(settings, f, indent=2)
            
        console.print(f"[green]✅ Hook installed in {settings_file}[/green]")
        console.print("[dim]Claude will now automatically track your changes![/dim]")
    else:
        console.print("[yellow]Claude Git hook already exists in settings[/yellow]")


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
