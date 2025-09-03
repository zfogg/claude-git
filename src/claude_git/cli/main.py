"""Main CLI interface for Claude Git."""

import os
import shutil
import stat
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
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
        
        result = claude_repo.run_git_command(args)
        if result:
            console.print(result)
        else:
            console.print("[yellow]No commits found[/yellow]")
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
        
        changes = claude_repo.list_changes(session.id)
        change_count = str(len(changes))
        
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
        # Use git show command
        args = ["show"]
        if commit_hash:
            args.append(commit_hash)
        
        result = claude_repo.run_git_command(args)
        console.print(result)
        
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
                json_files = [f for f in commit.tree.traverse() if f.name.endswith('.json')]
                for json_file in json_files:
                    change_data = json.loads(json_file.data_stream.read().decode('utf-8'))
                    if (change_data.get('parent_repo_hash', '').startswith(parent_hash) or 
                        parent_hash in commit.message):
                        matching_commits.append((commit, change_data))
                        break
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
def setup_hooks():
    """Set up Claude Code hooks for change tracking."""
    hooks_dir = Path.home() / ".claude" / "hooks"
    hook_script = hooks_dir / "post_tool_use.sh"
    
    # Create hooks directory
    hooks_dir.mkdir(parents=True, exist_ok=True)
    
    # Find the claude-git installation
    claude_git_script = shutil.which("claude-git")
    if not claude_git_script:
        console.print("[red]Could not find claude-git command. Make sure it's installed and in PATH.[/red]")
        return
    
    # Get the directory containing the capture script
    claude_git_path = Path(claude_git_script).resolve()
    src_dir = claude_git_path.parent.parent / "src"
    capture_script = src_dir / "claude_git" / "hooks" / "capture.py"
    
    if not capture_script.exists():
        # Try to find it relative to the module
        import claude_git.hooks.capture
        capture_script = Path(claude_git.hooks.capture.__file__)
    
    # Create the hook script
    hook_content = f"""#!/bin/bash
# Claude Git hook for tracking AI changes
# Generated by claude-git setup-hooks

if [[ "$TOOL_NAME" =~ ^(Edit|Write|MultiEdit)$ ]]; then
    python3 "{capture_script}" "$HOOK_INPUT_JSON"
fi
"""
    
    hook_script.write_text(hook_content)
    
    # Make executable
    current_mode = hook_script.stat().st_mode
    hook_script.chmod(current_mode | stat.S_IEXEC)
    
    console.print(f"[green]✅ Hook installed at {hook_script}[/green]")
    console.print("[dim]Claude will now automatically track your changes![/dim]")


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