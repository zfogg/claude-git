.PHONY: test test-fast test-parallel test-coverage install lint format clean help install-hooks

# Default Python interpreter
PYTHON := python
UV := uv

# Test configurations
PYTEST_FLAGS := --testmon -n auto --tb=short --strict-markers --strict-config
PYTEST_COVERAGE_FLAGS := $(PYTEST_FLAGS) --cov=claude_git --cov-report=term-missing --cov-report=html
PYTEST_FAST_FLAGS := --testmon -n auto --tb=line -x --no-cov

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install dependencies
	$(UV) sync

test: ## Run all tests with coverage and parallel execution
	$(PYTHON) -m pytest $(PYTEST_COVERAGE_FLAGS)

test-fast: ## Run tests quickly (no coverage, fail fast)
	$(PYTHON) -m pytest $(PYTEST_FAST_FLAGS)

test-parallel: ## Run tests in parallel without coverage
	$(PYTHON) -m pytest $(PYTEST_FLAGS) --no-cov

test-sequential: ## Run tests sequentially (useful for debugging)
	$(PYTHON) -m pytest --testmon --tb=short

test-changed: ## Run only tests affected by recent changes (testmon only)
	$(PYTHON) -m pytest --testmon --no-cov -v

test-clean: ## Clean testmon database and run all tests
	rm -f .testmondata*
	$(PYTHON) -m pytest $(PYTEST_FLAGS) --no-cov

lint: ## Run linting tools
	$(UV) run ruff check .
	$(UV) run ruff format --check .

format: ## Format code with ruff
	$(UV) run ruff check --fix .
	$(UV) run ruff format .

clean: ## Clean up generated files
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf htmlcov/
	rm -rf .coverage
	rm -rf .testmondata*
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

# Development targets
dev-setup: install ## Set up development environment
	$(UV) add --group dev pre-commit
	pre-commit install

test-watch: ## Watch for changes and run affected tests
	while true; do \
		$(PYTHON) -m pytest $(PYTEST_FAST_FLAGS) --testmon-off || true; \
		inotifywait -qq -r -e modify,create,delete,move src/ tests/ || sleep 2; \
	done

# Testing specific areas
test-core: ## Test core functionality only
	$(PYTHON) -m pytest $(PYTEST_FLAGS) tests/test_*core* tests/test_*repository*

test-cli: ## Test CLI functionality only  
	$(PYTHON) -m pytest $(PYTEST_FLAGS) tests/test_*cli* tests/test_*command*

test-hooks: ## Test hook functionality only
	$(PYTHON) -m pytest $(PYTEST_FLAGS) tests/test_*hook*

install-hooks: ## Install git hooks (pre-commit with auto-formatting)
	@echo "🔧 Installing git hooks..."
	@if [ ! -d ".git" ]; then \
		echo "❌ Not a git repository"; \
		exit 1; \
	fi
	@cp hooks/pre-commit .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "✅ Pre-commit hook installed successfully!"
	@echo "  🎨 Auto-formats code and runs linting before commits"
	@echo "💡 To bypass: git commit --no-verify"