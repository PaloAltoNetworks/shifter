#!/bin/bash
# Setup script for git worktrees
# Creates symlinks to shared venvs from the main repo

MAIN_REPO="/home/atomik/src/shifter"
WORKTREE_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"

if [ -z "$WORKTREE_ROOT" ]; then
    echo "Error: Not in a git repository"
    exit 1
fi

if [ "$WORKTREE_ROOT" = "$MAIN_REPO" ]; then
    echo "Error: This script is for worktrees, not the main repo"
    exit 1
fi

echo "Setting up worktree: $WORKTREE_ROOT"

# Portal venv
if [ -L "$WORKTREE_ROOT/portal/.venv" ]; then
    echo "portal/.venv symlink already exists"
elif [ -d "$WORKTREE_ROOT/portal/.venv" ]; then
    echo "Removing empty portal/.venv directory..."
    rm -rf "$WORKTREE_ROOT/portal/.venv"
    ln -s "$MAIN_REPO/portal/.venv" "$WORKTREE_ROOT/portal/.venv"
    echo "Created portal/.venv symlink"
elif [ -d "$WORKTREE_ROOT/portal" ]; then
    ln -s "$MAIN_REPO/portal/.venv" "$WORKTREE_ROOT/portal/.venv"
    echo "Created portal/.venv symlink"
fi

# Shifter-engine venv (if it exists in main repo)
if [ -d "$MAIN_REPO/shifter-engine/.venv" ]; then
    if [ -L "$WORKTREE_ROOT/shifter-engine/.venv" ]; then
        echo "shifter-engine/.venv symlink already exists"
    elif [ -d "$WORKTREE_ROOT/shifter-engine/.venv" ]; then
        echo "Removing empty shifter-engine/.venv directory..."
        rm -rf "$WORKTREE_ROOT/shifter-engine/.venv"
        ln -s "$MAIN_REPO/shifter-engine/.venv" "$WORKTREE_ROOT/shifter-engine/.venv"
        echo "Created shifter-engine/.venv symlink"
    elif [ -d "$WORKTREE_ROOT/shifter-engine" ]; then
        ln -s "$MAIN_REPO/shifter-engine/.venv" "$WORKTREE_ROOT/shifter-engine/.venv"
        echo "Created shifter-engine/.venv symlink"
    fi
fi

# Node modules (for stylelint, prettier, etc.)
if [ -f "$WORKTREE_ROOT/package.json" ]; then
    if [ -d "$WORKTREE_ROOT/node_modules" ]; then
        echo "node_modules already exists"
    else
        echo "Installing node modules..."
        (cd "$WORKTREE_ROOT" && npm install)
        echo "Installed node modules"
    fi
fi

echo "Done"
