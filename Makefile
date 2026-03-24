# ARCHON Makefile
# Common development tasks for the ARCHON project

.PHONY: help clean install dev test lint typecheck format check serve chat docs

# Default target
help:
	@echo "ARCHON Development Commands"
	@echo ""
	@echo "  make clean       - Remove test artifacts, caches, and temp files"
	@echo "  make install     - Install ARCHON in development mode"
	@echo "  make dev         - Install with dev dependencies"
	@echo "  make test        - Run test suite"
	@echo "  make test-cov    - Run tests with coverage"
	@echo "  make lint        - Run linter (ruff)"
	@echo "  make typecheck   - Run type checker (mypy)"
	@echo "  make format      - Format code with black"
	@echo "  make check       - Run all checks (lint + typecheck + test)"
	@echo "  make serve       - Start API server"
	@echo "  make chat        - Start interactive chat TUI"
	@echo "  make validate    - Validate configuration"
	@echo ""

# Clean up test artifacts and caches
clean:
	@echo "Cleaning project..."
	@bash cleanup.sh
	@echo "Done."

# Install in development mode
install:
	@echo "Installing ARCHON..."
	@if command -v py >/dev/null 2>&1; then \
		py -3 -m pip install -e .; \
	else \
		python3 -m pip install -e .; \
	fi
	@echo "Done. Run 'archon' to verify installation."

# Install with dev dependencies
dev:
	@echo "Installing ARCHON with dev dependencies..."
	@if command -v py >/dev/null 2>&1; then \
		py -3 -m pip install -e ".[dev]"; \
	else \
		python3 -m pip install -e ".[dev]"; \
	fi
	@echo "Done."

# Run tests
test:
	@echo "Running tests..."
	@pytest --import-mode=importlib

# Run tests with coverage
test-cov:
	@echo "Running tests with coverage..."
	@pytest --import-mode=importlib --cov=archon --cov-report=term-missing

# Run linter
lint:
	@echo "Running linter..."
	@ruff check archon/ tests/

# Run type checker
typecheck:
	@echo "Running type checker..."
	@mypy archon/

# Format code
format:
	@echo "Formatting code..."
	@black archon/ tests/

# Run all checks
check: lint typecheck test
	@echo "All checks passed!"

# Start API server
serve:
	@echo "Starting API server..."
	@archon ops serve

# Start interactive chat
chat:
	@echo "Starting chat TUI..."
	@archon core chat

# Validate configuration
validate:
	@echo "Validating configuration..."
	@python -m archon.validate_config

# Create virtual environment
venv:
	@echo "Creating virtual environment..."
	@if command -v py >/dev/null 2>&1; then \
		py -3 -m venv .venv; \
	else \
		python3 -m venv .venv; \
	fi
	@echo "Done. Activate with: source .venv/bin/activate (Linux/macOS) or .venv\\Scripts\\activate (Windows)"

# Uninstall ARCHON
uninstall:
	@echo "Uninstalling ARCHON..."
	@archon uninstall --yes
