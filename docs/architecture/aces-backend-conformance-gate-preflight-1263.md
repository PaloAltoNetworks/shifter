# ACES Backend Conformance Gate Preflight

Issue: GitHub #1263, "ACES migration: add Shifter ACES backend conformance
gate."

Status: pre-implementation architecture guidance. This note does not implement
the conformance runner, CI wiring, tests, RuntimeTarget adapter, API surface, or
live validation. This is a requirement-free run; the GitHub issue is the
shipping contract.

## Boundary

`docs/architecture/aces-runtime-target-backend-manifest-preflight-1233.md` is
the design source for the backend profile claim.
`docs/architecture/aces-backend-manifest-publication-preflight-1261.md` and
`shared.aces.manifest` are the current manifest publication incumbents. ADR-024
remains the controlling migration doctrine: Shifter's current runtime path
stays authoritative until the ACES path passes parity, backend
manifest/conformance, portal, engine, provisioner, status, and validation gates.

#1263 adds an automated conformance gate for the initial Shifter backend
profile claim. It must validate the published Shifter manifest as
`provisioning-only` through ACES-owned contract/profile/conformance tooling and
must surface only bounded, sanitized diagnostics.

The gate is validation evidence, not a runtime feature flag and not a launch
adapter. It must not introduce a second manifest, local ACES profile schema,
second status taxonomy, new exception hierarchy, new secret store, new runtime
settings surface, Terraform/Kubernetes change, or workflow-owned JSON template.

## Architecture Decisions

- Keep `shared.aces.manifest` as the canonical Shifter backend manifest source
  and `shifter/shifter_platform/shared/aces/backend-manifest.json` as the
  checked-in publication artifact.
- The profile claim remains exactly `provisioning-only`. The gate must fail if
  Shifter widens capabilities or supported contracts without matching ACES
  conformance evidence.
- Validation semantics come from ACES tooling. Shifter code may adapt invocation
  shape and sanitize output, but must not reimplement backend profile inference,
  required-contract calculation, or conformance verdict logic with local string
  checks.
- Failure output may name profile ids, capability names, contract versions,
  manifest path, report refs, tool version/ref, and bounded status classes. It
  must not include secrets, provider credentials, Terraform variables or output,
  SSM/bootstrap payloads, private keys, generated runtime config, raw ACES
  payload bodies, live cloud ids, or unbounded diagnostic dumps.
- Prefer a test-local or shared validation helper exercised by the existing
  `shifter_platform` pytest suite. A separate top-level script or workflow job is
  justified only if the ACES tool cannot be exercised reliably from pytest; if
  added, it must use the existing quality path-filter and ADR/workflow guard
  conventions rather than weakening current checks.
- The ACES tooling dependency remains dev/test scoped while the gate validates a
  checked-in manifest and no production runtime path imports it. Promoting ACES
  tooling to a runtime dependency belongs to the RuntimeTarget-adapter slice only
  when production code needs it.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Migration doctrine | `docs/architecture/aces-migration-adr.md`, ADR-024, `docs/architecture/aces-migration-parity-inventory.yaml` row `validation.aces-manifest-conformance` | Treat the gate as parity/cutover evidence, not as a runtime selector. |
| Design source | `docs/architecture/aces-runtime-target-backend-manifest-preflight-1233.md` | Reuse the `provisioning-only` claim and required-contract boundary. |
| Manifest source | `shared.aces.manifest`, `shared.aces.contracts`, `shifter/shifter_platform/shared/aces/backend-manifest.json` | Validate the published builder/artifact pair; do not add a second manifest or constants file. |
| Existing manifest tests | `tests/shared/aces/test_backend_manifest_publication.py` | Extend or complement the publication tests instead of duplicating model/profile assertions elsewhere. |
| Diagnostic sanitization | `shared.log_sanitize`, `shared.schemas._aces_validation.validate_diagnostic_refs`, `shared.aces.status` diagnostic-ref pattern | Use bounded single-line summaries and allowlisted refs; do not create a parallel sanitizer with broader output. |
| Package/source conformance metadata | `cms.models.AcesPackageSource`, `shared.schemas.aces_package_source` | Keep package conformance status separate from backend manifest conformance. One does not imply the other. |
| Workflow verification | `.github/workflows/_quality.yml`, `.github/quality-path-filters.yaml`, `.pre-commit-config.yaml`, `.gc/plan-rules.md` | Keep local pytest/pre-commit and CI quality wiring aligned; workflow changes trigger `actionlint` and ADR guard. |
| Import enforcement | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `scripts/adr_guard/adr_guard.py` | ACES imports stay behind `shared` or tests unless a later ADR/import-rule change permits more. |
| Runtime config inventory | `config/settings.py`, `config/env-manifest.json`, `shifter/installation/runtime_inventory.py`, provider renderers | No new runtime env/config knob for this gate unless the implementation introduces an operator-configurable setting. |

## Cross-Cutting Layers The Design Must Pass

- ACES contract/profile validation: invoke the published ACES backend
  conformance/profile tooling against the Shifter manifest and expected
  `provisioning-only` profile. Shifter assertions should check integration,
  manifest path/artifact sync, expected verdict, and sanitized output shape, not
  duplicate ACES profile semantics.
- Manifest publication surface: `create_shifter_backend_manifest()`,
  `render_shifter_backend_manifest_payload()`, `SHIFTER_BACKEND_PROFILE`,
  `SHIFTER_SUPPORTED_CONTRACT_VERSIONS`, and
  `shifter/shifter_platform/shared/aces/backend-manifest.json` must remain in
  lockstep. Builder/artifact drift is a conformance failure.
- Security and secret-handling surface: conformance inputs are checked-in
  manifest payloads and profile ids only. Outputs are bounded verdicts,
  references, fingerprints, contract names, and tool metadata. Raw provider
  payloads, Terraform/SSM output, generated runtime config, private keys,
  tokens, credentials, cloud ids, and raw ACES package bodies must not reach
  logs, CI annotations, pytest failure text, PR evidence, env files, or
  artifacts.
- OS/process exposure: command execution, if needed, uses structured argv with
  bounded repo-relative paths/profile ids/report refs. Do not pass manifest
  JSON, package bodies, tokens, credentials, Terraform variables, generated
  commands, broad environment dumps, or shell fragments through argv or logs.
- Error-envelope surface: this gate should normally fail in pytest/CI, not an
  API response. If any result is later exposed through CMS/API/UI, it must use
  existing `shared.api.errors`, `shared.errors`, CMS permissions, and sanitized
  diagnostic refs. Raw ACES, Terraform, cloud, SSM, SSH, Docker, or provider
  exceptions stay behind curated messages.
- Config/env validators: no ad hoc `ACES_*` environment reads in tests,
  validators, views, workers, or workflows. A configurable report path,
  profile selector, or retention knob must go through typed settings,
  `config/env-manifest.json`, runtime inventory/renderers, and tests.
- Auth surface: #1263 should not need a new user-facing endpoint. If the gate
  evidence is later served, CMS authoring/session/API-token scopes and product
  ownership checks run before reading sidecar/report refs. Conformance status is
  never authorization.
- Import-boundary surface: production CMS, CTF, Mission Control, engine, and
  provisioner modules must not import `aces_conformance`, `aces_contracts`, or
  `aces_backend_protocols` directly for this gate. Keep ACES tooling imports in
  tests or a `shared` facade that import-linter permits.
- Workflow/security gates: ADR guard, import-linter, layer-import checks,
  ruff/format, Bandit, secret scanning, actionlint, Terraform, Kubernetes, and
  runtime-env validation remain enabled for every touched surface. A new gate is
  additive; it must not replace or soften existing checks.

## Extensibility Seam

The seam is a parameterized backend conformance invocation over manifest path,
expected backend profile, and optional sanitized report ref. The first expected
profile is `provisioning-only`; a later orchestrator, evaluator, participant
runtime, observation, provider, or live-target variant should add a profile or
capability branch behind the same seam.

Do not hardcode Polaris names, workflow paths, Terraform providers, or Shifter
range ids into the gate. The next reasonable variation is another manifest/profile
claim or a live RuntimeTarget conformance run; that should require changing the
profile/report parameters and adapter evidence, not copying the gate into CMS,
CTF, Mission Control, engine, provisioner, or workflow-specific scripts.

## Whole-Repo Scope

Future implementation must evaluate changes against:

- `docs/architecture/aces-runtime-target-backend-manifest-preflight-1233.md`
- `docs/architecture/aces-backend-manifest-publication-preflight-1261.md`
- `docs/architecture/aces-registry-validation-launchability-preflight-1253.md`
- `docs/architecture/aces-participant-runtime-manifest-conformance-gate-preflight-1291.md`
- `docs/architecture/aces-migration-adr.md`
- `docs/architecture/aces-migration-parity-inventory.yaml`
- `shifter/shifter_platform/shared/aces/manifest.py`
- `shifter/shifter_platform/shared/aces/contracts.py`
- `shifter/shifter_platform/shared/aces/backend-manifest.json`
- `shifter/shifter_platform/shared/schemas/_aces_validation.py`
- `shifter/shifter_platform/shared/log_sanitize.py`
- `shifter/shifter_platform/tests/shared/aces/`
- `shifter/shifter_platform/pyproject.toml` and `uv.lock` if ACES tooling pins
  change
- `.github/workflows/_quality.yml`, `.github/quality-path-filters.yaml`, and
  `.pre-commit-config.yaml` only if the gate cannot live inside the existing
  shifter_platform test suite
- `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`,
  `scripts/adr_guard/**`, `docs/adr/index.yaml`, and `docs/adr/exceptions.yaml`
  only if enforceable guardrails or exceptions change
- `config/settings.py`, `config/env-manifest.json`,
  `shifter/installation/runtime_inventory.py`, `platform/terraform/**`, and
  `platform/k8s/**` only if implementation adds runtime configuration or
  deployment surfaces, which is not expected for this gate

## Gotchas And Anti-Patterns

- Do not create a Shifter-local backend profile schema, required-contract table,
  conformance verdict enum, exception hierarchy, report format, or manifest
  template.
- Do not treat package conformance, Polaris parity, or launchability as backend
  manifest conformance. They are separate gates.
- Do not claim ACES orchestrator, evaluator, participant runtime, or broad
  observation capability to make a conformance run appear more complete.
- Do not expose Terraform variables, SSM documents/output, provider payloads,
  image ids, subnet/CIDR allocation, NGFW attachment, secret ids, runtime env,
  generated configs, or live resource ids in manifest diagnostics.
- Do not route conformance through shell strings, env dumps, workflow summaries,
  Kubernetes env literals, SSM command text, or artifacts that can leak payloads
  or secrets.
- Do not skip existing architecture, import, Terraform, Kubernetes, workflow,
  SAST, secret-scanning, or runtime-env checks because the ACES gate passes.
- Do not make the conformance gate a launch authorization check, feature flag,
  or cutover switch. It is one validation gate in ADR-024's larger cutover set.

## Non-Goals

- No RuntimeTarget/provisioner adapter implementation in this preflight.
- No live cloud, Terraform, SSM, Docker, SSH, Kubernetes, or provider execution.
- No CMS/API/UI endpoint for serving or mutating conformance results.
- No new runtime env variable, installation schema field, Terraform variable,
  Helm value, or Kubernetes manifest unless a later implementation explicitly
  adds an operator-configurable runtime surface.
- No ACES profile beyond `provisioning-only`.
- No replacement of existing manifest publication tests, ADR guard,
  import-linter, Terraform, Kubernetes, workflow, SAST, or secret checks.
- No new Ground Control requirement UID for this requirement-free run.

## Validation Expectations

For this architecture note, run:

```bash
python3 scripts/adr_guard/adr_guard.py --files docs/architecture/aces-backend-conformance-gate-preflight-1263.md docs/architecture/aces-migration-parity-inventory.yaml --level fast
```

The future implementation must also run the ACES backend conformance gate, the
`shifter_platform` tests covering it, and the stack-native checks required by
`.gc/plan-rules.md` for every touched path.

## Implementation

Implemented by
`shifter/shifter_platform/tests/shared/aces/test_backend_conformance_gate.py`.
The gate is a test-local, parameterized helper (`manifest`, expected profile,
manifest ref) exercised by the existing `shifter_platform` pytest suite. It runs
the ACES fixture conformance runner for the `provisioning-only` profile against
Shifter's published manifest (builder plus the checked-in
`shared/aces/backend-manifest.json` artifact via the `backend-manifest-v2`
model), proves the gate is non-vacuous against a capability-widened and a
contract-dropped manifest, and asserts diagnostics stay single-line, bounded,
and free of secret- or provider-realization-shaped substrings. ACES tooling
stays dev/test scoped; no production runtime path imports it.
