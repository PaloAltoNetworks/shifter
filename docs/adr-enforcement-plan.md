# ADR Enforcement Plan

## Goal

Make architecture and engineering decisions executable:

- hard to violate by accident
- fast to verify locally
- required in CI
- visible in PR review
- embedded in Claude/Codex workflows

The rule is simple: if an ADR matters, it should not live only as prose.

## Current State

The repo already has useful enforcement primitives:

- [`CLAUDE.md`](../CLAUDE.md) establishes behavior and workflow constraints for Claude.
- [`.pre-commit-config.yaml`](../.pre-commit-config.yaml) has strong local quality gates.
- [`scripts/check_layer_imports/check_layer_imports.py`](../scripts/check_layer_imports/check_layer_imports.py) encodes one real architectural rule.
- [`scripts/check_layer_imports/layer_imports.yaml`](../scripts/check_layer_imports/layer_imports.yaml) provides a machine-readable boundary policy.
- [`.github/workflows/_quality.yml`](../.github/workflows/_quality.yml) runs lint, tests, SAST, and architecture checks in CI.
- [`.claude/settings.json`](../.claude/settings.json) supports pre/post tool hooks.

That said, the current system is still easy to drift from:

- Most architectural decisions are prose in docs, not machine-readable policy.
- Claude has only two active hooks, and neither checks ADR conformance.
- There is no Codex-specific repo policy file at all.
- Historical CI bypasses like `[skip quality]` and `[skip tests]` on `dev`
  have been removed from the deploy workflow; Quality now runs by default
  unless the diff is classified as ordinary docs-only.
- There is no `CODEOWNERS`, PR template, or ADR impact check.
- The architecture check surface is narrow: layer imports and FK checks only.
- There is no single source of truth that maps ADRs to concrete automated checks.

## Design Principle

Every important ADR should be represented in three forms:

1. Human-readable decision record.
2. Machine-readable policy entry.
3. Automated verification and/or scaffolding.

If you only have the first, drift is inevitable.

## Recommended Enforcement Stack

### 1. Create a machine-readable ADR registry

Add:

- `docs/adr/`
- `docs/adr/index.yaml`

Each ADR should include:

- `id`
- `title`
- `status`
- `scope`
- `decision`
- `rules`
- `exceptions`
- `enforcement`
- `evidence`

Example:

```yaml
- id: ADR-001
  title: Cross-layer access goes through service boundaries
  status: accepted
  scope: shifter_platform
  rules:
    - id: ADR-001-R1
      description: Non-shared cross-layer imports may only target `<layer>.services`
      enforcement:
        - pre_commit: adr-guard
        - ci: adr-conformance
        - hook: pre_tool_edit
    - id: ADR-001-R2
      description: Cross-layer DTOs live in `shared.schemas`
      enforcement:
        - ci: adr-guard
```

This is the pivot point. Once the registry exists, the repo can compile policy into hooks, CI checks, and review prompts.

### 2. Add one repo-native policy runner

Add:

- `scripts/adr_guard/`
- `scripts/adr_guard/adr_guard.py`

This should be a thin orchestrator that runs named checks and prints:

- violated rule id
- why it failed
- matching files/lines
- suggested fix

Checks should start small and opinionated:

- `layer-imports`
- `cross-layer-model-imports`
- `service-boundary`
- `domain-exception-hierarchy`
- `shared-contract-location`
- `migration-safety`
- `terraform-policy`
- `docs-impact`

Do not spread this across ad hoc scripts forever. One entrypoint makes local use, CI use, and AI hook use consistent.

### 3. Move from prose-only ADRs to executable checks

High-value rules for this repo:

- Cross-domain imports only through `*.services` and `shared`.
- No direct model imports across app boundaries.
- Shared request/response contracts live under `shared.schemas`.
- Domain-specific exceptions must inherit from the domain base exception.
- Views, management commands, Celery tasks, and consumers are orchestration only; business rules live in services or domain objects.
- New cross-layer seams require tests.
- Terraform changes to prod paths require stronger approval gates than dev.
- CI skip flags must not bypass architecture checks.

Existing files show you already believe several of these. They just are not enforced uniformly yet.

### 4. Make pre-commit the fast local gate

Extend [`.pre-commit-config.yaml`](../.pre-commit-config.yaml) with:

- `adr-guard --changed --level=fast`
- `adr-guard layer-imports`
- `adr-guard cross-layer-model-imports`
- `adr-guard domain-exception-hierarchy`

Keep local hooks fast. A good split is:

- `fast`: import boundaries, forbidden imports, metadata checks
- `medium`: Django management checks, contract checks
- `slow`: full tests and deeper scans

Conformance must be cheap enough that engineers do not want to bypass it.

### 5. Strengthen CI and remove soft bypasses for architecture

Change CI behavior:

- Add a dedicated required job: `adr-conformance`.
- Run it on every PR and on pushes to `dev` and `main`.
- Keep `[skip quality]` and `[skip tests]` style markers out of architecture
  and test routing.
- Keep test skips separate from architecture and policy skips.
- Mark architecture jobs as required branch protection checks.

For this repo specifically:

- `check-layer-imports-arch` and `model-fks-arch` should live under one visible architecture gate.
- `adr-conformance` should fail the PR if any accepted ADR rule is violated.

### 6. Add PR friction in the right place

Add:

- `.github/CODEOWNERS`
- `.github/pull_request_template.md`

The PR template should require:

- ADRs touched
- ADRs intentionally not affected
- new exception requested? yes/no
- if exception requested, link issue/ADR amendment

The template should not be essay-shaped. A short checklist is enough.

`CODEOWNERS` should require review for:

- `docs/adr/**`
- `scripts/adr_guard/**`
- `.github/workflows/**`
- `.pre-commit-config.yaml`
- `shifter/shifter_platform/shared/**`
- `shifter/shifter_platform/*/services.py`

This prevents silent weakening of the guardrails themselves.

Status:

- Implemented in this worktree with `.github/CODEOWNERS` and `.github/pull_request_template.md`.

### 7. Wire Claude hooks to repo policy

Current state: [`.claude/settings.json`](../.claude/settings.json) only wires `protect_files.sh` and `ruff_format.sh`.

Recommended additions:

- `PreToolUse(Edit|Write)`: block edits that would violate forbidden path/rule combinations.
- `PostToolUse(Edit|Write)`: run `adr-guard --files <edited files>`.
- `PreToolUse(Bash)`: block mutating repo commands that skip policy checks unless explicitly user-directed.
- `PostToolUse(Bash)`: when running tests/lint in guarded directories, surface missing architecture checks.

Useful hooks:

- `adr_pre_edit_guard.py`
- `adr_post_edit_check.py`
- `ci_bypass_guard.py`
- `service_boundary_guard.py`

Examples:

- If Claude edits `mission_control` and adds `from cms.models import ...`, fail immediately.
- If Claude touches `.github/workflows/` or `.pre-commit-config.yaml`, require an explicit note that enforcement code is being changed.
- If Claude adds a new cross-layer public seam, remind it to update the ADR registry and tests.

### 8. Add Codex repo instructions instead of relying on system prompt only

Add one or both:

- `AGENTS.md`
- `.codex/`

Codex-specific repo rules should mirror the Claude rules that matter operationally:

- architecture boundaries
- required local checks before completion
- forbidden bypasses
- when ADR updates are required
- how to run `adr-guard`

Without a repo-local Codex file, the policy lives outside the repo and will drift.

### 9. Create skills for “conforming work,” not just shipping work

Current Claude skills are workflow-heavy, but they do not enforce ADR conformance as a first-class step.

Add skills like:

- `adr-check`
- `adr-update`
- `architecture-review`
- `safe-cross-layer-change`

Each should do the same sequence:

1. identify affected ADR rules
2. run `adr-guard`
3. map changes to decision records
4. update ADR/evidence if needed
5. verify tests and traces

This makes the correct workflow the default workflow for agents.

### 10. Add a review bot for architectural deltas

In CI, add a comment bot that summarizes:

- changed layers
- new cross-layer imports
- new public service functions
- changes to shared schemas
- changes to workflows/guardrails
- ADR files added/changed/missing

This is not the primary enforcement. It is review compression so humans see the architectural delta quickly.

### 11. Make the compliant path easier than the non-compliant path

Add scaffolding:

- `scripts/new_service_boundary.py`
- `scripts/new_adr.py`
- `scripts/new_shared_contract.py`

Templates should produce:

- correct file placement
- correct exception base class
- stub tests
- traceability/update placeholders

Engineers drift when the compliant structure takes more effort than improvising.

### 12. Track exceptions explicitly

Do not allow “temporary” rule violations to hide in code.

Add:

- `docs/adr/exceptions.yaml`

Each exception should have:

- rule id
- owner
- reason
- created date
- expiry date
- removal issue

`adr-guard` should fail expired exceptions.

Status:

- Implemented in this worktree with `docs/adr/exceptions.yaml` plus expiry validation in `scripts/adr_guard/adr_guard.py`.

## Suggested Implementation Order

### Phase 1: High leverage, low disruption

- Add `docs/adr/index.yaml`
- Add `scripts/adr_guard/adr_guard.py`
- Add `adr-conformance` CI job
- Remove architecture bypass via skip flags
- Add Codex repo file (`AGENTS.md` or `.codex/`)
- Extend Claude hooks to run `adr-guard` on edited files

### Phase 2: Review and workflow hardening

- Add `CODEOWNERS`
- Add PR template with ADR impact checklist
- Add `adr-check` and `architecture-review` skills
- Add CI bot summary for architectural deltas

### Phase 3: Richer domain checks

- Add AST checks for service-boundary violations
- Add exception hierarchy checks
- Add shared contract location checks
- Add migration/invariant checks
- Add policy exception expiry enforcement

## Concrete First ADRs To Encode

If you only encode a few first, start here:

1. Service-layer boundaries.
2. Shared contract placement.
3. Domain exception hierarchy.
4. No CI architecture bypass.
5. Guardrail files require ownership/review.

These are broad, cheap to check, and prevent the most common accidental drift.

## Specific Repo Gaps Observed

- Claude has extra hook scripts in [`.claude/hooks`](../.claude/hooks), but several are not wired in [`.claude/settings.json`](../.claude/settings.json).
- Codex has no repo-local enforcement file.
- CI quality is strong, but architecture is still a small subset of total policy.
- CI currently allows skip flags in [`deploy.yml`](../.github/workflows/deploy.yml), which weakens “required by default” behavior.
- The architecture checker already exists, which means the repo has proven the pattern. The next step is to generalize it.

Status update:

- Implemented in this worktree with `import-linter`, `actionlint`, `TFLint`, and `gitleaks` added alongside the repo-native ADR guard.

## Definition Of Done

You know this is working when:

- a developer cannot add an invalid cross-layer dependency without failing locally
- an agent cannot casually bypass an architecture rule without being interrupted by hooks
- a PR touching architecture shows its ADR impact automatically
- weakening a guardrail requires explicit review
- exceptions are visible, owned, and time-bounded

At that point, ADR conformance is no longer a social preference. It is part of the toolchain.
