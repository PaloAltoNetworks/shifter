# ACES Scenario Verification Plugin Seam Preflight

Issue: GitHub #1293, "ACES migration: define the scenario-verification plugin
seam (move Polaris smoketest coverage out-of-tree)."

Status: pre-implementation architecture guidance. This note does not implement
the entry-point loader, public Python contract, runner, adapters, packaging, or
CI cutover. The ADR required by #1293 remains an implementation deliverable.

## Rescoped Boundary

The 2026-07-15 issue rescope supersedes the in-place adapter-expansion direction
in `polaris-scenario-smoketest-preflight-617.md` and the original #1237 follow-up
wording. The existing harness is input to the contract, not the permanent home
of per-scenario verification.

The boundary is:

- Shifter core owns a provider- and scenario-neutral Python contract, installed
  entry-point discovery, orchestration, prerequisite handling, a bounded
  command-runner contract, result aggregation, exit semantics, and redacted
  human/JSON reporting.
- A separately installed plugin owns every scenario check id, expected answer,
  participant-path command, target/binding name, runtime prerequisite, and all
  mapping from scenario meaning to a backend's realized layout. Core ships zero
  adapters and zero answer-key material.
- ACES SDL is still the demand, `shared.aces.manifest` is the backend capability
  supply, and `shared.aces.runtime_target` plus ingest/realizability validation
  reconcile the two before launch. A verification plugin observes a realized
  range after that boundary; it is not a second capability manifest, launch
  gate, provisioning adapter, or source of scenario requirements.
- The existing read-only CTFd flag-row check is an operational board-integrity
  concern, not the plugin ABI. It may remain as separate generic tooling, but
  the public verification seam must not require CTFd, challenge ids, static
  flags, or a board JSON shape.

The future ADR must name no plugin repository, tenant packaging layout, cloud
provider, runner host, container, network, asset, challenge, or scenario. Those
details belong on the plugin side of the seam.

## Architecture Decisions

### Contract ownership and packaging

The public contract belongs in a neutral module under
`shifter/shifter_platform/shared/`, in the existing `shifter-platform`
distribution. That follows the repository rule that new cross-cutting
contracts live in `shared`, lets the framework reuse `shared.log_sanitize`, and
avoids a new Django app, service/repository layer, persistence model, or a
second Python distribution merely to expose a small in-process protocol.

The module must remain import-safe: importing it cannot initialize Django,
read settings or environment variables, discover plugins, execute adapters, or
import scenario content. Discovery occurs only from the explicit operator CLI
or service entry point. The separately installed plugin must not be bundled
into portal, worker, provisioner, or participant images.

### Runtime discovery

Use `importlib.metadata.entry_points()` with one fixed, documented group:
`shifter.scenario_verification.adapters`. Do not scan scenario-pack
directories, mutate `sys.path`, import modules named by scenario data, inspect
provider folders, or install packages at runtime.

Each entry point resolves to a zero-argument factory returning one immutable
plugin declaration. The declaration carries a contract `api_version`, a stable
plugin id, and its adapters. Discovery must:

- enumerate metadata before loading code and load only the explicitly selected
  installed plugin (or the sole unambiguous match);
- reject an unsupported API version, malformed declaration, duplicate plugin
  id, duplicate adapter identity, and an empty selected adapter set;
- order discovery and reports deterministically by distribution, entry-point,
  and adapter identity;
- identify load failures by sanitized distribution/entry-point id and exception
  class only, never by raw exception text; and
- exit non-zero if discovery or selection cannot produce the requested checks.

Importing an installed entry point executes third-party code with the invoking
user's privileges. Installation is therefore the authorization boundary:
operators must install a reviewed, version-pinned distribution into a dedicated
least-privilege verification environment. A scenario package, catalog row,
web request, manifest, or environment variable must never cause a plugin to be
downloaded, installed, selected by arbitrary module path, or loaded in a Django
request/startup path.

### Public adapter contract

Keep the v1 surface small and typed with frozen dataclasses, enums, and
`typing.Protocol`; this is an in-process Python ABI, so a parallel Pydantic,
ACES, CTFd, or Django schema is not warranted.

- Adapter identity is an opaque stable string scoped by the selected plugin,
  with an optional scenario id and external reference carried as report
  metadata. Core must not require an integer CTFd challenge id.
- `AdapterContext` contains only core-owned capabilities: a `Runner`, immutable
  non-secret bindings, and the run deadline/cancellation budget. It does not
  expose Django settings, cloud SDK clients, a secrets store, a backend
  manifest, `RuntimeTarget`, raw process environment, or provider-specific
  objects.
- `Runner` is a protocol, not a Docker/topology type. Its execution method takes
  an opaque target id, an argv sequence, optional stdin, and an explicit bounded
  timeout, and returns a structured `ExecResult`. A Docker, SSH, Kubernetes, or
  other executor may implement that protocol without changing adapters or
  framework orchestration. Core interprets no target naming convention.
- A prerequisite is an explicit typed check evaluated with the same context
  before the adapter. It returns satisfied or a `blocked` result with a stable
  bounded reason code and authored non-sensitive summary. An exception while
  evaluating a prerequisite is `error`, not `blocked`.
- An adapter returns only `pass` or `fail` plus a stable reason code and an
  optional bounded non-sensitive summary. Expected values, produced values,
  raw evidence, and command output never cross into the report DTO. Core may
  expose a generic secret-equality helper that returns a boolean/verdict only;
  it must not return or fingerprint either operand.

Do not retain the current import-side-effect decorator registry. Registration
by importing `adapters.__init__` is global, order-sensitive, collision-prone,
and cannot attribute a check to an installed distribution or negotiate a
contract version.

### Result and report contract

The report status vocabulary is local to verification and closed:

- `pass`: the adapter ran and its verification condition held;
- `fail`: the adapter ran and the condition did not hold;
- `blocked`: a declared runtime prerequisite was not satisfied, so the adapter
  did not run; and
- `error`: discovery, contract validation, prerequisite execution, runner, or
  adapter execution faulted.

`blocked` is a non-success exit result. It must not be used for mismatches,
adapter exceptions, plugin load errors, an unsupported backend capability, or
missing cutover coverage. It is runtime evidence only and must not be promoted
into the ACES backend manifest or a pack-side requirements manifest.

Human and JSON output must render from the same immutable report DTO. The JSON
shape needs an explicit schema version and may contain only plugin distribution
name/version, plugin/adapter/scenario ids, status, stable reason/prerequisite
codes, bounded non-sensitive summaries, durations, counts, and framework
version. It must never contain expected/produced answers, answer digests, flags,
credentials, private keys, bearer tokens, token-file paths, command argv/stdin,
stdout/stderr, environment values, internal hostnames/addresses, package or
provider payloads, raw exception messages, or tracebacks.

The current `compare.redact()` emits a deterministic truncated SHA-256 of an
answer. That is not acceptable redaction for low-entropy or guessable values:
it enables equality correlation and offline guessing. Reports should emit only
`match`/`mismatch`-class reason codes. If logs require within-process
correlation for a sensitive opaque value, reuse
`shared.log_sanitize.safe_log_fingerprint`; never persist that nonce as report
evidence.

Plugin-provided strings are untrusted report input even when the plugin itself
is trusted code. Enforce id/reason-code character sets and lengths; pass any
display label or summary through `safe_log_value`. Sanitization prevents log
forging but cannot discover an embedded secret, so default output must not
accept arbitrary notes or exception strings. No raw-output/debug-report mode
belongs in the v1 contract.

### Existing harness disposition

The current files contain both reusable framework behavior and scenario-owned
material. Preserve the behavior, not the layout:

| Current concern | Disposition boundary |
| --- | --- |
| `run.py`, `report.py`, generic runner/result behavior | Move/adapt into the neutral shared framework, retaining deterministic aggregation, non-zero failure semantics, exception containment, and fake-runner testability. |
| `adapters/mission1_osint.py`, `adapters/mission5_bunker.py`, adapter-specific tests | Remove from core; they contain scenario topology, participant paths, target names, prerequisites, parsing, and answer material. |
| `adapters/__init__.py` global registry | Replace with installed entry-point discovery and explicit declarations; do not preserve import side effects. |
| `board.py`, Polaris defaults in `__main__.py`, adapter coverage selection | Not part of the provider/pack-neutral contract. They know a CTFd/Polaris schema and answer source and therefore move out of core or remain separate operational tooling. |
| `compare.py` | Preserve only a generic no-value verdict helper if useful; remove deterministic answer fingerprints and `flag`/`answer` as public core types. |
| `ctfd_check.py` | Keep separate from adapter discovery if retained; reuse the existing CTFd client/pagination behavior and translate its raw-body exceptions before any report. |

The framework test suite must use synthetic plugin declarations, sentinel
values, fake entry points, and fake runners. It must prove discovery/version
rejection, collision handling, prerequisite ordering, every status/exit code,
timeouts/output bounds, exception containment, deterministic ordering, and
report redaction. It must not recreate scenario answers, asset names, topology,
or adapter logic as "fixtures" in core.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Neutral contract home | `shifter/shifter_platform/shared/`, `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml` | Keep the ABI independent of CMS, engine, CTF, Mission Control, risk register, and config. Do not add cross-layer imports or a Django app. |
| Current framework behavior | `scenario_smoketest.run`, `report`, `runner`, and framework portions of `test_scenario_smoketest.py` | Preserve orchestration, structured argv, fake-runner injection, aggregation, and exception containment while removing scenario assumptions. |
| Log/report sanitization | `shared.log_sanitize.safe_log_value`, `safe_log_id`, `safe_log_fingerprint` | Reuse the established control-character/length and sensitive-correlation policy. Do not add a second sanitizer or deterministic secret hash. |
| ACES capability supply | `shared.aces.manifest`, `shared/aces/backend-manifest.json` | Keep one evidence-backed backend capability declaration. Verification prerequisites do not add capabilities. |
| ACES demand/supply reconciliation | `shared.aces.runtime_target`, `shared.aces.realization_ledger`, `shared.aces.package_loader`, ingest compatibility gates | Keep admission and fail-closed realization before dispatch. Do not let a plugin validate or mutate launchability. |
| Python distribution metadata | `importlib.metadata` use in `shared.aces.manifest` / `runtime_target` | Use the standard installed-distribution surface; do not build a file registry, module scanner, or package downloader. |
| CTFd readback, if retained | `scripts/ctfd-workshop/common.py::CtfdClient` and `scenario_smoketest.ctfd_check` pagination | Keep read-only pagination/auth/timeout behavior separate from the plugin ABI; sanitize the incumbent client's raw response-body errors at the boundary. |
| CLI/API errors | Existing CLI aggregate-exit convention; `shared.errors` and `shared.api.errors` for any future HTTP surface | The scoped design is CLI-only. Do not add an exception hierarchy or DRF envelope; any later HTTP API must use the shared envelope. |
| Configuration inventory | `config/_env_manifest.py`, `config/env-manifest.json`, `shifter/installation/runtime_inventory.py` | The seam needs no Django env setting. Any later deployed setting must use these canonical binding/inventory gates, not handler-local `os.environ` reads. |
| CI routing | `.github/quality-path-filters.yaml`, `.github/workflows/_quality.yml`, existing shifter-platform test/lint jobs | Remove adapter-specific execution while retaining framework contract tests under the normal platform package gates. Do not create an unpinned plugin install in CI. |
| Parity evidence paths | `docs/architecture/aces-migration-parity-inventory.yaml` and its ADR-024 path-integrity guard | Update in-repo evidence references before removing the current README/module; do not put an external repository path into the checked inventory. |
| Architecture enforcement | `scripts/adr_guard/adr_guard.py`, ADR index/exceptions, `.gc/plan-rules.md` | Keep architecture/workflow changes documented and run the existing gates; do not add or weaken exceptions for the extraction. |

## Cross-Cutting Layers The Design Must Pass

### Security and trust

- **Authentication/authorization:** no browser, DRF, CTF participant, CMS, or
  Mission Control route is in scope. The authorization act is an operator
  installing and selecting a reviewed distribution, then running the CLI as a
  least-privilege verification identity. UI visibility, scenario selection,
  and pack contents are not authorization to load code.
- **Plugin supply chain:** entry-point loading is arbitrary code execution.
  Use an isolated environment with pinned distribution versions/digests and a
  minimal process environment. Do not auto-install from package metadata,
  remote URLs, catalog rows, or runtime values; do not load every installed
  plugin when one was selected; do not give the process cloud-admin, portal,
  database, CTFd-admin, or deployment credentials it does not need.
- **Contract shape:** validate the fixed entry-point group, API version,
  declaration type, ids, duplicates, callables, prerequisites, statuses,
  report fields, timeouts, and size limits before execution. Core validates the
  common envelope once; each plugin validates its own namespaced, non-secret
  bindings once. Do not validate the same plugin fields in core, CLI, and
  adapter code with divergent rules.
- **Scenario/ACES shape:** the seam does not parse SDL, invent a requirements
  manifest, or repeat backend capabilities. Existing ingest, ACES parser,
  backend-manifest, `RuntimeTarget.validate()`, and independent realizability
  gates remain authoritative. A runtime `blocked` result is evidence about one
  run, not a capability declaration.
- **Runner/process exposure:** accept argv sequences only, never shell strings
  or `shell=True`. Validate the concrete runner's target syntax, enforce
  per-command and whole-run deadlines, terminate/cancel runner work, and bound
  captured stdout/stderr before buffering. Do not construct commands from pack
  prose, challenge names, report labels, or unvalidated bindings. Secrets use
  target-local facilities, restrictive files, or stdin where unavoidable;
  never argv or inherited broad environment maps.
- **Network boundary:** the framework opens no network connection itself.
  Plugin checks must use the injected runner and intended participant/runtime
  path; no hidden host-side bypass, network attachment, ACL relaxation, or
  package-controlled URL fetch. An optional CTFd readback remains an explicit
  operator-selected path and must not send its token to a plugin-controlled
  origin or expose raw HTTP bodies.
- **Secret handling and reports:** answer keys and produced evidence remain in
  plugin memory only. Runner results are never logged or placed in reports.
  Token values, keys, credentials, flags, answers, command bodies, environment,
  internal addressing, and provider responses are excluded even on failure.
  A token-file option must enforce regular-file ownership/permission policy;
  help text alone is not a permission check.
- **OS/runtime placement:** core code may ship inertly with the platform
  distribution, but discovery and plugins run only in the operator verification
  environment. No Django startup hook, app `ready()`, web request, queue worker,
  provisioner startup, participant container, or image build may auto-discover
  them.

### Errors, observability, and persistence

- **Error envelope:** normalize failures into the closed verification report
  statuses and stable reason codes. Surface exception class at most. Do not
  create a plugin/adapter exception hierarchy, serialize `str(exc)`, or expose
  raw import, subprocess, SSH, Docker, HTTP, ACES, or provider exceptions. A
  later HTTP endpoint must translate through `shared.api.errors`; it must not
  reuse the CLI JSON report as an API error envelope.
- **Logging/observability:** log/report sanitized plugin and adapter ids,
  distribution version, counts, durations, status, and reason code. Reuse
  `safe_log_value` and, only for transient sensitive correlation,
  `safe_log_fingerprint`. Do not log command lines, output, answers, notes,
  environment, host bindings, package bodies, or tracebacks whose messages can
  carry those values.
- **Persistence:** no database model, repository, migration, outbox event,
  audit-log JSON payload, cache, or artifact store is needed. An explicitly
  requested local JSON report is ephemeral evidence and contains only the
  redacted report DTO. Do not overload `Range`, `RangeInstance`, ACES operation
  records, runtime snapshots, or `AuditLog` with plugin state.
- **Lifecycle/status:** verification `pass/fail/blocked/error` is not
  `ResourceStatus`, `engine.Range.Status`, ACES operation status, CTF challenge
  state, or process exit status. Keep the local enum rather than reusing or
  extending a lifecycle taxonomy with different semantics.

### Configuration and workflow

- **Environment/config:** discovery uses installed metadata and explicit CLI
  selection; no `SCENARIO_*`, provider, plugin path, or repo URL environment
  knob is needed. If a future deployed runtime setting is genuinely required,
  bind it in `config`, regenerate `env-manifest.json`, update installation
  runtime inventory/render tests, and keep secrets out of committed env files.
- **CI:** move framework tests under the existing shifter-platform test surface
  and delete only adapter/answer-key assertions. Workflow/path-filter edits
  must retain normal lint/SAST/test dependencies, use pinned actions, pass
  `actionlint`, and add the required pipeline changelog fragment. Never install
  an unpublished/private scenario plugin in core CI; use fake entry points.
- **Architecture validation:** shared Python changes pass Ruff, format, mypy
  where the package job enforces it, and import-linter. Workflow and doc changes
  pass ADR guard and workflow-model tests. The extraction must not weaken the
  existing `scenario-dev/polaris/tests/**` deploy-quality routing merely because
  one Python adapter suite leaves that tree; other range tests remain there.

## Extensibility Seam

The stable seam is the fixed entry-point group plus the versioned plugin
declaration, with explicit plugin/check selection and an injected `Runner`.
Plugin-specific non-secret bindings remain namespaced and opaque to core. These
are the parameters that let the next scenario plugin, backend realization, or
runner transport land without edits to discovery, orchestration, reporting,
ACES manifests, CMS/CTF services, or provider code.

Do not put `provider`, cloud credentials, Docker container names, CTFd schema,
challenge ids, answer kinds, pack paths, or backend capabilities into the core
type system. If a future variation needs a new runner transport, add a Runner
implementation/factory. If it needs new scenario verification, add an installed
plugin. If it needs a new realizable capability, change the ACES manifest and
independent realization evidence through their existing gates.

## Whole-Repository Surfaces For The Later Implementation

- `scenario-dev/polaris/tests/scenario_smoketest/**` and
  `scenario-dev/polaris/tests/test_scenario_smoketest.py`: mixed current source
  to split; no scenario adapters or answers remain after extraction.
- `shifter/shifter_platform/shared/**` and
  `shifter/shifter_platform/tests/shared/**`: neutral contract/framework and
  synthetic contract tests.
- `shifter/shifter_platform/pyproject.toml` and `uv.lock`: existing
  distribution/CLI metadata only if the operator entry point is exposed there;
  no runtime plugin dependency.
- `.importlinter` and `scripts/check_layer_imports/layer_imports.yaml`: existing
  shared-boundary enforcement; edit only if a genuine new rule is required.
- `.github/quality-path-filters.yaml`, `.github/workflows/_quality.yml`, and
  workflow-model tests in `scripts/adr_guard/tests/`: remove adapter-specific
  CI while keeping framework coverage and other Polaris range-test routing.
- `changelog.d/`: a changed/fixed fragment for CI behavior changes; no direct
  `CHANGELOG.md` edit.
- `docs/architecture/aces-migration-parity-inventory.yaml`: replace removed
  in-repo evidence paths with surviving core/framework or range-smoke evidence;
  do not cite an external checkout path.
- `docs/architecture/aces-polaris-acceptance-parity-gate-preflight-1237.md`,
  `polaris-scenario-smoketest-preflight-617.md`, and current operator runbooks
  under `scenario-dev/polaris/` and `scripts/polaris-aws-range/`: update commands
  and ownership wording without naming a plugin repository in the ADR.
- `shared.aces.manifest`, `runtime_target`, `realization_ledger`,
  `package_loader`, CMS ingest/launch gates, and their tests: architecture
  incumbents to preserve, not plugin-seam edit targets.
- `config/_env_manifest.py`, `config/env-manifest.json`, installation runtime
  inventory/renderers, portal/provisioner Dockerfiles, and Kubernetes/Terraform
  deployment manifests: confirm no plugin setting, secret, dependency, or image
  installation leaks into deployed runtime. No edits are expected.
- `docs/adr/index.yaml`, `docs/adr/exceptions.yaml`, ADR enforcement docs, and
  `scripts/adr_guard/**`: update only when the implementation adds an
  enforceable ADR rule; no exception is expected.

## Gotchas And Anti-Patterns

- Do not leave any hard-coded answer, answer digest, participant path, target
  name, scenario id mapping, or adapter test in core under a generic filename.
- Do not make CTFd `Challenge`, `flag`/`answer`, an ACES scenario pack, or
  Polaris topology the plugin ABI.
- Do not create a pack-side requirements/capabilities manifest. Verification
  prerequisites are runtime checks; SDL/backend-manifest/RuntimeTarget remain
  demand/supply/reconciliation.
- Do not let `blocked` hide failed assertions, exceptions, missing plugin
  coverage, unsupported API versions, or ACES realizability failures.
- Do not trust deterministic hashes as redaction, plugin notes as safe output,
  or exception messages as harmless diagnostics.
- Do not discover by filesystem scan, namespace package scan, `sys.path`
  mutation, import side effects, arbitrary module CLI flags, or network package
  installation.
- Do not load plugins in the portal, a request handler, a worker startup hook,
  the provisioner, a participant container, or CI for core contract tests.
- Do not give `AdapterContext` raw settings, environment, credentials, cloud
  clients, provider payloads, backend manifests, or persistence handles.
- Do not build shell strings, pass secrets in argv, archive command output,
  permit unbounded output, or treat killing a local CLI process as proof that
  remote/container work was cancelled.
- Do not add another logger sanitizer, JSON schema, exception hierarchy,
  workflow DSL, result store, audit model, status taxonomy, CTFd client, ACES
  manifest, or validation pipeline.
- Do not delete the entire Polaris tests path filter or weaken deploy quality
  routing when removing only the adapter suite.

## Non-Goals And Implementation Boundaries

- No plugin seam, adapter extraction, package publication, CLI, test, workflow,
  or runtime behavior is implemented by this preflight.
- No in-core per-scenario adapter expansion or cutover-universe coverage.
- No naming, creation, installation, publication, or CI checkout of an
  out-of-tree plugin repository.
- No scenario/challenge/content authoring or correction; missing content is
  tracked separately.
- No ACES schema/profile expansion, pack-side requirements manifest, backend
  capability claim, `RuntimeTarget` behavior change, ingest change, or range
  launch/cutover.
- No provider layout, runner host/container mapping, cloud transport, network
  relaxation, range mutation, or live verification run.
- No Django/DRF endpoint, permission/scope, settings variable, database model,
  migration, repository, audit/event record, or durable report store.
- No new Ground Control requirement for this requirement-free issue.

## Validation Expectations

For this documentation-only preflight:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

The later implementation also inherits Ruff/format/mypy/import-linter for the
platform package and `actionlint`, workflow-model tests, and a changelog fragment
for workflow changes.
