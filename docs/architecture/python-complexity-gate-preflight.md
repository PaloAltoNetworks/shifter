# Python Complexity Gate Preflight

Issue #1135 adds a hard per-function complexity gate using Ruff `C901`.
This is a guardrail change, not a new domain abstraction.

## Intended Boundary

- Reuse Ruff as the enforcement engine. Do not add an `adr_guard` complexity
  parser, a SonarCloud-only gate, or a custom AST scanner.
- Apply `C901` through the existing Python lint surface: package-local
  `pyproject.toml` Ruff configuration plus the existing Ruff pre-commit hooks
  and `_quality.yml` lint jobs.
- Keep the rule narrow. The change should add only McCabe complexity
  enforcement and the minimum exemption metadata needed for the current tree.
- Existing violations are debt, not precedent. Exemptions must be explicit and
  durable, with a backlog entry and a ratchet-down note.

## Canonical Incumbents

- `.pre-commit-config.yaml`: local Ruff hooks for `shifter/shifter_platform`,
  `shifter/engine/provisioner`, `shifter/packer`, `scripts/bootstrap`,
  `scripts/gcp`, `scripts/check_layer_imports`,
  `scripts/check_rds_pending_modifications`, and `shifter/installation`.
- `.github/workflows/_quality.yml`: required CI lint jobs that run
  `uv run ruff check .` and `uv run ruff format --check .` per Python package.
- Package-local `pyproject.toml` files: current Ruff settings live next to each
  package, not in a root config.
- `sonar-project.properties`: source inventory for SonarCloud. Sonar remains an
  advisory signal here; Ruff is the hard gate.
- `docs/adr/index.yaml` and `docs/adr/README.md`: architecture guardrail
  registry and enforcement docs. If the implementation changes enforcement
  files, ADR-002 requires matching ADR or developer documentation updates.
- `CHANGELOG.md`: durable user-facing release note for the threshold, backlog,
  and ratchet intent.

## Design Guardrails

- Prefer adding `C901` to each existing package-local Ruff config over adding a
  root config that may or may not be discovered from package working
  directories. If a root config is chosen, prove discovery from every
  pre-commit hook and every CI lint working directory.
- Use `extend-select = ["C901"]` only when the config otherwise relies on
  defaults. Existing package configs already use explicit `select = [...]`;
  in those files, add `"C901"` without widening the rule set.
- Set one repository threshold unless there is a documented, temporary reason
  for a package-specific threshold. `15` is the target; any higher initial value
  must be treated as a ratchet step, not the steady state.
- Prefer `per-file-ignores` for legacy backlog files when many functions in the
  same file exceed the threshold. Use per-function `# noqa: C901` only when it
  produces a clearer, smaller exemption list.
- Do not exempt tests by default. Tests under configured Ruff scopes should be
  held to the same per-function maintainability gate unless a specific test
  helper has a documented reason.
- Keep CI hard-failing on `ruff check`. The existing `--fix` pre-commit path is
  acceptable because complexity is not auto-fixed and Ruff still reports and
  fails on `C901`.

## Cross-Cutting Layers

- Security validators: this change touches lint configuration only. It must not
  weaken Bandit (`[tool.bandit]`, pre-commit, CI), gitleaks, Checkov, Terraform,
  Kubernetes, or ADR security checks.
- Config shape: Ruff options belong under `[tool.ruff.lint]` and
  `[tool.ruff.lint.mccabe]` in each canonical package config, or an explicitly
  verified shared Ruff config. Avoid duplicate threshold keys with conflicting
  values.
- OS/runtime exposure: no new commands should pass repository paths, secrets, or
  tokens through shell strings. Reuse the existing `uv run ruff check .` command
  shape and package working directories.
- Error envelopes and observability: not applicable to runtime behavior. The
  observable contract is developer feedback from Ruff and CI job failure.
- Workflow policy: `.pre-commit-config.yaml`, `_quality.yml`, and ADR docs are
  guardrail files. Any implementation edits there must run ADR guard and keep
  documentation in the same change.

## Extensibility

The required seam is the threshold value. It should be easy to ratchet from an
initial passing value toward `15` without reworking workflow logic. If
package-local configs remain canonical, keep the threshold value consistent and
searchable across those configs, and list the current exemption backlog in one
durable document or changelog entry.

The next likely extension is broadening or tightening the Python quality gate.
Do not bundle that with `C901`; new lint families, mypy strictness, or formatter
changes need separate justification and rollout.

## Non-Goals

- Refactoring existing high-complexity functions.
- Introducing new Python package layout, service boundaries, DTOs, repositories,
  exception hierarchies, or validation frameworks.
- Making SonarCloud the hard gate for complexity.
- Replacing pre-commit, `uv`, or package-local lint jobs.
- Solving non-Python complexity in JavaScript, Terraform, workflows, or
  Kubernetes manifests.
