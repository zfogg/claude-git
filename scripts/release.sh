#!/usr/bin/env bash
set -euo pipefail

# Claude Git Release Script
# Usage: ./scripts/release.sh [version] [--dry-run]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

VERSION="${1:-}"
DRY_RUN="${2:-}"

if [[ -z "$VERSION" ]]; then
    echo "Usage: $0 <version> [--dry-run]"
    echo "Example: $0 0.2.0"
    echo "         $0 0.2.0 --dry-run"
    exit 1
fi

echo "🚀 Claude Git Release Process"
echo "Version: $VERSION"

if [[ "$DRY_RUN" == "--dry-run" ]]; then
    echo "🔍 DRY RUN MODE - No changes will be made"
    DRY_RUN=true
else
    DRY_RUN=false
fi

# Check if we're in a clean git state
if [[ $(git status --porcelain) ]]; then
    echo "❌ Git working directory is not clean. Please commit or stash changes."
    exit 1
fi

# Update version in pyproject.toml
echo "📝 Updating version in pyproject.toml..."
if [[ "$DRY_RUN" == "false" ]]; then
    sed -i.bak "s/version = \".*\"/version = \"$VERSION\"/" pyproject.toml
    rm pyproject.toml.bak
fi

# Run tests
echo "🧪 Running tests..."
if ! uv run pytest -n auto --cov=claude_git --cov-report=term-missing; then
    echo "❌ Tests failed. Aborting release."
    exit 1
fi

# Check code formatting
echo "🔍 Checking code formatting..."
if ! uv run black --check src/ tests/; then
    echo "❌ Code formatting check failed. Run 'uv run black src/ tests/' to fix."
    exit 1
fi

if ! uv run isort --check-only src/ tests/; then
    echo "❌ Import sorting check failed. Run 'uv run isort src/ tests/' to fix."
    exit 1
fi

# Type check
echo "🔍 Running type checks..."
if ! uv run mypy src/; then
    echo "❌ Type check failed. Please fix type errors."
    exit 1
fi

# Build package
echo "📦 Building package..."
if [[ "$DRY_RUN" == "false" ]]; then
    rm -rf dist/
    uv tool install build
    uv tool run python -m build
    
    # Check package
    uv tool install twine
    uv tool run twine check dist/*
fi

# Create git tag and commit
if [[ "$DRY_RUN" == "false" ]]; then
    echo "📝 Committing version bump..."
    git add pyproject.toml
    git commit -m "Bump version to $VERSION"
    
    echo "🏷️ Creating git tag..."
    git tag "v$VERSION"
    
    echo "📤 Pushing to origin..."
    git push origin main
    git push origin "v$VERSION"
    
    echo "✅ Release $VERSION completed!"
    echo ""
    echo "Next steps:"
    echo "1. The GitHub Actions workflow will automatically:"
    echo "   - Run tests on all Python versions"
    echo "   - Build the package"
    echo "   - Create a GitHub release"
    echo "   - Publish to PyPI (if PYPI_API_TOKEN is configured)"
    echo ""
    echo "2. Check the release at: https://github.com/zfogg/claude-git/releases/tag/v$VERSION"
else
    echo "✅ Dry run completed successfully!"
    echo "Everything looks good. Run without --dry-run to create the release."
fi