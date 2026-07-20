#!/bin/bash
# Install guarded Claude Code autostart for interactive range terminal sessions (#180).
set -euo pipefail

install_claude_autostart() {
  local -a rc_files=("$@")

  if ((${#rc_files[@]} == 0)); then
    echo "install_claude_autostart: at least one rc file is required" >&2
    return 1
  fi

  cat > /etc/profile.d/shifter-claude-autostart.sh << 'EOF'
# Shifter Claude Code autostart (#180) — invoked from guarded interactive shell hooks.
_shifter_claude_autostart() {
  if [[ $- != *i* ]] || [[ ! -t 0 ]]; then
    return 0
  fi
  if [[ -n "${SHIFTER_SKIP_CLAUDE_AUTOSTART:-}" ]]; then
    return 0
  fi
  if [[ -n "${SHIFTER_CLAUDE_AUTOSTART_DONE:-}" ]]; then
    return 0
  fi
  case "$(id -un)" in
    kali|ubuntu) ;;
    *) return 0 ;;
  esac
  if ! command -v claude >/dev/null 2>&1; then
    return 0
  fi
  export SHIFTER_CLAUDE_AUTOSTART_DONE=1
  if ! claude --dangerously-skip-permissions; then
    echo "Shifter: Claude Code exited with status $?; shell continues." >&2
  fi
}
EOF

  for rc in "${rc_files[@]}"; do
    mkdir -p "$(dirname "$rc")"
    touch "$rc"
    if grep -q 'SHIFTER_CLAUDE_AUTOSTART_HOOK' "$rc" 2>/dev/null; then
      continue
    fi
    cat >> "$rc" << 'EOF'

# SHIFTER_CLAUDE_AUTOSTART_HOOK (#180)
if [[ $- == *i* ]] && [[ -t 0 ]] && [[ -f /etc/profile.d/shifter-claude-autostart.sh ]]; then
  # shellcheck source=/dev/null
  . /etc/profile.d/shifter-claude-autostart.sh
  _shifter_claude_autostart
fi
EOF
  done

  if grep -q 'SHIFTER_CLAUDE_AUTOSTART_HOOK' /etc/bash.bashrc 2>/dev/null; then
    return 0
  fi

  cat >> /etc/bash.bashrc << 'EOF'

# SHIFTER_CLAUDE_AUTOSTART_HOOK (#180)
if [[ $- == *i* ]] && [[ -t 0 ]] && [[ -f /etc/profile.d/shifter-claude-autostart.sh ]]; then
  # shellcheck source=/dev/null
  . /etc/profile.d/shifter-claude-autostart.sh
  _shifter_claude_autostart
fi
EOF
}

SHIFTER_CLAUDE_AUTOSTART_LIB="/usr/local/lib/shifter/claude-autostart-install.sh"

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  mkdir -p "$(dirname "$SHIFTER_CLAUDE_AUTOSTART_LIB")"
  cp "${BASH_SOURCE[0]}" "$SHIFTER_CLAUDE_AUTOSTART_LIB"
  chmod 755 "$SHIFTER_CLAUDE_AUTOSTART_LIB"
fi
