# Repository Agent Rules

This repo has repo-local architecture enforcement. Use it.

## Ground Control Context

This repo's Ground Control project is `shifter` (id
`df4e718f-1f67-46f8-a375-3ba53fabc9c4`). Requirement UIDs use the
prefixes `CTF-`, `PLAT-`, and `GEN-` depending on subsystem. The
workflow config and plan rules live in `.ground-control.yaml` at repo
root, with the full plan rules set in `.gc/plan-rules.md`. Agents read
it via the `gc_get_repo_ground_control_context` MCP tool, which
returns the full workflow config in a single call.

The authoritative list of "plans MUST..." constraints for the
`/implement` skill planning phase lives in `.gc/plan-rules.md`.

## Canonical GitHub Repository

The canonical GitHub repository for this checkout is
`Brad-Edwards/shifter`, as configured by `.ground-control.yaml`
(`github_repo`). Use that repository for all `gh`, GitHub API, PR, issue,
CI, Ground Control, and traceability operations.

Do not use `PaloAltoNetworks/shifter` unless the user explicitly requests
that repository in the current turn. Extra remotes, fork history, or
user-level skills do not override `.ground-control.yaml`.

## Required Checks

Before declaring work complete for changes touching architecture, workflows, hooks, or `shifter/shifter_platform`, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

When the change touches the relevant subsystem, run the stack-native checker too:

```bash
cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
actionlint
kube-linter lint --config .kube-linter.yaml platform/k8s/
kubeconform -strict -summary -ignore-missing-schemas -kubernetes-version 1.31.0 platform/k8s/gcp/base/*.yaml
```

For local edits or targeted validation:

```bash
python3 scripts/adr_guard/adr_guard.py --files <path> --level fast
```

## ADR Sources

The machine-readable ADR registry lives in:

- `docs/adr/index.yaml`
- `docs/adr/exceptions.yaml`

If you add or change a guardrail, architecture rule, or exception, update the ADR docs in the same change.

## Guardrail Files

Changes to these files are architecture work and must stay documented:

- `.github/workflows/**`
- `.github/CODEOWNERS`
- `.github/pull_request_template.md`
- `.github/copilot-instructions.md`
- `.github/dependabot.yml`
- `.pre-commit-config.yaml`
- `.ground-control.yaml`
- `.gc/plan-rules.md`
- `.shifter.yaml`
- `AGENTS.md`
- `.importlinter`
- `.tflint.hcl`
- `.gitleaks.toml`
- `.kube-linter.yaml`
- `.claude/settings.json`
- `.claude/hooks/**`
- `scripts/adr_guard/**`
- `docs/adr/**`

## Ground Control

All requirements management uses the Ground Control MCP server against the `shifter` project (id `df4e718f-1f67-46f8-a375-3ba53fabc9c4`).

- **Requirement UIDs** use subsystem prefixes:
  - `CTF-*` — capture-the-flag platform requirements
  - `PLAT-*` — platform / cloud / portal infrastructure requirements
  - `GEN-*` — general / cross-cutting requirements
- **Traceability link types**: `IMPLEMENTS` (requirement → code; only valid on `ACTIVE` requirements), `TESTS` (requirement → test), `DOCUMENTS` (requirement → tracking GH issue; works on `DRAFT`), `GITHUB_ISSUE` (alternative for issue references).
- **Requirement statuses**: `DRAFT` → `ACTIVE` → `ARCHIVED` / `DEPRECATED`. Transition to `ACTIVE` once implementation starts; only `ACTIVE` requirements accept `IMPLEMENTS` links.
- **Repo context**: `gc_get_repo_ground_control_context` reads
  `.ground-control.yaml` and inlines `.gc/plan-rules.md`; start there
  before issue workflows.
- **Requirement tools**: `gc_requirement` handles
  list/create/update/delete/archive/clone; `gc_transition_status` and
  `gc_bulk_transition_status` handle status transitions.
- **Traceability tools**: `gc_get_traceability`,
  `gc_get_traceability_by_artifact`, `gc_assert_traceability_reconciled`,
  and the current `link_create`/`link_delete` surfaces exposed by the
  relevant Ground Control entity tools.
- **Issue/PR workflow tools**: `gc_create_github_issue`,
  `gc_render_pr_body`, `gc_post_final_report`,
  `gc_close_issue_after_merge`, and `gc_integration_manager`.

**Caveat** — `gc_create_github_issue`'s auto-link uses `IMPLEMENTS`,
which the API rejects on `DRAFT` requirements. If you're filing a
tracking issue against a `DRAFT` requirement, transition it to `ACTIVE`
when implementation starts or create a `DOCUMENTS`/`GITHUB_ISSUE` link
with the currently available traceability link tool before final
reconciliation.

## Architectural Defaults

- Cross-layer access goes through service boundaries.
- Shared contracts live under `shared`.
- Do not weaken CI or local enforcement silently.
- If a rule needs an exception, record it in `docs/adr/exceptions.yaml` with an owner and expiry.
- Guardrail-file changes should also update the ADR enforcement docs or registry in the same change.
