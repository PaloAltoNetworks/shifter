# ADR-041: Scenario verification uses an explicitly selected installed plugin seam

## Status

Accepted.

## Date

2026-07-16

## Context

Scenario verification must prove that a realized scenario behaves as intended
through participant-relevant paths. The checks that provide that proof know
scenario answers, runtime topology, target names, credentials, protocols, and
backend-specific realization details. Those details are neither a platform
contract nor a scenario-description contract and must not become core runtime
policy.

Keeping scenario adapters in core would couple releases to scenario content,
expose answer material to unrelated installations, and encourage core services
to understand provider topology. A filesystem registry or import-side-effect
registry would add ambiguous selection and make installed code load without a
clear operator authorization boundary.

Core still needs a stable, testable contract for discovery, execution,
prerequisites, aggregation, and redacted evidence. That contract must remain
independent from the realization admission path and safe to exercise with
synthetic plugins in normal core CI.

## Decision

Core owns a provider- and scenario-neutral scenario-verification framework in
the shared contracts layer. Per-scenario adapters, answer material, topology,
and runner implementations live in separately installed distributions. Core
ships zero adapters.

### Discovery and selection

The only discovery namespace is the Python entry-point group
`shifter.scenario_verification.adapters`. Each entry point names a zero-argument
factory that returns one immutable, versioned plugin declaration.

Discovery enumerates installed distribution metadata without importing every
candidate. An operator selects an installed distribution by distribution name,
version, and entry-point name; a sole unambiguous candidate may be selected
when no selector is supplied. Only the selected candidate is loaded. Duplicate
or malformed identities, unsupported API versions, empty declarations,
ambiguous selection, and load failures fail closed before adapter execution.
Ordering is deterministic.

Installing and explicitly selecting reviewed, version-pinned code is the
authorization boundary. Core never scans files or namespaces, mutates
`sys.path`, accepts an arbitrary module path, downloads or installs packages,
or derives a plugin selection from scenario content or another runtime value.
Discovery never runs during web, worker, provisioner, or other service startup.

### Contract ownership

The versioned core contract consists of immutable declarations and result
objects, closed status enums, runtime-checkable runner and cancellation
protocols, deterministic orchestration, and versioned human/JSON rendering.
Plugin-provided identifiers, reason codes, bindings, and summaries are bounded
and validated centrally before execution.

An adapter receives an `AdapterContext` containing only namespaced non-secret
bindings, the injected `Runner`, and the whole-run deadline/cancellation
budget. It does not receive settings, environment maps, cloud clients,
provider objects, backend manifests, persistence handles, or a realized
scenario model.

A prerequisite is an explicit runtime check. A prerequisite that returns
unsatisfied prevents its dependent adapter from running and yields `blocked`.
A prerequisite exception is `error`. An adapter returns only `pass` or `fail`;
prerequisite, runner, timeout, cancellation, invalid-result, or adapter faults
yield `error`. Discovery, selection, declaration, and execution-configuration
failures occur before a report exists and fail closed through bounded safe
exceptions that the operator entry point must map to a non-zero process exit.

### Runner and process boundary

`Runner` is transport-neutral. It accepts an opaque target id, an argv
sequence, optional stdin, and an explicit per-command timeout, and returns one
bounded structured execution result. The framework also enforces a whole-run
deadline and cancellation budget.

No contract accepts shell command strings, broad environment maps, provider
objects, or credentials. Concrete runner implementations validate their own
target namespace, terminate or cancel outstanding work, constrain output
before buffering, and preserve the intended participant/runtime path. The core
framework opens no network connection.

### Status and report boundary

Verification has exactly four report statuses:

- `pass`: the adapter ran and its condition held;
- `fail`: the adapter ran and its condition did not hold;
- `blocked`: a declared runtime prerequisite was unsatisfied, so the adapter
  did not run; and
- `error`: prerequisite execution, runner, timeout, cancellation,
  invalid-result, or adapter execution faulted after a plugin was selected.

Every non-pass status produces a non-zero aggregate exit. Pre-report discovery
and configuration exceptions are also non-zero operator failures. `blocked` is
runtime evidence, not a substitute for missing adapter coverage, an unsupported
API version, an admission failure, or an adapter exception.

Human and JSON output render from the same immutable aggregate report. The JSON
shape has an explicit report schema version and binds the report to the exact
installed distribution name/version and entry-point name plus the declared
plugin id/version. It otherwise contains only allowlisted bounded adapter
identifiers, status and reason codes, durations, counts, and aggregate exit.
Plugin-authored declaration text is validated and sanitized but is not copied
into the report.

Reports and logs never contain expected or produced answers, deterministic
answer hashes, argv or stdin, stdout or stderr, environment values, exception
messages or tracebacks, credentials, internal network details, provider
payloads, or raw evidence. A generic equality helper may return a no-value
verdict but never either operand or a fingerprint.

### Boundaries retained outside the seam

- Scenario SDL is demand, the backend manifest is supply, and the existing
  runtime-target, ingest-compatibility, and realizability gates reconcile them
  before dispatch. Verification does not add a pack-side capability manifest
  or decide launchability.
- Challenge-board and scoring-system readback remains separate operator
  tooling. It is not part of discovery, the plugin declaration, or the report
  ABI.
- Provider topology, transport credentials, participant paths, target mapping,
  and answer comparison belong to the selected plugin and injected runner,
  behind their own least-privilege configuration.
- Persistence, deployment configuration, runtime settings, service APIs,
  audit records, and lifecycle models are unchanged. Verification reports are
  explicit ephemeral operator evidence, not platform state.

## Consequences

- New scenario/backend verification can be delivered and versioned without a
  core release or core knowledge of its topology and answers.
- Core CI tests the full discovery and orchestration contract with synthetic
  declarations, entry points, sentinels, and runners; it does not install a
  private or unpublished adapter distribution.
- Operators must review, pin, install, and explicitly select verification code
  in a least-privilege execution environment.
- Discovery and report schema changes require an explicit version change and
  compatibility review. Malformed or incompatible plugins fail before checks
  run.
- Existing shared import, architecture, workflow, lint, and test gates enforce
  the package boundary. This decision adds no exception and no new executable
  policy checker.

## Non-Goals

These non-goals describe the original operator verification ABI. The tenant
installation addendum below introduces a separate isolated runtime protocol.

- Defining scenario content, participant paths, answers, or adapter coverage.
- Defining provider topology, a transport implementation, or deployment
  packaging.
- Replacing scenario parsing, backend capability manifests, runtime admission,
  realization evidence, challenge-board services, or scoring.
- Adding a web API, service-startup hook, database model, event, audit payload,
  artifact store, settings surface, or automatic package installation.
- Treating verification success as proof of platform lifecycle state or as a
  replacement for infrastructure, isolation, conformance, and cutover gates.

## Tenant plugin installation addendum (2026-09-16)

Tenant organization administrators may install their own runtime plugins through
the tenant UI, without an operator-curated catalog, executable allowlist, cloud
grant, or shell access. Organization membership is authoritative; staff status
alone is insufficient. The Engine installation service uses only the tenancy
facade's `get_organization_profile` and `OrganizationAuthorizationError`. The
composition root uses `list_administrable_organizations` for an advisory UI flag.
These imports are explicitly restricted by the layer checker's symbol allowlists.

The independently versioned `shifter-adapter-sdk` distribution owns both the
existing `verification` ABI and the distinct `shifter.runtime-plugin/v1` wire
contract. This is an independently buildable author-facing component, separate
from the ADR-042 umbrella release version; publication is not yet automated.
The runtime worker's Python helper uses `shifter.runtime.plugins` to load one
exact distribution, version and entry point **inside the isolated image only**.
The portal and provisioner never import tenant plugin code.

A tenant deployment includes a dedicated restricted worker namespace, a service
account with no cloud bindings or API token, deny-all ingress and egress, resource
quotas and admission policy. Installation pins an OCI image digest, encrypts any
registry credentials at rest, and queues an isolated compatibility probe. A
registration starts in `checking`; only current, identity-bound successful probe
evidence may set `ready`. Retry creates a fresh probe identity. Disable and retire
fence pending completion; retirement is irreversible. API responses and audit
omit credentials and untrusted diagnostics. Registry pull secrets are created
with their invocation Job owner and are not mounted into worker containers.

The runtime protocol permits bounded guest-action plans, including private script
content, across the isolated worker boundary. This does not change the legacy
verification ABI's argv-only Runner. Core must validate the response against the
original operation, phase and exact target bindings before interpreting actions.
A plan is not evidence that any action ran. Readiness still requires host-owned
execution and verification. The installation probe proves package compatibility,
not a runnable pack or a ready range.

Pack assignments are organization-scoped and bind a stable catalog identity to
one verified content digest. Updating that digest requires explicit rebinding.
Existing ranges retain a separate immutable pin, including the installation,
manifest, digest, guest mappings and non-secret parameters; disabling or retiring
an installation does not rewrite those pins. The tenant UI offers verified guest
selectors, assignment confirmation and disabled/stale assignment feedback.

The RAES GCE host executes guest plans only after all three isolated planning
phases succeed. Configure and verify run inside apply's cleanup boundary, and
only guest exit status crosses into lifecycle evidence. Plans cannot select
transport targets, credentials or interpreters. Warm reuse is not admitted until
its compatibility contract accounts for plugin identity. Since the first host
grants guest actions only, core guest destruction fulfills cleanup without loading
the plugin again. Other host capabilities require separately reviewed contracts.

Guest action runtime-value references are limited to an original guest binding's
private address and verified participant SSH public key. Core resolves the
closed fields, bounds their JSON transport, and validates all references before
executing any action. The guest receives data in `SHIFTER_RUNTIME_VALUES_B64`;
the planning worker never receives realized values. Participant key requests
require declared SSH access before cloud mutation and use only the public key
returned by verified authored-account installation. Management keys, secret
references and arbitrary provider output fields cannot be selected or used as a
fallback. Both AWS and GCP require independent lifecycle qualification.

The full extraction acceptance criteria remain in
`external-scenario-runtime-design.md`. Local synthetic lifecycle coverage is not
live qualification or proof that private-code extraction is complete.

Native scenario ranges currently support provision, activation and teardown.
Pause/resume is unavailable: the legacy power worker consumes instance records
that native realization does not create. The tenant capability projection and
Engine service reject those operations before state mutation or task dispatch.
