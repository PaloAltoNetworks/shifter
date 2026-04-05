#!/bin/bash
# Auto-format Python files with ruff after Edit/Write
FILE_PATH=$(jq -r '.tool_input.file_path // empty')

# Only format Python files within shifter_platform
if [[ "$FILE_PATH" == *.py ]] && [[ "$FILE_PATH" == *shifter_platform* ]]; then
    VENV="$(dirname "$(dirname "$FILE_PATH")")"
    # Walk up to find .venv
    while [[ "$VENV" != "/" ]]; do
        if [[ -x "$VENV/.venv/bin/ruff" ]]; then
            "$VENV/.venv/bin/ruff" format "$FILE_PATH" 2>/dev/null
            exit 0
        fi
        VENV="$(dirname "$VENV")"
    done
fi
exit 0
