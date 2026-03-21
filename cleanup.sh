#!/usr/bin/env bash
# ARCHON Project Cleanup Script
# Removes accumulated test artifacts, cache directories, and temporary files

set -e

echo "=== ARCHON Cleanup Script ==="
echo ""

# Count files before cleanup
BEFORE_FILES=$(find . -type f | wc -l)
BEFORE_SIZE=$(du -sh . 2>/dev/null | cut -f1)

echo "Before cleanup: $BEFORE_FILES files, $BEFORE_SIZE total size"
echo ""

# Remove pytest cache directories
echo "Removing pytest cache directories..."
find . -type d -name "pytest-cache-files-*" -exec rm -rf {} + 2>/dev/null || true
find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true

# Remove test temp directories
echo "Removing test temp directories..."
find . -type d -name "_tmp_*" -exec rm -rf {} + 2>/dev/null || true

# Remove old virtual environments (keep .venv if it exists in root)
echo "Removing old virtual environments..."
rm -rf .venv-ci .venv-linux-ci .venv-codex-ci .venv-py314-backup 2>/dev/null || true

# Remove Python cache
echo "Removing Python cache..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true

# Remove build artifacts
echo "Removing build artifacts..."
rm -rf dist/ build/ *.egg-info/ 2>/dev/null || true

# Remove coverage files
echo "Removing coverage files..."
rm -f .coverage coverage.xml 2>/dev/null || true

# Remove old SQLite databases from tests (keep root-level production DBs)
echo "Removing test SQLite databases..."
find ./tests -name "*.sqlite3" -delete 2>/dev/null || true
find ./tests -name "*.db" -delete 2>/dev/null || true

# Remove validation config artifacts
echo "Removing validation config artifacts..."
rm -f validate-config-*.yaml 2>/dev/null || true

# Remove vision audit directories
echo "Removing vision audit directories..."
find . -type d -name "vision-audit-*" -exec rm -rf {} + 2>/dev/null || true

# Remove artifacts directory contents (keep the directory)
echo "Cleaning artifacts directory..."
rm -rf .artifacts/* 2>/dev/null || true

# Remove CI repro directory
echo "Removing CI repro directory..."
rm -rf .ci-repro 2>/dev/null || true

# Remove AI terminal state
echo "Removing AI terminal state..."
rm -f .ai-terminal-state.json 2>/dev/null || true

# Remove tmp directories
echo "Removing tmp directories..."
rm -rf .tmp/ .tmp-runtime-tests/ 2>/dev/null || true

# Count files after cleanup
AFTER_FILES=$(find . -type f | wc -l)
AFTER_SIZE=$(du -sh . 2>/dev/null | cut -f1)

echo ""
echo "=== Cleanup Complete ==="
echo "After cleanup: $AFTER_FILES files, $AFTER_SIZE total size"
echo "Removed: $((BEFORE_FILES - AFTER_FILES)) files"
echo ""
echo "Note: Production SQLite databases in root directory are preserved."
echo "      Run 'python -m archon.validate_config' to regenerate config if needed."
