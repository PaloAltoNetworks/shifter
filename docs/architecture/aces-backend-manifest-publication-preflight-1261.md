# ACES Backend Manifest Publication Preflight

Issue: GitHub #1261, "ACES migration: publish Shifter provisioning-only
backend manifest."

Status: pre-implementation architecture guidance. This note does not implement
the manifest, adapter, conformance runner, profile tooling, or live validation.

## Boundary

`docs/architecture/aces-runtime-target-backend-manifest-preflight-1233.md` is
the design source for this publication slice. ADR-024 remains the controlling
migration decision: current Shifter runtime behavior stays authoritative until
the parallel ACES path passes parity, manifest/conformance, portal, engine,
provisioner, status, and validation gates.

The #1261 scope is a checked-in Shifter ACES backend manifest source and PR
evidence that the source validates through ACES contract/profile tooling.
It must not add a launch adapter, operation sidecar persistence, new API
surface, cloud workflow, Terraform variable model, runtime selector, or
orchestrator/evaluator/participant-runtime claim.

## Architecture Decisions

- The only backend profile claim in this slice is `provisioning-only`.
- The manifest must declare exactly the ACES contracts required for that claim:
  `backend-manifest-v2`, `operation-receipt-v1`, `operation-status-v1`, and
  `runtime-snapshot-v1`.
- Orchestrator, evaluator, participant runtime, broader observation, and
  experiment claims stay absent until later slices add real ACES protocol
  support and conformance evidence.
- The checked-in manifest is a capability/profile source, not runtime
  configuration. It must not be read as Shifter settings, an env file,
  Terraform input, Kubernetes manifest, scenario template, or provider
  inventory.
- Backend-owned realization remains backend-owned. Terraform modules and
  variables, cloud provider choices, SSM/bootstrap commands, image ids,
  machine sizes, subnet allocation, NGFW attachment, and secret lookup are
  Shifter backend details to expose only as coarse capability/support
  statements when the ACES profile allows them.
- Validation must use ACES contract/profile tooling as the source of truth.
  Local tests may assert integration and invocation shape, but they must not
  reimplement ACES profile semantics with Shifter-only string checks.
- PR evidence should be deterministic and sanitized: command, manifest path,
  profile id, contract versions, tool version or ref, and pass/fail summary.
  It must not include secret values, generated runtime config, provider
  payloads, Terraform outputs, SSM output, image credentials, live cloud ids,
  or raw diagnostic dumps.

## Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Migration decision | `docs/architecture/aces-migration-adr.md`, ADR-024 in `docs/adr/index.yaml` | Keep this as a parallel, parity-gated publication. Do not create a second migration doctrine in the manifest. |
| Manifest/profile design | `docs/architecture/aces-runtime-target-backend-manifest-preflight-1233.md` | Reuse the `provisioning-only` decision and the required-contract list without widening claims. |
| Parity tracking | `docs/architecture/aces-migration-parity-inventory.yaml` row `validation.aces-manifest-conformance` | Treat conformance output as validation evidence, not as runtime state or a hand-maintained checklist. |
| Scenario/package boundary | `docs/architecture/aces-catalog-package-boundary-preflight-1232.md` | Keep package/source/profile identity explicit and separate from legacy YAML templates. |
| Operation/status/snapshot boundary | `docs/architecture/aces-operation-status-snapshot-projection-preflight-1234.md` | Declaring contracts does not create sidecar persistence, status mapping, or runtime snapshots in this slice. |
| Runtime config inventory | `shifter/installation/runtime_inventory.py`, `config/env-manifest.json`, provider runtime renderers | Do not add ACES manifest values as env settings unless a later runtime issue adds explicit settings and inventory coverage. |
| Service boundaries | `cms.scenarios.registry`, `cms.scenarios.hydrator`, `cms.services.create_range`, `engine.services`, `engine.ecs`, `shifter/engine/provisioner` | The manifest describes supported backend capability; implementation must not bypass these boundaries or invoke cloud tools from CMS/API code. |
| Shared contracts/imports | `shifter/shifter_platform/shared/**`, `.importlinter`, `scripts/adr_guard/adr_guard.py` | If code later imports ACES models, keep the import boundary behind `shared` and existing service seams. |
| Auth/errors/logging | `cms.api.permissions`, `shared.api_tokens.scopes`, `shared.api.errors`, `shared.errors`, `shared.log_sanitize`, provisioner `log_redact` | Any future surface that serves the manifest or validation result must reuse existing authorization, error envelopes, and redaction helpers. |
| Verification workflow | `.gc/plan-rules.md`, `.ground-control.yaml`, `scripts/adr_guard/adr_guard.py` | The future implementation must run ACES validation plus repo architecture checks without weakening either gate. |

## Cross-Cutting Layers

- ACES contract/profile validation: the manifest source must pass
  `backend-manifest-v2` plus the `provisioning-only` backend profile using the
  ACES tooling selected by the implementation. Shifter tests should verify
  invocation, checked-in paths, and evidence capture, not duplicate profile
  interpretation.
- Auth surface: if the manifest or validation result is later exposed through
  CMS/API, use existing CMS authoring/session/API-token permission gates and
  exact scopes. This issue does not need a public API surface.
- Scenario input shape: no legacy YAML shape detection, no raw ACES SDL stored
  in `Scenario.definition`, and no launchability inferred from filenames,
  package paths, Polaris ids, or manifest claims.
- Runtime config shape: do not add `ACES_*` env keys, installation schema
  fields, generated runtime env entries, Helm/Kubernetes env literals, or
  Terraform variables for this publication-only slice. If a later runtime
  knob is needed, it must go through settings, env manifest, runtime inventory,
  renderer, and tests.
- OS/process exposure: validation commands must use structured argv with
  bounded file paths/profile ids. Do not pass payload bodies, tokens,
  credentials, provider output, Terraform variables, or generated runtime
  config through argv, shell strings, CI logs, or PR evidence.
- Secret-handling surface: manifest source, validation fixtures, logs, and PR
  evidence may contain capability names, profile ids, contract versions,
  sanitized diagnostics, and coarse support statements only. Secret values,
  secret-bearing URLs, private keys, image credentials, SSM output, NGFW
  details, and live cloud ids stay out.
- Error-envelope surface: any future API or UI presentation of validation
  failures uses existing safe error classification and envelopes. Raw ACES,
  Terraform, cloud, SSM, SSH, Docker, and provider exceptions remain sanitized
  diagnostics.
- Import and architecture surface: ACES imports remain behind `shared` and the
  existing CMS/engine/provisioner boundaries. `.importlinter` and ADR guard
  remain hard gates.
- Release/workflow surface: publication evidence belongs in the PR and tests.
  Do not weaken CI, ADR guard, import-linter, Terraform, Kubernetes,
  actionlint, or secret-scanning policy to get the manifest accepted.

## Extensibility Seam

The required seam is an explicit backend profile/capability discriminator in
the manifest source. The first value is `provisioning-only`; future values may
add orchestration, evaluation, participant runtime, provider variants, or
observation depth only by adding ACES protocol support, contract versions, and
conformance evidence behind that discriminator.

The manifest path and validation wrapper should be parameterized by manifest
source path and profile id so a later profile variant can be validated without
rewriting the canonical artifact or hardcoding `provisioning-only` into
unrelated workflow logic.

## Whole-Repo Scope

Future implementation must evaluate changes against:

- `docs/architecture/aces-runtime-target-backend-manifest-preflight-1233.md`
- `docs/architecture/aces-migration-adr.md`
- `docs/architecture/aces-migration-parity-inventory.yaml`
- `docs/architecture/aces-catalog-package-boundary-preflight-1232.md`
- `docs/architecture/aces-operation-status-snapshot-projection-preflight-1234.md`
- `docs/adr/index.yaml` and `docs/adr/exceptions.yaml` only if enforceable
  rules or exceptions change
- the checked-in ACES manifest source and any local validation wrapper added by
  the implementation
- `shifter/shifter_platform/shared/**` only if code imports ACES contracts
- `shifter/shifter_platform/cms/scenarios/**`, `cms/services/**`,
  `engine/**`, and `shifter/engine/provisioner/**` only if a later runtime
  adapter is scoped
- `shifter/installation/runtime_inventory.py`,
  `shifter/shifter_platform/config/env-manifest.json`, provider runtime
  renderers, `.shifter.yaml`, and `shifter.yaml` only if a later issue adds
  runtime configuration
- `.ground-control.yaml`, `.gc/plan-rules.md`, `.importlinter`,
  `scripts/adr_guard/**`, and stack-native validators for any touched
  guardrail, Python, workflow, Terraform, or Kubernetes surface

## Gotchas And Anti-Patterns

- Do not claim ACES orchestrator, evaluator, participant runtime, experiment,
  or broad observation capability in this slice.
- Do not turn Shifter's setup orchestrator, CTF scoring, Mission Control, range
  status, or provider telemetry into ACES protocol support by naming them in
  the manifest.
- Do not expose Terraform variables, cloud provider settings, SSM/bootstrap
  commands, image ids, subnet/CIDR allocation, NGFW attachment, secret ids,
  provider task ids, or live resource ids as authored scenario semantics.
- Do not create a Shifter-only backend-manifest schema, profile validator,
  status taxonomy, exception hierarchy, or conformance checklist.
- Do not make the manifest a runtime config file, settings module, env
  manifest, Terraform input, Kubernetes manifest, or source of launchability.
- Do not store raw ACES payloads in `Scenario.definition`,
  `RangeInstance.range_spec`, `engine.Range.provisioned_instances`, audit JSON,
  events, logs, or PR evidence.
- Do not use Polaris-specific names or paths as the backend profile type
  system. Polaris remains a parity proving case, not the public manifest seam.

## Non-Goals

- No RuntimeTarget adapter or range launch path.
- No operation sidecar persistence, status projection, snapshot storage, or UI.
- No CMS/API endpoint for serving or mutating the manifest.
- No Terraform, cloud, SSM, image, subnet, NGFW, secret, or installation-config
  changes.
- No new ACES profile beyond `provisioning-only`.
- No GitHub issue or Ground Control requirement mutation for this
  requirement-free run.

## Validation Expectations

For this design-doc change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

The future implementation must also run the ACES contract/profile validation
for the checked-in manifest and capture sanitized PR evidence.
