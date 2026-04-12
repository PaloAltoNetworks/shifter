# Repository Agent Rules

This repo has repo-local architecture enforcement. Use it.

## Required Checks

Before declaring work complete for changes touching architecture, workflows, hooks, or `shifter/shifter_platform`, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

When the change touches the relevant subsystem, run the stack-native checker too:

```bash
cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter
cd platform/terraform && tflint --recursive --config ../../.tflint.hcl
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
- `.pre-commit-config.yaml`
- `.importlinter`
- `.tflint.hcl`
- `.gitleaks.toml`
- `.kube-linter.yaml`
- `.claude/settings.json`
- `.claude/hooks/**`
- `scripts/adr_guard/**`
- `docs/adr/**`

## Ground Control

All requirements management uses the Ground Control MCP server against the `aphelion` project.

- **Requirement UIDs** use the `GC-` prefix (e.g., `GC-42`).
- **Traceability link types**: `IMPLEMENTS` (requirement → code), `TESTS` (requirement → test), `GITHUB_ISSUE` (requirement → issue).
- **Requirement statuses**: `DRAFT` → `ACTIVE`. Transition to `ACTIVE` once implemented.
- **MCP tools**: `gc_get_requirement`, `gc_get_traceability`, `gc_create_github_issue`, `gc_create_traceability_link`, `gc_transition_status`.

## Architectural Defaults

- Cross-layer access goes through service boundaries.
- Shared contracts live under `shared`.
- Do not weaken CI or local enforcement silently.
- If a rule needs an exception, record it in `docs/adr/exceptions.yaml` with an owner and expiry.
- Guardrail-file changes should also update the ADR enforcement docs or registry in the same change.
