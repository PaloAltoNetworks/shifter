#!/usr/bin/env bash
#
# Sync per-environment deploy overlays into the matching GitHub Actions secrets.
#
# Since #1250 the AWS/GCP deploy workflows render each environment's real
# Terraform values from GitHub secrets (TF_VARS_<ENV>_PORTAL / _RANGE / _CORE
# and SHIFTER_CONFIG_<ENV>_RANGE / SHIFTER_CONFIG_GCP_DEV) into a gitignored
# local.auto.tfvars at deploy time. Operators keep the same values as local
# `local.auto.tfvars` overlays (used for local `terraform` and symlinked into
# worktrees by scripts/setup-worktree.sh). This script is the repeatable bridge
# between those local overlays and the secrets, so the running deployment size
# and config stop drifting from a hand-edited secret. See
# docs/dev/deploy-secrets.md.
#
# It never prints secret contents: only names, source paths, and byte counts.
#
# Requires the `gh` CLI, authenticated with repo admin (secret write) scope.

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/sync-deploy-secrets.sh --env ENV [--env ENV ...] [options]

Push the local deploy overlays for the selected environments into their
matching GitHub Actions secrets with `gh secret set`.

Required:
  --env ENV            Environment to sync. Repeatable. One of:
                       dev, prod, proof, gcp-dev, or `all` (= dev prod proof).
                       gcp-dev must be named explicitly; it is not in `all`.

Options:
  --stack STACK        Stack to sync. Repeatable. One of:
                       portal, range, core, config, or `all`.
                       Default: portal range core (the tfvars overlays).
                       `config` syncs SHIFTER_CONFIG_* from --shifter-config.
  --shifter-config P   Path to the deployment shifter.yaml. Required when a
                       `config` stack is selected. Falls back to $SHIFTER_CONFIG.
  --repo OWNER/NAME    Target repository. Default: current repo (`gh repo view`).
  --dry-run            Print what would be set (name, source, size) and exit 0
                       without writing any secret.
  -h, --help           Show this help.

Source mapping (relative to the repo root):
  TF_VARS_<ENV>_PORTAL       platform/terraform/environments/<env>/portal/local.auto.tfvars
  TF_VARS_<ENV>_RANGE        platform/terraform/environments/<env>/range/local.auto.tfvars
  TF_VARS_<ENV>_CORE         platform/terraform/environments/<env>/local.auto.tfvars
  SHIFTER_CONFIG_<ENV>_RANGE --shifter-config (the deployment shifter.yaml)
  SHIFTER_CONFIG_GCP_DEV     --shifter-config (the deployment shifter.yaml)

A required source file that is missing is a hard error (fail loud), so a
partial overlay never silently skips a secret.

Examples:
  scripts/sync-deploy-secrets.sh --env dev --dry-run
  scripts/sync-deploy-secrets.sh --env dev
  scripts/sync-deploy-secrets.sh --env dev --stack config --shifter-config ./shifter.yaml
  scripts/sync-deploy-secrets.sh --env all --stack all --shifter-config ./shifter.yaml
EOF
}

# Which (env, stack) pairs actually have a secret, and how each secret's source
# is resolved. Keep this in step with the `env:` blocks in
# .github/workflows/_shifter-platform.yml, _core.yml, _range.yml, _gcp-dev.yml
# and the table in docs/dev/deploy-secrets.md.
#
# Records: "ENV STACK SECRET_NAME KIND", where KIND is `tfvars` (source is the
# stack's local.auto.tfvars) or `shifter` (source is --shifter-config).
KNOWN_RECORDS=(
  "dev   portal TF_VARS_DEV_PORTAL        tfvars"
  "prod  portal TF_VARS_PROD_PORTAL       tfvars"
  "proof portal TF_VARS_PROOF_PORTAL      tfvars"
  "dev   range  TF_VARS_DEV_RANGE         tfvars"
  "prod  range  TF_VARS_PROD_RANGE        tfvars"
  "proof range  TF_VARS_PROOF_RANGE       tfvars"
  "dev   core   TF_VARS_DEV_CORE          tfvars"
  "prod  core   TF_VARS_PROD_CORE         tfvars"
  "proof core   TF_VARS_PROOF_CORE        tfvars"
  "dev     config SHIFTER_CONFIG_DEV_RANGE   shifter"
  "prod    config SHIFTER_CONFIG_PROD_RANGE  shifter"
  "proof   config SHIFTER_CONFIG_PROOF_RANGE shifter"
  "gcp-dev config SHIFTER_CONFIG_GCP_DEV     shifter"
)

DEFAULT_STACKS=(portal range core)

ENVS=()
STACKS=()
REPO=""
DRY_RUN=0
SHIFTER_CONFIG="${SHIFTER_CONFIG:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)
      [[ $# -ge 2 ]] || { echo "error: --env needs a value" >&2; exit 2; }
      if [[ "$2" == "all" ]]; then ENVS+=(dev prod proof); else ENVS+=("$2"); fi
      shift 2 ;;
    --stack)
      [[ $# -ge 2 ]] || { echo "error: --stack needs a value" >&2; exit 2; }
      if [[ "$2" == "all" ]]; then STACKS+=(portal range core config); else STACKS+=("$2"); fi
      shift 2 ;;
    --shifter-config)
      [[ $# -ge 2 ]] || { echo "error: --shifter-config needs a value" >&2; exit 2; }
      SHIFTER_CONFIG="$2"; shift 2 ;;
    --repo)
      [[ $# -ge 2 ]] || { echo "error: --repo needs a value" >&2; exit 2; }
      REPO="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ ${#ENVS[@]} -eq 0 ]]; then
  echo "error: at least one --env is required (dev, prod, proof, gcp-dev, or all)" >&2
  usage >&2
  exit 2
fi
if [[ ${#STACKS[@]} -eq 0 ]]; then
  STACKS=("${DEFAULT_STACKS[@]}")
fi

command -v gh >/dev/null 2>&1 || { echo "error: the 'gh' CLI is required" >&2; exit 1; }

REPO_ROOT="$(git rev-parse --show-toplevel)"

if [[ -z "$REPO" ]]; then
  REPO="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"
fi

contains() {
  local needle="$1"; shift
  local item
  for item in "$@"; do [[ "$item" == "$needle" ]] && return 0; done
  return 1
}

# Resolve the source file for a record. Echoes the path; exits non-zero (with a
# message on stderr) when the source cannot be resolved.
source_for() {
  local env="$1" stack="$2" kind="$3"
  case "$kind" in
    tfvars)
      case "$stack" in
        core)  echo "$REPO_ROOT/platform/terraform/environments/$env/local.auto.tfvars" ;;
        *)     echo "$REPO_ROOT/platform/terraform/environments/$env/$stack/local.auto.tfvars" ;;
      esac ;;
    shifter)
      if [[ -z "$SHIFTER_CONFIG" ]]; then
        echo "error: --shifter-config (or \$SHIFTER_CONFIG) is required to sync $stack secrets" >&2
        return 1
      fi
      echo "$SHIFTER_CONFIG" ;;
    *) echo "error: unknown source kind: $kind" >&2; return 1 ;;
  esac
}

planned=0
set_count=0
for record in "${KNOWN_RECORDS[@]}"; do
  # shellcheck disable=SC2086 # deliberate word-split of the space-delimited record
  set -- $record
  r_env="$1" r_stack="$2" r_secret="$3" r_kind="$4"

  contains "$r_env" "${ENVS[@]}" || continue
  contains "$r_stack" "${STACKS[@]}" || continue

  planned=1
  src="$(source_for "$r_env" "$r_stack" "$r_kind")"
  if [[ ! -f "$src" ]]; then
    echo "error: missing source for $r_secret: $src" >&2
    exit 1
  fi
  bytes="$(wc -c <"$src" | tr -d ' ')"

  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] would set $r_secret from ${src#"$REPO_ROOT/"} (${bytes} bytes) in $REPO"
  else
    echo "setting $r_secret from ${src#"$REPO_ROOT/"} (${bytes} bytes) in $REPO"
    gh secret set "$r_secret" --repo "$REPO" <"$src"
    set_count=$((set_count + 1))
  fi
done

if [[ "$planned" -eq 0 ]]; then
  echo "error: no known secrets match the selected --env/--stack combination" >&2
  exit 1
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "dry-run complete; no secrets written."
else
  echo "done; ${set_count} secret(s) set in $REPO."
fi
