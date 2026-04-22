#!/bin/bash
# Setup script for git worktrees
# Creates symlinks to shared venvs from the main repo

MAIN_REPO="/home/atomik/src/shifter"
WORKTREE_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"

if [[ -z "$WORKTREE_ROOT" ]]; then
    echo "Error: Not in a git repository"
    exit 1
fi

if [[ "$WORKTREE_ROOT" = "$MAIN_REPO" ]]; then
    echo "Error: This script is for worktrees, not the main repo"
    exit 1
fi

echo "Setting up worktree: $WORKTREE_ROOT"

# Helper: create or fix symlink
# Usage: ensure_symlink <target> <link_path> <description>
ensure_symlink() {
    local target="$1"
    local link_path="$2"
    local desc="$3"

    # Check if target exists
    if [[ ! -e "$target" ]]; then
        echo "Warning: $desc target does not exist: $target"
        return 1
    fi

    # Check parent directory exists
    local parent_dir
    parent_dir="$(dirname "$link_path")"
    if [[ ! -d "$parent_dir" ]]; then
        echo "Skipping $desc: parent directory does not exist"
        return 1
    fi

    # Valid symlink pointing to correct target
    if [[ -L "$link_path" ]] && [[ -e "$link_path" ]] && [[ "$(readlink "$link_path")" = "$target" ]]; then
        echo "$desc symlink already exists and is valid"
        return 0
    fi

    # Broken symlink - remove and recreate
    if [[ -L "$link_path" ]] && [[ ! -e "$link_path" ]]; then
        echo "Removing broken $desc symlink..."
        rm "$link_path"
    fi

    # Symlink pointing to wrong target - remove and recreate
    if [[ -L "$link_path" ]]; then
        echo "Fixing $desc symlink (wrong target)..."
        rm "$link_path"
    fi

    # Regular file or directory - remove and recreate
    if [[ -e "$link_path" ]]; then
        echo "Replacing $desc with symlink..."
        rm -rf "$link_path"
    fi

    # Create symlink
    ln -s "$target" "$link_path"
    echo "Created $desc symlink"
}

# Shifter platform venv
ensure_symlink \
    "$MAIN_REPO/shifter/shifter_platform/.venv" \
    "$WORKTREE_ROOT/shifter/shifter_platform/.venv" \
    "shifter/shifter_platform/.venv"

# Shifter platform .env file (for Django settings like DJANGO_SECRET_KEY)
ensure_symlink \
    "$MAIN_REPO/shifter/shifter_platform/.env" \
    "$WORKTREE_ROOT/shifter/shifter_platform/.env" \
    "shifter/shifter_platform/.env"

# Engine provisioner venv (if it exists in main repo)
ensure_symlink \
    "$MAIN_REPO/shifter/engine/provisioner/.venv" \
    "$WORKTREE_ROOT/shifter/engine/provisioner/.venv" \
    "shifter/engine/provisioner/.venv"

# Node modules (for stylelint, prettier, etc.)
if [[ -f "$WORKTREE_ROOT/package.json" ]]; then
    if [[ -d "$WORKTREE_ROOT/node_modules" ]]; then
        echo "node_modules already exists"
    else
        echo "Installing node modules..."
        (cd "$WORKTREE_ROOT" && npm install)
        echo "Installed node modules"
    fi
fi

echo "Done"
