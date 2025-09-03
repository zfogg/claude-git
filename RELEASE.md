# Release Guide

## 🚀 How to Release Claude Git

This guide covers how to create and publish a new release of Claude Git.

## Prerequisites

1. **Clean Git Repository**: Ensure all changes are committed
2. **PyPI Access**: You'll need a PyPI account with API token configured
3. **GitHub Repository**: Push access to the main repository

## Option 1: Automated Release (Recommended)

### Using the Release Script

```bash
# Test the release process (dry run)
./scripts/release.sh 0.2.0 --dry-run

# Create the actual release
./scripts/release.sh 0.2.0
```

The script will:
- ✅ Run all tests and checks
- ✅ Update version in `pyproject.toml`  
- ✅ Build and verify the package
- ✅ Create git tag and push to GitHub
- ✅ Trigger automated GitHub Actions workflow

### Using GitHub Actions Manual Trigger

1. Go to **Actions** tab in GitHub repository
2. Select **Release** workflow
3. Click **Run workflow**
4. Enter the version number (e.g., `0.2.0`)
5. Click **Run workflow**

This will create the release without needing local access.

## Option 2: Manual Release Process

### 1. Update Version

```bash
# Edit pyproject.toml
sed -i 's/version = ".*"/version = "0.2.0"/' pyproject.toml
```

### 2. Run Quality Checks

```bash
# Run tests
uv run pytest -n auto --cov=claude_git --cov-report=term-missing

# Check formatting
uv run black --check src/ tests/
uv run isort --check-only src/ tests/

# Type check
uv run mypy src/
```

### 3. Build Package

```bash
# Clean previous builds
rm -rf dist/

# Install build tools
uv tool install build
uv tool install twine

# Build
uv tool run python -m build

# Verify package
uv tool run twine check dist/*
```

### 4. Create Git Release

```bash
# Commit version bump
git add pyproject.toml
git commit -m "Bump version to 0.2.0"

# Create tag
git tag v0.2.0

# Push
git push origin main
git push origin v0.2.0
```

### 5. Publish to PyPI

```bash
# Upload to PyPI (requires PYPI_API_TOKEN)
uv tool run twine upload dist/*
```

## GitHub Actions Automation

The repository includes automated CI/CD that will:

1. **On Tag Push**: Automatically run tests, build, and publish to PyPI
2. **On Manual Trigger**: Same process but creates the tag for you

### Required Secrets

Configure these in GitHub repository settings > Secrets:

- `PYPI_API_TOKEN`: Your PyPI API token for publishing

## Release Checklist

- [ ] All tests passing
- [ ] Code formatted with Black and isort  
- [ ] Type checks pass with mypy
- [ ] Version updated in `pyproject.toml`
- [ ] README.md reflects current state
- [ ] Git repository is clean
- [ ] Release notes prepared
- [ ] GitHub release created
- [ ] Package published to PyPI

## Version Numbering

Claude Git follows semantic versioning:

- **Major** (1.0.0): Breaking changes to CLI or major architecture
- **Minor** (0.2.0): New features, non-breaking changes  
- **Patch** (0.1.1): Bug fixes, small improvements

Current stable version: **0.2.0**

## Testing Installation

After publishing, test the installation:

```bash
# Test PyPI installation
pip install claude-git==0.2.0

# Test functionality
claude-git --version
claude-git --help
```

## Troubleshooting

### Release Script Fails

- Check that git working directory is clean
- Ensure all dependencies are installed with `uv sync`
- Verify version format matches semver (e.g., `0.2.0`)

### PyPI Upload Fails  

- Verify API token is correct and has upload permissions
- Check package name isn't already taken
- Ensure version number is unique (not already published)

### GitHub Actions Fail

- Check workflow logs in Actions tab
- Verify secrets are configured correctly
- Ensure branch protections don't block the workflow

## Support

- **Issues**: [GitHub Issues](https://github.com/zfogg/claude-git/issues)
- **Discussions**: [GitHub Discussions](https://github.com/zfogg/claude-git/discussions)