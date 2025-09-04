# 🔄 Claude Git - Professional AI-Human Collaboration with Fork-Based Version Control

The **first version control system designed for AI pair programming**. Claude Git treats AI as a proper development partner with full git workflow integration, professional commit attribution, and transparent collaboration tracking.

## 🎯 Revolutionary Fork-Based Architecture

Claude Git creates a **true git fork** of your repository where AI works as an independent developer:

- **Main Repository**: Your normal git workflow - commit when YOU decide
- **Claude-Git Fork**: Real git fork (`git remote add upstream ../`) where Claude works on dedicated branches
- **Professional Integration**: Use standard `git merge`, `git cherry-pick`, and `git diff` to incorporate Claude's work
- **Complete Transparency**: Full audit trail of AI contributions with reasoning preserved

### The Professional AI Collaboration Problem

**Current Reality:** AI-generated code is everywhere, but completely untracked:

```bash
# Today's broken workflow:
1. Developer: "Claude, implement authentication system"
2. Claude writes 200 lines across 5 files
3. Developer commits: "Add authentication"
4. 6 months later: "Why did I implement it this way?" (You didn't - Claude did)
5. Git blame shows developer's name, not Claude's contribution
6. Claude's reasoning and context: COMPLETELY LOST
```

**Claude Git's Solution - Professional AI Attribution:**

```bash
# Revolutionary fork-based workflow:
1. Claude works on dedicated branch: claude-session-auth
2. Each Claude commit preserves thinking: "Planning JWT middleware approach..."
3. Developer reviews Claude's work: git diff claude/claude-session-auth
4. Professional integration: git merge claude/claude-session-auth
5. Result: Claude's contributions properly attributed with full context preserved

# Git history shows truth:
abc123 John: Add payment integration
def456 Claude: Planning auth system - need JWT middleware and validation
ghi789 Claude: Created User class with proper validation methods  
jkl012 Claude: Added JWT token generation in auth middleware
mno345 John: Updated auth config for production
```

## 🚀 Core Capabilities

### 🤝 Professional AI-Human Git Workflows
- **Fork-Based Collaboration**: Claude works on proper git branches in a real fork of your repo
- **Standard Git Integration**: Use `git merge claude/session-name`, `git cherry-pick`, `git diff` 
- **AI Commit Attribution**: Every Claude commit shows "Author: Claude" with full reasoning preserved
- **Selective Integration**: Cherry-pick the AI changes you want, leave what you don't
- **Mid-Session Branch Switching**: User switches branches → Claude auto-commits and continues seamlessly

### 🔍 Complete AI Transparency & Auditability
- **AI Attribution Tracking**: `git log --author="Claude"` shows all AI contributions
- **Thinking Text Preservation**: Every Claude commit includes reasoning: "Planning auth approach..."
- **Professional Code Review**: Review AI work like any team member before merging
- **Enterprise Compliance**: Full audit trail for AI-generated code with git-native tools
- **Context Preservation**: 6 months later, understand why Claude chose specific approaches

### 🌳 Revolutionary Session Worktrees
- **Multi-Session Isolation**: Multiple Claude sessions work concurrently in separate worktrees
- **Real-Time Test Integration**: Each session gets independent pytest-testmon for live feedback
- **Session Branch Management**: Each session works on `claude-session-{id}` branches
- **Smart Session Merging**: Merge compatible sessions, handle conflicts intelligently
- **Branch Operations**: Create branches in claude-git, selectively merge to main
- **Professional Git Tooling**: Use any git tool (tig, gitk, VSCode) on Claude's work

## 🏗 Architecture Deep Dive

### Fork-Based Repository Structure
```
project-root/
├── .git/                           # Main repository (user-controlled)
├── src/                           # Your project files  
├── .claude-git/                   # TRUE GIT FORK of your repository
│   ├── .git/                      # Full git repository (fork)
│   │   ├── refs/remotes/upstream/  # Points to ../. (your repo)
│   │   └── refs/notes/commits     # Git notes storage (structured data)
│   ├── src/                       # IDENTICAL project structure 
│   └── worktree/                  # Session worktrees
│       ├── session-auth-abc123/   # Isolated session workspace
│       └── session-ui-def456/     # Another concurrent session
```

**Key Architecture Benefits:**
- **Real Git Fork**: `cd .claude-git && git remote -v` shows `upstream: ../`
- **Shared Git History**: Both repos share same commit ancestry  
- **Professional Workflows**: `git merge upstream/main`, `git fetch upstream`
- **Performance Optimized**: `git clone --reference` shares objects, minimal disk usage

**🚀 Revolutionary Auto-Commit + Squash Workflow:**

The fork architecture enables a groundbreaking development workflow where every single change is automatically preserved, then intelligently organized for professional integration:

**How It Works:**
1. **Continuous Auto-Commit**: Every file change Claude makes is immediately committed to the fork
2. **Complete Change Capture**: User changes, Claude changes - everything is preserved with full context
3. **Intelligent Squashing**: When Claude stops coding, related commits are squashed into logical units
4. **Cherry-Pickable Results**: Each squashed commit becomes a professional, mergeable unit of work

**Example Auto-Commit + Squash Flow:**
```bash
# During Claude session - auto-commits every change:
Auto-commit 1: "Start auth implementation - create User class"
Auto-commit 2: "Add JWT token validation method"  
Auto-commit 3: "Handle user config changes"
Auto-commit 4: "Fix validation logic for edge cases"
Auto-commit 5: "Add error handling for expired tokens"

# Session ends - intelligent squashing:
git rebase -i HEAD~5  # Squash related commits
Final commit: "Planning authentication system - JWT middleware and validation

I started by creating a User class with proper validation methods, 
then added JWT token generation in the auth middleware. The config 
needed auth settings for token expiration and secret keys.

Handled edge cases: expired tokens, invalid credentials, rate limiting.
The user wanted this to integrate with their existing OAuth setup.

Files: auth.py, user.py, config.py
Parent-Repo: abc123def456
Session: session-789"
```

**Professional Integration Benefits:**
- **Perfect Changesets**: Each squashed commit contains the COMPLETE changeset needed to integrate a feature
- **User Changes Included**: If user switched branches or made changes during the session, those are included in the final commit
- **Cherry-Pick Ready**: `git cherry-pick claude/session-auth` brings the complete auth implementation
- **Audit Trail**: Full development history preserved in auto-commits, logical units in squashed commits
- **Risk-Free Integration**: Review squashed commits, cherry-pick what you want

### Data Storage Philosophy

**Maximum Accessibility, Optimal Performance:**
- **Everything visible** in `git log` (commit messages)
- **Everything queryable** in git notes (structured JSON)
- **Query optimization** - use fastest method for each use case
- **Zero external dependencies** - pure git native

**Example Data Flow:**
```bash
# 1. Claude session ends → extract thinking text
THINKING="Planning auth system - need JWT middleware..."

# 2. Store in commit message (human readable)
git commit -m "$THINKING

Parent-Repo: abc123def456  
Session: session-789
Files: auth.py,user.py"

# 3. ALSO store in git notes (query optimized)
git notes add -m '{"parent_repo":"abc123def456","thinking":"Planning auth..."}' HEAD
```

**Query Performance:**
- **Simple lookups**: `git log --grep="Parent-Repo: abc123"` (milliseconds)
- **Complex filters**: Parse git notes JSON (still fast, more flexible)
- **Text search**: `git log --grep="authentication"` (natural language search)
- **File patterns**: Notes JSON array searching

## 🎣 Hook Integration Strategy

**🧠 Real-Time Thinking Capture & Rich Commit Generation**

Claude Code hooks automatically capture Claude's thinking process as it happens and create meaningful commits with complete context:

### Claude Code Hooks (Automatic Setup)
```bash
# ~/.claude/hooks/session_start.sh
#!/bin/bash
# Initializes session tracking when Claude starts working
PROJECT_ROOT=$(pwd)
if [ -d ".claude-git" ]; then
    MAIN_REPO_COMMIT=$(git rev-parse HEAD)
    python -m claude_git.cli.main session-start --main-repo-commit="$MAIN_REPO_COMMIT"
    echo "✅ Claude session started - tracking changes to .claude-git"
fi

# ~/.claude/hooks/session_end.sh  
#!/bin/bash
# Extracts thinking text and creates rich commit when Claude finishes
TRANSCRIPT_PATH="$1"  # Claude Code provides transcript with thinking
PROJECT_ROOT=$(pwd)
if [ -d ".claude-git" ]; then
    MAIN_REPO_COMMIT=$(git rev-parse HEAD)
    python -m claude_git.cli.main session-end \
      --transcript="$TRANSCRIPT_PATH" \
      --main-repo-commit="$MAIN_REPO_COMMIT"
    echo "✅ Session ended - commit created with thinking text and conversation history"
fi
```

### 🚀 What This Achieves
- **Real-Time Capture**: Claude's thinking is captured as it thinks during the session
- **Accumulated Changes**: All file edits are grouped into logical commits
- **Rich Context**: Commit messages contain actual thought process, not just technical metadata  
- **Conversation History**: Full user-Claude dialogue stored in git notes for AI conflict resolution
- **Automatic Operation**: Zero manual intervention required

### Revolutionary: Claude's Thinking as Commit Messages
Instead of generic commit messages, we use **Claude's actual thought process**:

```bash
# Traditional approach:
git commit -m "claude: edit auth.py"

# Revolutionary approach using thinking text:
git commit -m "Planning user authentication system - need to add JWT middleware and validation

I should start by creating a User class with proper validation methods, 
then add JWT token generation in the auth middleware. The config will 
need auth settings for token expiration and secret keys.

Parent-Repo: abc123def
Files: auth.py, user.py, config.py"
```

### Git Hooks (User Change Detection)
```bash
# .git/hooks/post-commit
#!/bin/bash
# Triggered after user commits to main repo
claude-git sync-user-commit "$(git rev-parse HEAD)"

# Watches for user changes between Claude sessions
# Auto-commits to claude-git when user modifies files
```

### Smart Commit Timing
- **User changes BEFORE Claude starts**: Auto-commit to claude-git first
- **Claude works**: Accumulate changes, extract thinking text from transcript
- **Session ends**: Create logical commit with Claude's complete thought process
- **User changes DURING Claude work**: Interrupt, commit user changes, resume Claude
- **User changes AFTER Claude**: Auto-commit user changes

### Thinking Text Extraction
```python
def extract_thinking_text(transcript_path):
    """Extract Claude's thinking text from JSONL transcript file."""
    thinking_messages = []
    
    with open(transcript_path, 'r') as f:
        for line in f:
            data = json.loads(line)
            
            # Find thinking messages
            if (data.get('type') == 'message' and 
                data.get('role') == 'assistant' and 
                data.get('thinking') == True):
                
                content = data.get('content', [])
                for item in content:
                    if item.get('type') == 'text':
                        thinking_messages.append(item['text'])
    
    # Combine thinking messages into coherent summary
    return summarize_thinking_flow(thinking_messages)

def summarize_thinking_flow(thinking_messages):
    """Create coherent commit message from thinking fragments."""
    # Remove duplicates while preserving order
    unique_thoughts = []
    seen = set()
    for thought in thinking_messages:
        if thought not in seen:
            unique_thoughts.append(thought)
            seen.add(thought)
    
    # Join with proper formatting for git commit message
    return "\n\n".join(unique_thoughts[:5])  # Limit to 5 most important thoughts
```

## 🛠 Revolutionary Command Set

### Dual-Repository Navigation
```bash
# Show work context - what was Claude doing when main repo was at specific commit?
claude-git show-work-at abc123
# Output: "During main repo abc123, Claude implemented authentication (3 commits)"

# Find all Claude work during main repo development period
claude-git log --main-repo-range abc123..def456  
# Shows all Claude sessions during that main repo evolution

# Show collaborative timeline
claude-git timeline
# [main abc123] user: add payment feature
#   ├── [claude def456] claude: implement payment validation  
#   └── [claude ghi789] claude: add error handling
# [main jkl012] user: fix typo
#   └── [claude mno345] claude: refactor payment processing
```

### Intelligent Selective Operations
```bash
# Revert to specific user state with Claude work control
claude-git revert-to-user abc123 --exclude-claude-after
claude-git revert-to-user abc123 --include-all-claude
claude-git revert-to-user abc123 --interactive

# Session-based operations
claude-git revert-session session-456  # Undo entire logical work unit
claude-git show-session session-456    # See complete session work
claude-git diff-sessions session-123..session-456
```

### Context-Aware Analysis  
```bash
# Understand Claude's complete thought process
claude-git explain def456
# Shows: "I'm thinking about authentication flow - user login should validate 
#         credentials, generate JWT token, and set secure session. Need to 
#         handle edge cases like expired tokens and invalid credentials."

# Search Claude's thinking patterns
claude-git search-thinking "authentication"
# Shows all commits where Claude was thinking about auth-related topics

# Collaboration pattern analysis with thinking context
claude-git patterns --thinking
# "Claude often thinks about error handling after implementing core features"
# "Claude's debugging thought process: identify issue -> isolate -> fix -> test"

# Find related work by Claude's thought patterns
claude-git find-related-thinking "user validation"
# Shows all sessions where Claude was thinking about user validation
```

## 🔄 Synchronization Strategy

### File-Level Synchronization
```python
# Every change triggers sync in both directions
def sync_files():
    # Main repo → Claude-git repo
    for changed_file in detect_main_repo_changes():
        copy(f"main_repo/{changed_file}", f".claude-git/{changed_file}")
    
    # Claude-git repo → Main repo (when restoring/applying changes)
    for changed_file in detect_claude_git_changes():
        copy(f".claude-git/{changed_file}", f"main_repo/{changed_file}")
```

### Git-Native Data Storage Strategy

We store the same data in **both places** for optimal querying:

**1. Commit Messages (Human-Visible)**
```bash
# Every commit message contains structured data
git commit -m "Planning authentication system - need JWT middleware and validation

I should create a User class with proper validation, then add JWT token 
generation. The config needs auth settings for token expiration.

Parent-Repo: abc123def456
Session: session-789
Files: auth.py,user.py,config.py
Lines-Added: 47
Lines-Modified: 12"
```

**2. Git Notes (Query-Optimized & Conversation-Aware)**
```bash
# Comprehensive structured data for efficient querying and AI conflict resolution
git notes add -m '{
  "parent_repo": "abc123def456",
  "session_id": "session-789", 
  "files": ["auth.py", "user.py", "config.py"],
  "thinking": "Planning authentication system - need JWT middleware...",
  "conversation": [
    {"role": "user", "content": "Help me implement user authentication"},
    {"role": "assistant", "content": "I will help you build a JWT-based authentication system..."},
    {"role": "assistant", "thinking": true, "content": "Planning authentication system - need JWT middleware..."}
  ],
  "lines_added": 47,
  "lines_modified": 12,
  "timestamp": "2025-01-15T14:30:00Z",
  "tool_calls": [
    {"tool": "Write", "file": "auth.py", "timestamp": "14:30:15"},
    {"tool": "Edit", "file": "user.py", "timestamp": "14:30:45"}  
  ],
  "claude_code_transcript": "/path/to/claude/transcript.jsonl"
}' claude-commit-hash
```

**🚀 Revolutionary: AI-Powered Conflict Resolution via Git Notes**

When merge conflicts occur, claude-git can automatically resolve them using Claude Code and the stored conversation context:

```bash
# Automatic conflict resolution using conversation history
claude-git resolve-conflicts --auto
# → Extracts conversation from git notes
# → Generates contextual prompt: "You were implementing auth system, user switched to OAuth..."  
# → Runs: claude -p "$contextual_prompt" to resolve conflicts intelligently
# → USER CHANGES ALWAYS WIN, Claude enhances compatibly
```

**Query Strategy: Use Whatever's Fastest**
```python
def find_claude_work_by_parent_commit(parent_commit):
    # Fast text search in commit messages
    result = run_git_command([
        "log", f"--grep=Parent-Repo: {parent_commit}", 
        "--pretty=format:%H %s"
    ])
    return parse_commit_list(result)

def find_work_by_file_patterns(file_pattern):
    # Complex queries use structured git notes  
    commits = run_git_command(["log", "--pretty=format:%H"])
    matching = []
    
    for commit in commits.split('\n'):
        try:
            note = run_git_command(["notes", "show", commit])
            data = json.loads(note)
            if any(file_pattern in f for f in data.get("files", [])):
                matching.append((commit, data))
        except:
            continue
    return matching

def search_thinking_patterns(search_term):
    # Search thinking text in both places
    # 1. Try commit message grep first (fastest)
    grep_result = run_git_command([
        "log", f"--grep={search_term}", "--pretty=format:%H %s"
    ])
    
    # 2. Fall back to notes search for complex queries
    if not grep_result:
        return search_notes_field("thinking", search_term)
```

## 🌟 Revolutionary Multi-Session Collaboration

### **The Game-Changer: Multiple Claude Sessions Working Together**

Imagine multiple Claude Code sessions working on your project simultaneously, each with their own branch, automatically merging compatible changes:

```bash
# Terminal 1: Claude working on authentication  
# → Creates branch: claude-session-auth-abc123
# → Works in worktree: .claude-git/worktree/session-auth-main/
# → Real-time testing: pytest-testmon running continuously

# Terminal 2: Claude working on UI components
# → Creates branch: claude-session-ui-def456  
# → Works in worktree: .claude-git/worktree/session-ui-main/
# → Test feedback: "4 tests passed, 2 UI tests failed"

# Terminal 3: Claude working on database layer
# → Creates branch: claude-session-db-ghi789
# → Works in worktree: .claude-git/worktree/session-db-main/
# → Live monitoring: "Database migration tests all green ✅"
```

### **Smart Multi-Session Merging**

When Claude sessions end, claude-git automatically handles the complexity:

```bash
# Non-conflicting changes → Automatic merge
Auth session: Modified auth.py, user.py  
UI session: Modified components.tsx, styles.css
DB session: Modified models.py, migrations/

→ All changes automatically merged to main claude-git branch

# Conflicting changes → Interactive resolution
Auth session: Modified config.py (lines 10-15)
DB session: Modified config.py (lines 12-18)  

→ claude-git merge-interactive 
→ "Choose auth session config? [y/n]"
→ "Choose DB session config? [y/n]" 
→ "Combine both approaches? [y/n]"
```

### **Session Branch Navigation**

Navigate between different Claude approaches with ease:

```bash
# See all active session worktrees
claude-git sessions --list
# session-auth-abc123: JWT implementation (47 files changed, 12 tests passing)
# session-ui-def456: Component-based UI (23 files changed, 8 tests failing)
# session-db-ghi789: Database refactor (15 files changed, all tests green)

# Compare different approaches
claude-git diff-sessions session-auth-abc123 session-ui-def456
# Shows: "Authentication vs UI implementation differences"

# Interactive session selection
claude-git merge-interactive
# → "Include auth session JWT middleware? [y/n]"
# → "Include UI session error handling? [y/n]"
# → "Include database session migrations? [y/n]"
```

### **AI-Powered Conflict Resolution Revolution**

The **world's first self-healing version control system** - when Claude's work conflicts with user changes, Claude Code automatically resolves conflicts intelligently:

```bash
# User commits a change that conflicts with Claude's work
git commit -m "Switch from JWT to OAuth authentication"

# Claude-git automatically detects and resolves
🔄 Rebasing claude-main onto user's latest commit...
❌ CONFLICT detected in src/auth.py

🤖 AI conflict resolution started (max 60s)
📁 Creating conflict resolution worktree...
🔧 Analyzing conflict with Claude Code...

$ claude -p "Resolve merge conflict: User switched to OAuth, integrate my JWT validation logic compatibly..."

⏱️  Claude resolved conflict in 23 seconds!
✅ Proposed Resolution:
```python
def authenticate_user(request):
    oauth_token = request.headers.get('Authorization')
    if not oauth_token:
        raise AuthenticationError('Missing OAuth token')
    
    # Validate OAuth token (user's architecture wins)
    user = validate_oauth_token(oauth_token)
    
    # Enhanced validation from Claude's JWT logic
    if not user.is_active:
        raise AuthenticationError('User account inactive')
    
    return user
```

🎯 Accept this resolution? [Y/n/view/edit]: Y
✅ Resolution accepted and applied!
🔀 Successfully rebased claude-main
```

**Key Features:**
- **USER CHANGES ALWAYS WIN** - Preserves user's architectural decisions
- **AI Enhancement** - Integrates valuable Claude logic where compatible
- **60-Second Limit** - Fast resolution or graceful fallback
- **Multi-Language** - Supports 15+ programming languages with AST analysis
- **Safe Isolation** - Uses temporary worktrees for conflict resolution
- **Syntax Verification** - Validates resolved code before applying

## 🧪 **REVOLUTIONARY: Real-Time Test Integration**

### **The Future is Here: AI Development with Live Test Feedback**

Claude-git now integrates with **pytest-testmon** to provide real-time test feedback during Claude Code sessions, creating the world's first **test-driven AI development system**:

```bash
# Automatic pytest-testmon integration during Claude sessions
🧪 Starting real-time test monitoring for session session-auth-abc123...
📁 Worktree: .claude-git/worktree/session-auth-main/
🔍 Watching: *.py files for changes
⚡ Test runner: pytest-testmon --testmon-readonly

# Live test feedback as Claude works
📝 Claude modifies auth.py (lines 45-67)
🧪 → Running affected tests... 
✅ test_user_validation PASSED (0.12s)
✅ test_jwt_generation PASSED (0.08s)
❌ test_auth_middleware FAILED - AttributeError: 'User' object has no attribute 'is_authenticated'

🤖 Claude sees test failure instantly:
"I need to add the is_authenticated property to the User class..."

📝 Claude modifies user.py (line 23)
🧪 → Re-running failed tests...
✅ test_auth_middleware PASSED (0.15s)

✨ Real-time feedback creates smarter AI development!
```

### **Game-Changing Features:**

**🔄 Live Feedback Loop:**
- Claude sees test results **instantly** as it makes changes
- Failed tests influence Claude's next moves automatically
- **TDD for AI**: Tests guide Claude's implementation decisions
- Zero manual intervention - fully automated test-driven development

**📊 Cross-Session Test Intelligence:**
```bash
# Multi-session test coordination
Terminal 1 (Auth): "✅ All auth tests passing (12/12)"
Terminal 2 (UI): "❌ 2 UI tests failing due to auth changes"
Terminal 3 (DB): "⚠️  3 integration tests affected"

# Automatic test impact analysis
claude-git test-impact session-auth-abc123
# "Auth changes affect 7 tests across 3 other sessions"
# "Suggested fix: Update UserInterface mock in ui tests"
```

**🎯 Intelligent Test-Driven Commits:**
- Commits only created when **all affected tests pass**
- Test results included in commit messages and git notes
- Failed test sessions can be recovered and resumed
- **Quality guarantee**: Claude's work always maintains test suite health

### **Shell Command Tracking Revolution**

Track not just file changes, but the complete development process including **real-time test results**:

```bash
# Git notes now include comprehensive development activity
git notes show session-auth-abc123

{
  "thinking": "Need to test the authentication endpoint...",
  "files": ["auth.py", "test_auth.py", "user.py"],
  "shell_commands": [
    {"cmd": "pytest-testmon test_auth.py", "timestamp": "14:30:15", "result": "PASSED", "duration": "0.12s"},
    {"cmd": "pytest test_user_validation", "timestamp": "14:30:45", "result": "FAILED", "error": "AttributeError"},
    {"cmd": "pytest --testmon-readonly", "timestamp": "14:31:00", "result": "12 passed, 0 failed"}
  ],
  "test_results": {
    "total_tests": 12,
    "passed": 12,
    "failed": 0,
    "test_files": ["test_auth.py", "test_user.py"],
    "coverage_delta": "+5.2%",
    "affected_by_changes": ["test_jwt_generation", "test_auth_middleware"]
  },
  "ai_conflict_resolutions": [
    {"file": "auth.py", "resolved_at": "14:31:15", "duration": "23s", "method": "claude-code"}
  ],
  "session_branch": "claude-session-auth-abc123",
  "worktree_path": ".claude-git/worktree/session-auth-main/"
}
```

## 🎮 Revolutionary Developer Workflows

### Test-Driven Problem Investigation
```bash
# Something broke - which Claude session caused test failures?
git log --oneline | head -5  # Find when tests started failing
claude-git show-test-timeline abc123  # See test results during that period
claude-git show-session session-payment --test-results  # See what tests were affected
claude-git revert-session session-payment --until-tests-pass  # Smart revert
```

### AI-Powered Learning and Analysis
```bash
# Study Claude's test-driven development approach
claude-git log --claude-only --failed-tests  # See how Claude handles test failures
claude-git show-complete-work def456 --include-tests  # See code + test changes together
claude-git explain def456 --test-context  # Understand Claude's testing strategy
claude-git test-patterns --session-auth  # Learn Claude's auth testing patterns
```

### Quality-Driven Collaborative Workflow
```bash
# Keep your work, include Claude's improvements that maintain test quality
claude-git revert-to-user abc123 --interactive --test-aware
# Shows: "Include Claude's error handling? (maintains 12/12 tests) [Y/n]"
#        "Include Claude's optimization? (adds 3 new tests) [Y/n]"
#        "Include Claude's refactor? (breaks 2 integration tests) [y/N]"

# Test-driven selective merging
claude-git merge-sessions --best-test-coverage
# Automatically chooses session changes that maximize test coverage
```

## 📊 Advanced Features Enabled by Dual-Repository Architecture

### Collaborative Intelligence
- **Work Pattern Recognition**: "Claude refactors after you implement features"
- **Context Awareness**: "This change happened when you were working on authentication"  
- **Selective History**: "Show only authentication-related work across all sessions"

### Professional Git Integration
- **Branch Operations**: `claude-git checkout -b experiment-auth session-456`
- **Cherry-picking**: `claude-git cherry-pick def456 --to-main-repo`
- **Conflict Resolution**: Leverage git's merge tools for Claude work

### Cross-Session Analysis
- **Session Comparison**: `claude-git diff-sessions morning-session afternoon-session`
- **Success Tracking**: Which Claude approaches led to successful outcomes?
- **Pattern Mining**: Common sequences in Claude's problem-solving approach

## 🔧 Installation and Setup

### Quick Start
```bash
# Install claude-git
pip install claude-git

# Initialize in your project  
cd /path/to/your/project
claude-git init

# Set up hooks (integrates with Claude Code automatically)
claude-git setup-hooks

# Start developing - changes are tracked with logical boundaries!
```

### Hook Configuration
```bash
# Configure Claude Code integration
claude-git configure --claude-code-hooks
# Automatically sets up session_start and session_end hooks

# Configure git hooks for user change detection  
claude-git configure --git-hooks
# Sets up post-commit and file watching
```

## 🗺 Implementation Roadmap

### Phase 1: Core Dual-Repository System ✅ **COMPLETED**
- ✅ **Repository Initialization**: Create synchronized git repos
- ✅ **File Synchronization**: Bidirectional file sync system  
- ✅ **Git-Native Operations**: Standard git commands instead of custom implementations
- ✅ **Hook Integration**: Claude Code session hooks + git hooks
- ✅ **Basic Commands**: `log`, `show`, `diff`, `init`

### Phase 2: Intelligent Commit Boundaries ✅ **COMPLETED**
- ✅ **Session Management**: Detect Claude work start/end
- ✅ **Logical Commits**: Group related changes into work units
- ✅ **Context Mapping**: Link Claude work to main repo state
- ✅ **Thinking Text Extraction**: Claude's thought process as commit messages
- ✅ **Chronological Commit Messages**: Thinking + file changes interspersed

### Phase 3: AI-Powered Conflict Resolution 🤖 **COMPLETED**
- ✅ **Self-Healing Version Control**: First VCS that resolves its own conflicts using AI
- ✅ **Claude Code Integration**: Use `claude -p "$prompt"` for non-interactive conflict resolution
- ✅ **Contextual AI Prompting**: Generate detailed prompts with file context and conflict analysis
- ✅ **Safe Worktree Isolation**: Temporary worktrees for conflict resolution testing
- ✅ **Intelligent User-Centric Resolution**: "USER CHANGES ALWAYS WIN" principle with AI enhancement
- ✅ **Multi-Language Support**: AST-aware conflict resolution for 15+ programming languages

### Phase 4: Multi-Session Branching & Real-Time Testing 🚀 **BREAKTHROUGH IMPLEMENTATION**
- 🚀 **Session-Based Worktrees**: Each Claude session gets isolated git worktree (revolutionary isolation)
- 🚀 **Real-Time Test Integration**: pytest-testmon running continuously during Claude sessions
- 🚀 **Live Test Feedback**: Claude sees test results instantly, guides implementation decisions
- 🚀 **Cross-Session Test Intelligence**: Multi-session test impact analysis and coordination
- 🚀 **Test-Driven AI Commits**: Only commit when all affected tests pass
- [ ] **Interactive Session Merging**: Choose which session approaches to merge
- [ ] **Shell Command Tracking**: Track bash commands and test results in git notes
- [ ] **Session Recovery**: Resume failed test sessions from last known good state

### Phase 5: Advanced Navigation & Test-Driven Workflows
- [ ] **Selective Operations**: `revert-to-user`, `include-claude-work`
- [ ] **Test-Driven Queries**: `show-test-impact`, `find-failing-tests`
- [ ] **Session Analysis**: `explain`, `patterns`, `diff-sessions`, `test-timeline`
- [ ] **Interactive Test Workflows**: Choose changes based on test results
- [ ] **AI Test Generation**: Claude automatically writes tests for new code
- [ ] **Regression Prevention**: Block commits that break existing functionality

### Phase 6: Professional Integration
- [ ] **Git Tool Compatibility**: Work with VSCode, tig, gitk
- [ ] **Advanced Branch Operations**: Create, merge, rebase Claude work
- [ ] **Fork-Based Architecture**: Optional upstream/downstream Git model
- [ ] **Performance Optimization**: Handle large repositories efficiently

## 🧪 Testing Strategy

### Repository Synchronization Tests
```python
def test_file_sync_bidirectional():
    # User changes main repo → claude-git repo updates
    # Claude changes claude-git repo → main repo updates
    # Files remain identical between repos

def test_commit_mapping_integrity():
    # Every claude-git commit maps to main repo commit
    # Database relationships remain consistent
    # Bidirectional lookup works correctly
```

### Hook Integration Tests
```python
def test_claude_session_boundaries():
    # session_start creates proper context
    # session_end creates logical commit
    # User interruptions handled correctly

def test_git_hook_detection():  
    # User commits trigger sync
    # File changes detected and committed
    # No conflicts during simultaneous changes
```

### Advanced Feature Tests
```python
def test_selective_revert_operations():
    # Can revert to user state with Claude inclusion/exclusion
    # Interactive selection works correctly
    # File state matches expectations

def test_context_aware_navigation():
    # show-work-at finds correct Claude commits
    # Timeline shows proper interleaving
    # Cross-session analysis works
```

## 🤝 Contributing to the Revolution

This dual-repository approach represents a fundamental shift in AI-human collaborative development. We're building the foundational tooling for a new era of software development.

### Development Setup
```bash
git clone https://github.com/zfogg/claude-git.git
cd claude-git
uv sync
claude-git init --dev-mode  # Special development configuration
```

### Key Areas for Contribution
- **Hook System**: Improving Claude Code integration
- **Mapping Database**: Query optimization and new relationship types  
- **Synchronization**: Handling edge cases and conflict resolution
- **User Experience**: Making complex operations intuitive

## 📄 License

MIT License - Building the future of AI-collaborative development.

---

*"The first version control system designed for the age of AI pair programming"*

🚀 **REVOLUTIONARY**: Dual-repository architecture with intelligent commit mapping - the future of AI-human collaborative development!