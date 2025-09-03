# Contributing to Claude Git

Thank you for your interest in contributing to Claude Git! This guide will help you get started.

## Development Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/zfogg/claude-git.git
   cd claude-git
   ```

2. **Install dependencies with uv**:
   ```bash
   uv sync
   ```

3. **Install development dependencies**:
   ```bash
   uv sync --extra dev
   ```

4. **Install pre-commit hooks**:
   ```bash
   uv run pre-commit install
   ```

## Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=claude_git

# Run specific test
uv run pytest tests/test_repository.py
```

## Code Style

We use several tools to maintain code quality:

- **Black**: Code formatting
- **isort**: Import sorting
- **flake8**: Linting
- **mypy**: Type checking

Run all checks:
```bash
uv run black src tests
uv run isort src tests
uv run flake8 src tests
uv run mypy src
```

## Testing the CLI

```bash
# Test CLI commands
uv run claude-git --help
uv run claude-git init
uv run claude-git status
```

## Project Structure

```
claude-git/
├── src/claude_git/
│   ├── cli/           # CLI interface
│   ├── core/          # Core functionality
│   ├── hooks/         # Hook scripts
│   ├── models/        # Data models
│   └── web/           # Web interface (future)
├── tests/             # Test suite
├── docs/              # Documentation
└── scripts/           # Utility scripts
```

## Submitting Changes

1. **Create a branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes and commit**:
   ```bash
   git add .
   git commit -m "Add your feature"
   ```

3. **Push and create a pull request**:
   ```bash
   git push origin feature/your-feature-name
   ```

## Reporting Issues

Please use the [GitHub Issues](https://github.com/zfogg/claude-git/issues) page to report bugs or request features.

## License

By contributing to Claude Git, you agree that your contributions will be licensed under the MIT License.