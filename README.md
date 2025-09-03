# 🔄 Claude Git - Parallel Version Control for AI Changes

A revolutionary version control system that tracks ONLY Claude-made changes, giving you unprecedented visibility and control over AI-driven development.

## 🎯 Core Concept

Claude Git creates a separate `.claude-git` repository alongside your regular git repo, capturing every change Claude makes during your coding sessions. This allows you to:

- **See exactly what Claude changed** in each interaction
- **Branch off from any Claude change** to explore different approaches  
- **Compare different solutions** Claude tried for the same problem
- **Revert specific Claude changes** without affecting your manual work
- **Track Claude's problem-solving process** step by step

## 🚀 Key Features

### Smart Change Tracking
- **Precise Change Capture**: Records only what Claude actually changed, not full file states
- **Patch-Based Storage**: Each commit contains `.patch` files for easy application/rollback  
- **Non-Destructive**: User changes and Claude changes are completely independent
- **Surgical Rollbacks**: Undo specific Claude changes without affecting user modifications
- Timestamps every change with session context
- Links changes to specific Claude conversations

### Session-Based Branching  
- Auto-creates branches for each Claude session
- Named branches like `session-2024-01-15-14-30` (timestamp-based)
- **Concurrent session support**: Multiple Claude sessions can run simultaneously
  - `session-2024-01-15-14-30` (first session)
  - `session-2024-01-15-14-30-45` (second session, same minute)
  - `session-2024-01-15-14-30-45-2` (third session, same second)
- Navigate between different approaches Claude tried
- Merge successful changes back to main codebase

### Intelligent Conflict Detection & Workflow Assistance 🧠
- **Smart Conflict Detection**: Automatically detects when you and Claude modify the same files
- **Human Activity Tracking**: Tracks ALL your repository changes alongside Claude's work
- **Related File Analysis**: Identifies when changes affect files in the same directory or with similar names
- **Merge Strategy Recommendations**: AI suggests Safe Auto-Merge, Selective Merge, or Careful Manual Merge
- **File Hash Tracking**: Monitors actual content changes to detect modification patterns
- **Conflict Resolution Guidance**: Step-by-step assistance for resolving merge conflicts

### Advanced Analysis
- Pattern detection across Claude's changes
- Success scoring based on change outcomes  
- Cross-project insights and best practices
- AI-powered change recommendations

### Why Real Git?
Using a real git repository gives you superpowers:
- **🔍 Full History**: Every Claude change is a proper commit with diffs
- **🌿 Branch Management**: Create, merge, rebase Claude's work like any code
- **⚡ Performance**: Git's efficient storage and indexing
- **🔧 Tooling**: Works with any git tool (tig, gitk, VSCode, etc.)
- **📊 Analytics**: Use git log, blame, bisect for Claude change analysis
- **🔄 Integration**: Easy to cherry-pick or patch Claude changes to main repo

## 🛠 Architecture

### Real Git Repository
Claude Git creates a **real git repository** inside `.claude-git/`, giving you all the power of git:

```
project-root/
├─ .git/                    # Your normal git repo
└─ .claude-git/             # REAL git repo for Claude changes
   ├─ .git/                 # Full git repository
   ├─ changes/              # Claude change records
   │  ├─ abc123.json        # Change metadata
   │  ├─ abc123.patch       # Exact patch to apply
   │  ├─ def456.json        # Another change
   │  └─ def456.patch       # Another patch
   ├─ sessions.json         # Session metadata
   └─ config.json           # Claude Git configuration
```

### What Gets Committed?
Each Claude change creates **two files** in a git commit:
1. **`change-id.json`** - Metadata (timestamp, file path, old/new strings)
2. **`change-id.patch`** - Standard git patch for the exact change

This means you can:
- **Apply patches** to your main repo: `git apply claude-change.patch`
- **Rollback cleanly** even if you made other changes to the same file
- **Use any git tool** to analyze Claude's change patterns

### Hook-Based Change Capture
```bash
# ~/.claude/hooks/post_tool_use.sh
#!/bin/bash
if [[ "$TOOL_NAME" =~ ^(Edit|Write|MultiEdit)$ ]]; then
    claude-git capture "$HOOK_INPUT_JSON"
fi
```

### Native Git Commands
Use regular git commands on the Claude repository:
```bash
# Navigate Claude's history
claude-git git log --oneline
claude-git git show HEAD
claude-git git diff HEAD~1

# Create branches from Claude changes  
claude-git git checkout -b fix-attempt-2
claude-git git cherry-pick <commit-hash>

# Advanced git operations
claude-git git rebase -i HEAD~5
claude-git git bisect start
```

## 📋 Installation

### Prerequisites
- Claude Code CLI installed and configured
- Python 3.8+ 
- Git 2.0+

### Quick Start
```bash
# Option 1: Install from PyPI (coming soon)
pip install claude-git

# Option 2: Install from source
git clone https://github.com/zfogg/claude-git.git
cd claude-git
uv sync

# Initialize in your project
cd /path/to/your/project  
claude-git init

# Set up Claude Code hooks (automatic PostToolUse integration)
claude-git setup-hooks

# Start coding with Claude - changes are automatically tracked!
# Check your changes: claude-git log
```

## 🔧 Usage

### Basic Commands
```bash
# View Claude's recent changes (uses git log under the hood)
claude-git log --oneline

# See what Claude is working on now
claude-git status

# View detailed diff of a specific change
claude-git show <commit-hash>

# Use ANY git command on Claude's repository
claude-git git log --oneline --graph
claude-git git show HEAD
claude-git git diff HEAD~2..HEAD
claude-git git blame changes/

# Apply a Claude change to your main project
claude-git apply <commit-hash>
claude-git apply <commit-hash> --dry-run

# Rollback a specific Claude change
claude-git rollback <commit-hash>

# Create branch from any Claude commit
claude-git git checkout -b my-experiment <commit-hash>
```

### 🧠 Intelligent Workflow Commands
```bash
# Detect conflicts between Claude and human changes
claude-git conflicts
claude-git conflicts --session-id <session-id>
claude-git conflicts --limit 20

# Get conflict resolution assistance
claude-git resolve <commit-hash>

# Analyze patterns and get merge recommendations
claude-git analyze
claude-git analyze --session-id <session-id>
```

### Web Interface
```bash
# Launch the web dashboard
claude-git web

# View at http://localhost:3000
# - Timeline of all changes
# - Interactive diff viewer
# - Session replay functionality  
# - Branch management UI
```

## 🎮 Example Workflows

### Basic Workflow
1. **Start Claude session**: Claude Git automatically creates branch `session-2024-01-15-14-30` 
2. **Claude makes changes**: Each Edit/Write creates a real git commit with the actual file changes
3. **Review changes**: `claude-git git log --oneline` shows commit history
4. **Inspect specific changes**: `claude-git git show <hash>` shows full diff
5. **Create experimental branches**: `claude-git git checkout -b experiment`
6. **Apply changes to main repo**: Use `git format-patch` and `git am` or manual cherry-picking

### 🧠 Intelligent Collaboration Workflow
1. **Automatic conflict detection**: As Claude works, system tracks your parallel changes
2. **Check for conflicts**: `claude-git conflicts` shows potential merge issues
3. **Get AI recommendations**: `claude-git analyze` suggests merge strategy based on patterns
4. **Resolve conflicts smartly**: `claude-git resolve <commit>` provides step-by-step guidance
5. **Apply changes safely**: Follow recommended merge strategy (Auto-Merge, Selective, or Manual)

### Power User Workflow
```bash
# See Claude's work in a beautiful graph
claude-git git log --oneline --graph --all

# Find when Claude introduced a bug
claude-git git bisect start
claude-git git bisect bad HEAD
claude-git git bisect good HEAD~10

# Create patch files to apply to main repo
claude-git git format-patch HEAD~3..HEAD
git am *.patch

# Compare different Claude sessions  
claude-git git diff session-morning..session-afternoon
```

## 📊 Advanced Features

### Change Analytics
- **Pattern Recognition**: "Claude often fixes auth bugs by updating middleware first"
- **Success Metrics**: Track which changes actually solved problems
- **Rollback Intelligence**: Automated suggestions for problematic changes

### Multi-Project Insights
- Cross-project pattern analysis
- Learning curve visualization  
- Best practice extraction
- Team collaboration features

### Integration Modes
- **Selective Merge**: Cherry-pick specific Claude changes
- **Conflict Prevention**: Warn before modifying recently changed files
- **Change Proposals**: Bundle related changes into single commits

## 🗺 Roadmap

### Phase 1: Core Tracking ✅ **COMPLETE**
- [x] Hook-based change capture (PostToolUse integration)
- [x] Real git repository with proper commits
- [x] CLI for viewing changes (`claude-git log`, `status`, `show`)
- [x] Parent repository hash tracking
- [x] Session-based branching with collision detection
- [x] Patch generation and application

### Phase 2: Intelligent Workflows ✅ **COMPLETE**  
- [x] Smart conflict detection (`claude-git conflicts`)
- [x] Human activity tracking with file hash monitoring
- [x] AI-powered merge strategy recommendations (`claude-git analyze`)
- [x] Conflict resolution assistance (`claude-git resolve`)
- [x] Pattern analysis and insights
- [x] Session management (`claude-git sessions`)

### Phase 3: Web Interface (Future)
- [ ] React-based dashboard
- [ ] Interactive diff visualization
- [ ] Session management UI
- [ ] Branch operations

### Phase 4: Advanced Analytics (Future)
- [ ] Cross-project insights
- [ ] Team collaboration features
- [ ] Learning curve visualization

## 🤝 Contributing

We welcome contributions! Check out our [Contributing Guide](CONTRIBUTING.md) for details.

### Development Setup
```bash
git clone https://github.com/your-username/claude-git.git
cd claude-git
pip install -e ".[dev]"
pre-commit install
```

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.

## 🙋 Support

- **Documentation**: [docs/](docs/)
- **Issues**: [GitHub Issues](https://github.com/your-username/claude-git/issues)
- **Discussions**: [GitHub Discussions](https://github.com/your-username/claude-git/discussions)

---

*"Finally, version control that understands AI development workflows"*

🎉 **PRODUCTION READY**: Complete parallel version control system for AI development workflows! Real-time tracking confirmed. Hook system working perfectly!