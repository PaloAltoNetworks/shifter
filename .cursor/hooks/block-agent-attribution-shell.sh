#!/usr/bin/env bash
# Deny shell commands that inject AI/agent attribution into git or GitHub artifacts.
set -euo pipefail

input=$(cat)
command=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("command",""))')

deny() {
  local reason=$1
  python3 -c 'import json,sys; print(json.dumps({
    "permission": "deny",
    "user_message": sys.argv[1],
    "agent_message": sys.argv[2],
  }))' \
    "Blocked: ${reason}" \
    "Do not inject AI/agent attribution into commits or PRs. Use plain human authorship only."
  exit 2
}

if [[ -z "$command" ]]; then
  python3 -c 'print("{\"permission\":\"allow\"}")'
  exit 0
fi

if [[ "$command" =~ git[[:space:]]+(commit|.*commit) ]]; then
  if [[ "$command" =~ --trailer[[:space:]]+.*(Co-authored-by|Co-Authored-By|Made-with:|cursoragent@) ]]; then
    deny "git commit --trailer with agent attribution"
  fi
fi

if [[ "$command" =~ gh[[:space:]]+pr[[:space:]]+(create|edit) ]]; then
  if [[ "$command" =~ [Mm]ade[[:space:]]+with[[:space:]]+\[Cursor\] ]] \
    || [[ "$command" =~ cursor\.com ]]; then
    deny "gh pr body/footer with Cursor marketing attribution"
  fi
fi

python3 -c 'print("{\"permission\":\"allow\"}")'
exit 0
