# ADR Enforcement

Architecture rules in this repo are enforced by tooling, not just prose.

## What Exists

The current enforcement stack has six parts:

1. `docs/adr/index.yaml`
   Machine-readable ADR registry. Each accepted ADR lists the rules and the checks that enforce them.

2. `docs/adr/exceptions.yaml`
   Explicit exceptions. If a rule needs a temporary waiver, record it here with an owner and expiry instead of leaving the exception implicit.

3. `scripts/adr_guard/adr_guard.py`
   Repo-native policy runner. This is the entrypoint for ADR conformance checks.

4. `.pre-commit-config.yaml`
   Fast local enforcement. The ADR guard runs before commit so architectural drift is caught locally.

5. `.github/workflows/_quality.yml`
   CI enforcement. ADR conformance runs as its own architecture gate.

6. Existing ecosystem tooling
   - `import-linter` for Python package contracts
   - `actionlint` for GitHub Actions workflows
   - `TFLint` for Terraform linting
   - `gitleaks` for new secret leakage detection

There is also agent-specific wiring:

- `.claude/hooks/adr_guard_hook.py` runs the ADR guard after Claude edits files.
- `.claude/skills/adr-check/SKILL.md` provides a default workflow for ADR conformance work.
- `.claude/skills/architecture-review/SKILL.md` provides a repo-specific architecture review checklist.
- `AGENTS.md` gives Codex a repo-local policy file.

Review controls:

- `.github/CODEOWNERS` requires review on guardrail files and shared/public architecture seams.
- `.github/pull_request_template.md` requires an ADR impact section on PRs.
- `.github/copilot-instructions.md` now points GitHub Copilot toward the same ADR enforcement model.

## Current Checks

The first slice intentionally stays small:

- `adr-registry`
  Validates the ADR registry and exception files.

- `layer-imports`
  Enforces the existing cross-layer import policy from `scripts/check_layer_imports/layer_imports.yaml`.

- `guardrail-docs`
  Requires guardrail changes to update ADR or developer docs in the same change.

- `cross-layer-model-imports`
  Fails on direct cross-layer model imports inside service layers. The current tree already satisfies this rule, so it is part of the default guard.

- `import-linter`
  Adds package-level forbidden-import contracts across the main Django app layers.

- `actionlint`
  Lints GitHub Actions workflows beyond plain YAML validation.

- `TFLint`
  Adds Terraform linting on top of `terraform fmt` and `terraform validate`.
  The initial profile is intentionally narrow: it leaves existing repo-wide
  debt rules disabled so the new gate enforces signal instead of legacy noise.

- `gitleaks`
  Scans newly introduced commits for likely secrets, with a small repo config for approved false positives.

## Local Usage

Run the fast profile on the full repo:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level fast
```

Run the CI profile:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Useful ecosystem checks:

```bash
cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
actionlint
```

Run on specific files:

```bash
python3 scripts/adr_guard/adr_guard.py --files .github/workflows/_quality.yml --level fast
```

Run on staged or modified files:

```bash
python3 scripts/adr_guard/adr_guard.py --changed --level fast
```

## How To Add A Rule

1. Add or update the ADR entry in `docs/adr/index.yaml`.
2. Implement the check in `scripts/adr_guard/adr_guard.py`.
3. Decide where it belongs:
   - fast local gate
   - CI gate
   - Claude post-edit hook
   - agent policy docs
4. If the rule cannot be enforced immediately, add a dated exception to `docs/adr/exceptions.yaml`.

## Exceptions

Use exceptions sparingly. They are for temporary, explicit waivers only.

Required fields:

- `rule_id`
- `owner`
- `reason`
- `expires_on`

Optional narrowing fields:

- `checks`
- `paths`

Expired exceptions fail `adr_guard`, so they cannot linger unnoticed.

## Design Constraints

- Keep the default local gate fast.
- Do not rely on external dependencies for the core ADR guard.
- Prefer explicit exceptions over hidden tolerances.
- Do not make CI architecture checks skippable through the normal test-skip path.
- Keep review friction focused on guardrail files, not on ordinary feature code.
