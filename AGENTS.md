# Repository Agent Rules

This repo has repo-local architecture enforcement. Use it.

## Repository metadata and review attribution

Do not add assistant/vendor branding to branch names, commit messages, issue or
PR titles, changelog entries, or promotional repository metadata.

Canonical Ground Control review, finding, decision, readiness and final-report
records may identify the reviewer engine. The required review attestation in a
PR body's Ground Control Checks section may also name that engine (for example,
"Pre-push Codex review completed; all findings fixed or dispositioned"). Keep the
identifier confined to that factual review attestation; this exception does not
permit promotional wording, generated-by footers or AI co-author trailers.

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
  - `CTF-*`: capture-the-flag platform requirements
  - `PLAT-*`: platform / cloud / portal infrastructure requirements
  - `GEN-*`: general / cross-cutting requirements
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

**Caveat:** `gc_create_github_issue`'s auto-link uses `IMPLEMENTS`,
which the API rejects on `DRAFT` requirements. If you're filing a
tracking issue against a `DRAFT` requirement, transition it to `ACTIVE`
when implementation starts or create a `DOCUMENTS`/`GITHUB_ISSUE` link
with the currently available traceability link tool before final
reconciliation.

## Architectural Defaults

- Private scenario packs and their adapters belong in their owning repositories.
  Never copy private pack content, topology, answers, guest scripts, image recipes,
  credentials, or scenario-specific infrastructure into this repository.
- Public issues, PRs, review records, plans, and documentation describe generic
  Shifter behavior using synthetic examples. Do not include private pack names,
  repository locations, domains, asset names, or operational details, even when
  these already appear in historical material. Keep private reproduction evidence
  in the private owning repository. Existing disclosure is not permission to
  repeat it.
- Core code must not branch on a pack name, image alias, guest/container name, or
  other private scenario identity. External adapters consume the published SDK;
  they must not import application internals. A pack cannot authorize executable
  adapter installation. Use explicit administrator-managed adapter bindings.

- Cross-layer access goes through service boundaries.
- Shared contracts live under `shared`.
- `cyberscript` is retired and no layer may import it. Shifter-owned lifecycle,
  authorization, persistence, and wire contracts live natively under `shared`;
  scenario authoring and provisioning intent use the pinned RAES contract.
- Do not weaken CI or local enforcement silently.
- If a rule needs an exception, record it in `docs/adr/exceptions.yaml` with an owner and expiry.
- Guardrail-file changes should also update the ADR enforcement docs or registry in the same change.

## External pack ownership

Private and third-party packs own their scenario content, adapters, image recipes,
guest scripts, answer material, operational evidence, and cloud-specific pack
configuration. Keep those assets in the owner's repository. Core changes must use
the public adapter SDK, typed runtime capabilities, and synthetic fixtures; never
branch on pack names, image aliases, container names, domains, or private identities.

Do not copy private pack names, details, logs, repository links, or acceptance
evidence into public issues, pull requests, comments, commit metadata, or release
notes. Describe shared defects through a synthetic reproduction. Keep private
acceptance records in the owner's repository. This applies even when private
material is visible in a neighboring checkout or earlier issue history.

Tenant organization administrators may install their own conforming adapters and
packs through the tenant UI. Executable adapters run through the isolated plugin
worker boundary; core must not import pack code or install it into the portal or
provisioner process. A compatibility probe alone does not qualify a live range.
