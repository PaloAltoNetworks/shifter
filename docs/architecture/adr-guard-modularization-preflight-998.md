# ADR Guard Modularization Preflight (#998)

Status: pre-implementation guidance

Date: 2026-07-29

Issue: GitHub #998, "Split adr_guard.py (~4.9k lines) into a package; the
enforcement tool should model the modularity it enforces."

This is a requirement-free maintenance change. The GitHub issue is the shipping
contract. This note fixes the compatibility, security, validation, and
repository-integration boundaries for the refactor; it is not an implementation
plan and does not change an ADR check.

## Current Baseline And Scope

The issue describes an older revision. `scripts/adr_guard/adr_guard.py` is now
about 7,060 lines and registers 29 named checks in `CHECKS`. Its effective
surface is wider than the CLI:

- `.pre-commit-config.yaml`, `.github/workflows/_quality.yml`, `Makefile`,
  `AGENTS.md`, `README.md`, and `CONTRIBUTING.md` invoke the exact
  `python[3] scripts/adr_guard/adr_guard.py ...` path;
- five test modules load that file with
  `importlib.util.spec_from_file_location("adr_guard", ...)`;
- the tests access `Violation`, `REPO_ROOT`, `CHECKS`, `CHECK_LEVELS`, check
  functions, family constants, and private workflow-model helpers; and
- workflow, complexity, boundary-mock, and K8s checks treat the current
  `adr_guard.py` path as a self-change sentinel in targeted mode.

The refactor may change ownership and import topology inside
`scripts/adr_guard/`. It must not change check semantics, check names, rule ids,
profile membership, ordering, diagnostics, exception behavior, process
boundaries, or CLI output.

## Architecture Decisions

Keep `scripts/adr_guard/adr_guard.py` as a thin executable compatibility facade.
The existing `scripts/adr_guard/` directory should become the importable package
root, with concern modules and a `checks/` package beneath it. Do not create a
nested import package also named `adr_guard` beside `adr_guard.py`: the pinned
file-path loaders install the facade in `sys.modules["adr_guard"]`, so imports
of `adr_guard.<module>` would resolve against the non-package facade and fail.
Use an unambiguous fully qualified package namespace, with package-relative
imports internally. Any direct-execution bootstrap belongs once in the facade;
family modules must not mutate `sys.path`.

The facade must preserve the existing invocation from any working directory and
re-export the observed compatibility surface while it remains used. That
includes the public runner contract and the private `_dw_*` workflow model
currently consumed by `test_deploy_workflow.py` and
`test_quality_path_ownership.py`. New family tests should import their owning
module so the facade does not become the new test composition root; retain a
small facade compatibility suite proving the legacy file-path load and CLI.
Re-exporting a function is not enough to preserve tests that monkeypatch a
facade module global: those patches do not alter the moved function's
`__globals__`. Existing patch seams must either remain behaviorally effective
through an explicit dependency seam or be moved to the owning module with
equivalent coverage; do not add module-proxy magic or synchronize globals at
call time.

Keep one explicit, deterministic registry as the composition seam. `CHECKS` and
`CHECK_LEVELS` remain the compatibility maps and the source of CLI choices and
execution order. Check modules must not import the registry or CLI, and the
registry must not discover checks by walking the filesystem, import side
effects, decorators, or naming conventions. Adding the next check should
require one concern-local implementation and test plus an explicit registry
entry and profile decision.

Retain the current check callable shape:

```text
(repo_root: Path, files: list[str] | None) -> list[Violation]
```

Only the CLI/facade establishes the default repository root. Every family
continues to receive `repo_root`; a moved module must not recompute the root
from its deeper `__file__` location. `None` continues to mean a whole-repository
run and is not interchangeable with an empty list.

Use cohesive check families, not one tiny module per `check_*` and not a new
`utils.py` monolith. The real shared kernels visible in the current dependency
graph are narrow:

- `Violation` and the check-call result contract;
- repository-relative path and tracked-file helpers;
- read-only git/base-reference helpers used by ratchets;
- ADR exception loading, matching, and filtering;
- the deploy workflow-as-data parser/evaluator used by deploy and quality
  checks; and
- the explicit registry, profiles, CLI selection, and rendering.

Layer/import helpers stay together; K8s render/security helpers stay together;
deploy textual checks share their workflow constants and block readers; secret,
generated-artifact, and identifier checks share only their safe repository-file
inventory and redaction conventions. Family-specific constants and validators
belong to the family that owns them.

One package-wide predicate must answer whether a selected path changes ADR guard
source. Replace exact `scripts/adr_guard/adr_guard.py` self-change tests with
that predicate wherever a targeted check must revalidate itself. It should
cover package source under `scripts/adr_guard/` while keeping tests, JSON
baselines, and unrelated support scripts classified deliberately. This is the
required extensibility seam: a future check module must not need to update six
scattered exact-file sentinels to avoid self-bypass. The stable
`repo_root`/`files` callable parameters and explicit registry are the other
extension seams; no plugin system is warranted.

No new ADR is needed. Existing ADRs own the enforced policies, and this change
does not create a new repository rule. The implementation is nevertheless a
guardrail change under ADR-002-R1 and must update
`docs/technical/dev/adr-enforcement.md` or `docs/adr/` in the same change.
Update normative descriptions whose symbol locations become stale, especially
the ADR-012 complexity threshold/backlog and current ADR evidence paths. Do not
rewrite historical preflight notes merely because they cite the stable
facade.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #998 |
| --- | --- | --- |
| Result and output contract | `Violation`, `_print_text`, the JSON payload in `main()`, and exit status `0`/`1` | Keep one result schema and one renderer. Do not add family result DTOs, log records, or error envelopes. |
| Check selection | `CHECKS`, `CHECK_LEVELS`, `_parse_args`, `_selected_files` | Preserve names, insertion order, profiles, `--checks`, mutually exclusive scope flags, default level, and `None` versus selected-file behavior. |
| ADR policy and waivers | `docs/adr/index.yaml`, `docs/adr/exceptions.yaml`, `load_adr_exceptions`, `filter_excepted_violations` | Apply dated exceptions once after all selected checks. A family must not parse or suppress its own waivers. |
| Layer policy | `scripts/check_layer_imports/layer_imports.yaml` | This remains the sole classification/allowlist data. Do not create package-local layer enums or a second YAML schema. |
| Standalone layer checker | `scripts/check_layer_imports/check_layer_imports.py` and `_symbol_facade.py` | Preserve parity without opportunistically redesigning both checkers. Reuse an existing pure helper only when dependencies and diagnostics remain compatible; do not copy a third implementation. |
| Workflow semantic model | Existing `_dw_*` loader, shape errors, constrained expression parser, filter matcher, and runner classification | Extract once and reuse from deploy checks, quality ownership, and workflow tests. Do not create per-check YAML loaders or expression evaluators. |
| Quality ownership schema | `.github/quality-path-filters.yaml` parsed by `scripts/quality_ownership/contract.py` | Keep dynamic consumption of the canonical contract module; do not reproduce its dataclasses, schema validation, glob precedence, or output computation. |
| K8s policy | Existing `yaml.safe_load_all`, chart render matrix, pod/container checks, and network-policy checks | Share the render/parse boundary between the two K8s checks. Do not replace kube-linter, kubeconform, Helm, or their distinct policy scopes. |
| Secret and identifier policy | Existing tfvars parser, generated-artifact inventory, secret-env shape checks, `_read_text_safe`, identifier patterns, and redacted violations | Move behavior intact. Never centralize real secret values or live identifiers in fixtures, constants, or diagnostics. |
| Boundary-mock ratchet | `scripts/adr_guard/boundary_mock_baseline.json`, `_git_text`, and base-reference selection | Preserve read-only git behavior, base-ref ordering, local fail-open behavior, dated exceptions, and non-growth semantics. |
| Complexity policy | `PYTHON_COMPLEXITY_GATE_PYPROJECTS`, `PYTHON_COMPLEXITY_THRESHOLD`, `.pre-commit-config.yaml`, and `docs/adr/complexity-backlog.md` | Keep one threshold and the current cross-file reconciliation. Moving the constant requires updating normative references, not cloning it. |
| Attribution policy | `agent_attribution.py` and `block_agent_attribution_commit_msg.py` | Keep detection and commit-message enforcement separate from package bootstrap. Use package-relative import wiring without duplicating detector patterns. |
| Local/CI routing | `.pre-commit-config.yaml`, `.github/quality-path-filters.yaml`, `_quality.yml`, and `Makefile::test-adr-guard`/`policy` | Existing `scripts/adr_guard/**` routing already covers nested modules and tests. Preserve the exact facade command and self-check lane. |

The existing quality unit intentionally has dated ADR-004-R24 exceptions for
its missing blocking lint and security owners, tracked by #1698. Do not
mislabel the ADR guard test lane as lint/SAST, and do not turn this structural
refactor into an unreviewed closure of that separate workflow gap.

## Cross-Cutting Layers The Design Must Pass

| Layer | Required invariant |
| --- | --- |
| Auth/execution context | ADR conformance stays on GitHub-hosted `ubuntu-latest` with `contents: read`; it must not gain `id-token: write`, cloud credentials, a protected Environment, write permissions, or self-hosted execution. Local pre-commit remains a developer process. The package split adds no application auth surface. |
| CLI input shape | `argparse` remains the only CLI parser. Check names are selected from the explicit registry; `--all`, `--changed`, and `--files` stay mutually exclusive; normalized paths continue to be passed as repository-relative strings. Do not add import/module names as user-selectable execution targets. |
| ADR/config shape | ADR index and exceptions retain their JSON-in-`.yaml` standard-library parsing and current shape validators. Layer policy retains its canonical YAML data. Ruff config retains `tomllib`. Workflow and K8s parsing retain `yaml.safe_load`/`safe_load_all`. Quality ownership retains `contract.py` as its only schema validator. |
| Secret handling | `no-plaintext-secrets-in-tfvars`, `no-populated-secret-env-files`, generated-artifact, live-identifier, and Mission Control flag checks must continue to report path, line/kind, and remediation without echoing matched values. No package initializer may read environment files or configuration eagerly. |
| Environment binding | Preserve the narrow meanings of `ADR_GUARD_BASE_REF` and `GITHUB_BASE_REF` as read-only git-reference selectors and `ADR_GUARD_SNAPSHOT_ENFORCE` as the CI fail-closed switch. The workflow evaluator's child environment remains restricted to `PATH`, `GITHUB_REF`, and a temporary `GITHUB_OUTPUT`. Do not add family-specific env flags. |
| OS/process exposure | Git and Helm continue through fixed argv arrays, bounded timeouts where currently present, explicit `cwd`/`-C`, captured output, and no shell. `_dw_evaluate_env` is the one existing constrained exception: it evaluates the repository's static `Set environment` workflow body via `bash -c` with literal event/branch inputs, an explicit minimal environment, no secrets, no tracing, and a temporary output file. Do not generalize it into a shell helper or feed CLI/config/secret text into it. |
| Filesystem/persistence | Checks read the checkout and, where necessary, git metadata. They do not write repository state, databases, caches, audit logs, or cloud state. The workflow evaluator's temporary `GITHUB_OUTPUT` remains process-local and is removed with its temporary directory. Moved modules must use the supplied `repo_root` and must not scan home directories or paths derived from their new depth. |
| Error envelope | Expected malformed repository input remains a deterministic `Violation` or the existing bounded `_DwShapeError` translated by its owning check. Text and JSON output shapes and exit codes stay unchanged. Do not add a package-wide exception hierarchy, per-family serialization, stack traces in normal violations, or a catch-all in `main()` that converts programmer defects into false policy results. |
| Observability | The observable signal is deterministic stdout plus the pre-commit/CI exit status. There is no logger, metric, event, or durable audit surface to preserve or create. Diagnostics must retain check name, ADR rule, repository-relative path, and redaction. |
| Dependency/runtime | Python 3.11 remains required because of `tomllib`; CI and the test lane retain their pinned `uv`/PyYAML setup; the dependency-bearing K8s hook retains PyYAML. Module import must remain side-effect free and must not require Helm unless a selected K8s check reaches chart rendering. |
| Exception policy | `docs/adr/exceptions.yaml` remains the only waiver mechanism, with owner, reason, expiry, and optional path/check scope. Filtering occurs centrally after check execution so extraction cannot produce family-specific bypass behavior. |

## Compatibility And Test Guardrails

The authoritative behavior baseline is the current suite under
`scripts/adr_guard/tests/`, including synthetic repositories, real-repository
conformance, workflow-as-data tests, and registration/profile assertions.
Reorganize tests by behavior family as production ownership moves, but retain
black-box coverage that:

- runs the unchanged file-path CLI for text and `--json` success/failure cases;
- file-loads `adr_guard.py` as module name `adr_guard`;
- proves the compatibility facade exposes the currently consumed symbols;
- compares the ordered check names and `fast`/`ci`/`all` memberships;
- proves a change to any package source module triggers every check that treats
  guard source as relevant in targeted mode; and
- runs every registered check against the real repository at the appropriate
  profile, including optional PyYAML/Helm prerequisites.

Preserve exact failure semantics as behavior, not source topology. Do not make
tests assert which private family module implements a check. Conversely, do not
silently drop the existing workflow-model unit tests merely because `_dw_*`
moves; that model is a shared policy engine and needs focused parser,
expression, routing, and shape-error coverage.

The guard's own `boundary-mock-policy` applies to touched tests. Prefer
synthetic repo data, explicit dependency parameters at process/git boundaries,
and black-box facade calls over adding new patches of first-party internal
functions. Do not raise `boundary_mock_baseline.json` to accommodate the
refactor.

## Whole-Repository Integration Surface

The implementation owns or consumes these surfaces:

- `scripts/adr_guard/adr_guard.py`, the new package modules beneath
  `scripts/adr_guard/`, and `scripts/adr_guard/tests/`;
- `scripts/adr_guard/boundary_mock_baseline.json`,
  `agent_attribution.py`, and the commit-message blocker as existing adjacent
  contracts, not default move targets;
- `docs/adr/{index.yaml,exceptions.yaml,complexity-backlog.md,README.md}` and
  `docs/technical/dev/adr-enforcement.md` as normative policy/documentation;
- `scripts/check_layer_imports/{layer_imports.yaml,check_layer_imports.py,_symbol_facade.py}`
  and `.importlinter` as complementary architecture validation;
- `.github/quality-path-filters.yaml`,
  `scripts/quality_ownership/{contract.py,classify_paths.py}`, and
  `.github/workflows/_quality.yml` as fail-closed quality routing;
- `.pre-commit-config.yaml`, `Makefile`, `AGENTS.md`, `README.md`, and
  `CONTRIBUTING.md` as stable CLI consumers;
- `.github/workflows/{deploy.yml,_core.yml,_range.yml,_shifter-engine.yml,_shifter-platform.yml,_gcp-dev.yml}`
  as parsed deploy-policy inputs;
- K8s base manifests, the Shifter Helm chart/values matrix, `.kube-linter.yaml`,
  and kubeconform as complementary K8s validation;
- all pyprojects registered in `PYTHON_COMPLEXITY_GATE_PYPROJECTS`, plus the
  Ruff hooks and complexity backlog; and
- `.gitleaks.toml`, Terraform/secret-env/generated-artifact paths, and scoped
  ADR exceptions as complementary secret and identifier policy.

Only the first and the necessary normative documentation should need structural
edits for #998. The remaining surfaces are compatibility or validation inputs;
changing them to make the extraction pass is evidence that the refactor is
drifting into policy or workflow redesign.

## Gotchas And Anti-Patterns

- Do not remove or rename `scripts/adr_guard/adr_guard.py`, switch documented
  callers to `python -m`, or require the repository root to be the current
  directory.
- Do not create a sibling package whose import name collides with the
  file-loaded `adr_guard` facade.
- Do not derive `REPO_ROOT` independently from deeper modules; `parents[2]`
  changes meaning after a move.
- Do not assume `from module import *` preserves underscore-prefixed helpers or
  monkeypatch behavior. The current tests consume both.
- Do not leave exact `adr_guard.py` self-change sentinels in family modules.
  A new package file must not bypass targeted self-validation.
- Do not dynamically discover `check_*` functions, execute package modules for
  registration side effects, or let import order determine profiles.
- Do not copy workflow YAML parsing, the `_DwParser`, quality contract schema,
  layer policy, exception matching, tracked-file inventory, or output
  serialization into each family.
- Do not turn every helper into a public service, protocol, controller, DTO,
  repository, or exception class. This is a synchronous static-policy runner,
  not an application service stack.
- Do not replace the monolith with a giant `common.py`/`utils.py`, dozens of
  one-function files, or circular imports between check families and the
  registry.
- Do not import optional PyYAML or probe Helm from package initialization.
  Unrelated explicit checks must remain runnable without those prerequisites.
- Do not broaden the existing Bash evaluator, pass untrusted CLI values or
  secrets to it, inherit the full process environment, or include arbitrary
  child stderr in new result surfaces.
- Do not change redaction while moving scanners. Values from secret env files,
  tfvars, live cloud identifiers, flags, or rendered deployment material must
  not enter diagnostics, JSON, logs, or fixtures.
- Do not catch every exception in the CLI to make extraction failures look like
  policy violations or success. Anticipated shape errors are bounded locally;
  programming/import defects must remain visible and fail the process.
- Do not treat `files=[]` as `files=None`, reorder checks through set
  iteration, or derive `all` from a nondeterministic source.
- Do not weaken `guardrail-docs`, the independent Quality self-check,
  `adr-guard-tests`, ADR exception expiry, snapshot fail-closed CI behavior, or
  boundary-mock non-growth to make the move easier.
- Do not count this preflight under `docs/architecture/` as the ADR-002-R1
  companion update: the check recognizes `docs/adr/` and the developer ADR
  enforcement docs for guardrail changes.

## Non-Goals

- No checker, rule, profile, CLI, diagnostic, exception, or security-policy
  behavior change.
- No new check registry schema, plugin framework, dependency-injection
  container, generic parser framework, logger, audit store, cache, database, or
  persistence layer.
- No consolidation or redesign of the standalone layer checker, K8s linters,
  gitleaks, Checkov, quality ownership, workflow routing, or ADR registry.
- No closure of the separate #1698 ADR guard lint/SAST ownership gaps, no new
  package toolchain, and no workflow-permission change.
- No cleanup of pre-existing CLI/path edge cases, exception-loading behavior,
  workflow-expression semantics, or shell-model behavior unless a separate,
  explicitly reviewed issue authorizes it.
- No sweep over historical architecture notes solely to replace stable
  `adr_guard.py` citations.
- No product runtime, authentication, cloud, Terraform, Kubernetes,
  application schema, or user-facing behavior change.
- No issue implementation in this preflight.
