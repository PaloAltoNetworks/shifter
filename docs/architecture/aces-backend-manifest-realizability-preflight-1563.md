# ACES Backend Manifest Realizability Ledger Preflight

Issue: GitHub #1563, "fix: make the ACES backend manifest an honest
realizability ledger (narrow over-claims + gate account features)."

Status: pre-implementation architecture guidance. This note does not change the
manifest, generated artifact, runtime gate, provisioner, or tests. The GitHub
issue is the shipping contract for this requirement-free run.

## Boundary

`shared.aces.manifest` is the one source for Shifter's
`backend-manifest-v2`; `shared/aces/backend-manifest.json` is its deterministic
checked-in rendering. The manifest is an admission envelope: the ACES planner
uses it before launch, and `shared.aces.runtime_target` revalidates the compiled
plan before the dispatch port can persist or provision it.

#1563 narrows that envelope to effects the GCE backend genuinely delivers. It
does not implement credentials, Kerberos/SPN registration, source-package
delivery, dataset materialization, a new manifest schema, or a new backend
profile. Removed terms remain unavailable until their sibling gap issues add
real realization and evidence.

## Architecture Decisions

- Keep `SHIFTER_PROVISIONER_CAPABILITIES` as the canonical declaration and
  regenerate `backend-manifest.json` only through
  `render_shifter_backend_manifest_payload()`. Do not hand-maintain a second
  manifest source or JSON template.
- Remove `auth_method` and `spn` from `supported_account_features`. Ignoring an
  authentication method and writing an SPN-shaped marker file are not account
  realization.
- Narrow `supported_content_types` to `directory`. `dataset` has no payload
  delivery, and the public capability is type-level: it cannot distinguish an
  inline `file` (currently written) from a source-backed `file` (currently only
  creates a parent directory). Keeping `file` would continue admitting an
  unsupported file shape.
- Treat `groups`, `shell`, `home`, `disabled`, and `mail` as the maximum
  account-feature set left by the issue, not as proof by enumeration. A retained
  term needs cross-boundary evidence for the supported guest dialects. The
  manifest has no OS-by-account-feature matrix, so tests must not certify only a
  Linux path while implying unconditional Windows support.
- Keep the upstream plan-time gate authoritative: ACES
  `ProvisionerCapabilities` plus the public
  `provisioner_account_features()` extractor define the capability vocabulary
  and account-spec-to-feature mapping. Do not create a Shifter account schema or
  manually duplicate field-presence rules.
- Add an equivalent Shifter account-feature assertion at apply time because
  `aces_processor.semantics.realization.CONCERN_PAYLOAD_PATH` has no account
  concern in the pinned ACES release. The assertion must run through the same
  pure validation path used by `validate()` and `apply()`, before dispatch, and
  must compare requested features with an evidence-backed realization envelope
  that is independent of the manifest declaration. Comparing the plan only to
  `manifest.provisioner.supported_account_features` would repeat the claim, not
  test it.
- The local assertion is a bounded compatibility shim, not a replacement
  SEM-218 model. It may use a small feature policy/table with separate ownership
  from the manifest, but it must not add a DTO, persistence contract, exception
  hierarchy, or Shifter-only ACES vocabulary. Remove the shim in favor of the
  public ACES gate when a pinned released dependency supports account-feature
  realization evidence.
- Reject with typed `Diagnostic` values. Diagnostics may name the resource
  address and governed feature term only; they must never include account field
  values, credentials, inline content, plan bodies, generated scripts, or
  provider output.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Manifest contract | `shared.aces.manifest`, `shared.aces.contracts`, ACES `BackendManifest` / `ProvisionerCapabilities` | Narrow the existing declaration; do not add a local manifest model or capability registry. |
| Published artifact | `render_shifter_backend_manifest_payload()`, `shared/aces/backend-manifest.json` | Keep builder and checked-in JSON byte-for-byte synchronized. |
| Account vocabulary | `aces_backend_protocols.account_features.provisioner_account_features` | Use the public extractor in planner/envelope/apply checks; do not infer features independently. |
| Plan/apply validation | `shared.aces.runtime_target._serialized_for_apply`, `interpret_provisioning_plan`, `shared.aces.composition_envelope` | Keep one no-I/O path for `validate()` and `apply()` and refuse dispatch on any error. |
| Runtime non-approximation | ACES `realization_disclosure` / `CONCERN_PAYLOAD_PATH`, Shifter `_snapshot_entry` concern echo | Preserve the upstream gate for node/OS/content; add only the missing account-feature equivalent. Do not monkey-patch ACES internals. |
| Transport validation | `serialize_provisioning_plan`, `shifter/engine/provisioner/aces_plan.py::parse_plan` | The serialized ACES plan remains the only platform-to-provisioner contract; no capability DTO crosses the boundary. |
| Realization evidence | `aces_composition.py`, `aces_gcp_composition.py`, `aces_gcp_apply.py`, their provisioner tests, and `test_composition_realization_e2e.py` | A manifest term requires a real guest effect and cross-boundary proof; parser fields, marker files, and structural directories are not substitutes. |
| Dispatch/persistence | `shared.aces.package_loader`, `cms.aces.dispatch`, `engine.services.create_aces_range`, `engine.ecs` | All validation completes before `range_config`, operation receipt, ECS/local task, or cloud mutation. |
| Errors/logging | ACES `Diagnostic`, `shared.log_sanitize`, provisioner `log_redact`, `cms.exceptions.CMSError` | Return stable bounded diagnostics and preserve the generic user-facing rejection; do not raise payload-bearing exceptions. |
| Feature flag/config | `config/_aces_settings.py`, `config/env-manifest.json`, `shifter/installation/runtime_inventory.py` | Reuse `SHIFTER_ACES_NATIVE_PROVISIONING` (default off); add no setting or env variable. |
| Architecture enforcement | `.importlinter`, `scripts/check_layer_imports`, `scripts/adr_guard` | Keep `aces_*` imports inside `shared.aces`/tests and all existing repo gates enabled. |

## Cross-Cutting Layers

- **SDL shape and policy:** ACES Pydantic models first validate account/content
  shapes. `RuntimeManager.plan` then applies the manifest using the canonical
  content type and account-feature vocabulary. Removed terms must fail here for
  normal launches.
- **Backend validate/apply:** `ShifterProvisioner.validate()` and `apply()` both
  funnel through `_serialized_for_apply`. The independent account realization
  check belongs in that common path and must cover every materialized
  account-placement payload, including non-DELETE operations if operations and
  resources diverge. `apply()` must not call the dispatch port after a failure.
- **Runtime result contract:** ACES `backend_calls` continues to validate
  `ApplyResult`, snapshot transitions, and SEM-218 node/OS/content evidence. Do
  not encode account values in snapshot payloads merely to make a comparison
  pass; normalized governed feature names are the maximum permissible evidence.
- **Auth surface:** no endpoint or permission changes are needed. ACES launch
  continues through `create_aces_native_range`, which reuses user, scenario,
  launchability, active-range, ownership, and audit controls. Manifest or
  conformance status is not authorization.
- **Persistence surface:** a rejected plan must never reach
  `engine.Range.range_config`, operation receipts, outbox events, or ACES
  sidecars. No model, migration, record kind, or retention change is needed.
- **Secret handling:** account values, password-strength/authentication details,
  SPNs, inline sensitive content, source payloads, private keys, and provider
  data remain out of diagnostics, logs, events, audit records, snapshots, and PR
  evidence. `supports_accounts` does not mean Shifter provisions a participant
  credential.
- **OS/process exposure:** local/ECS dispatch remains the structured argv
  `aces-range provision --request-id <uuid>`; the plan remains DB-backed. Do not
  place account/content payloads in argv, env overrides, shell fragments, or
  workflow output. Existing bash/PowerShell quoting and identifier validation
  are defense in depth, not evidence that an excluded capability is realized.
- **Error envelopes:** plan/apply rejection stays an ACES `Diagnostic`, is
  bounded by `shared.aces.package_loader`, and becomes the existing generic
  `CMSError` at the product boundary. Raw ACES, guest-bootstrap, GCE, Terraform,
  SSH/SSM, or parser exceptions must not cross that boundary.
- **Observability:** capability names, stable diagnostic codes, addresses, and
  request-id fingerprints are sufficient. The redacted operation/snapshot
  sidecars remain topology/status evidence and must not become a second
  capability ledger.
- **Configuration/workflows:** no new runtime config, Terraform, Kubernetes,
  CI job, or workflow is required. Existing pytest/conformance suites,
  import-linter, layer checks, secret scanning, and ADR guard remain the
  canonical verification path.

## Extensibility Seam

The seam is a parameterized pair of envelopes at the shared ACES boundary:

1. the public declaration (`ProvisionerCapabilities`); and
2. the independent evidence-backed account-feature realization policy consumed
   by the common validate/apply diagnostics.

They must agree in production but must not be auto-derived from each other; a
negative test must be able to widen the manifest while leaving realization
evidence unchanged and observe a rejection at apply time. A sibling issue may add
one account feature to both only after the provisioner genuinely implements it
and cross-boundary tests prove the effect.

Content remains governed by the public type-level capability. Re-add `file`
only after every file shape admitted by the pinned ACES contract (including
source-backed files) is genuinely delivered, or after a released ACES contract
provides a public conditional-capability seam. Do not invent a Shifter-only
`constraints` string to distinguish inline and source-backed files.

## Regression Evidence Expectations

- Publication tests assert the exact narrowed account/content sets, published
  model validity, profile inference, backend-owned-detail exclusion, and
  builder/artifact equality.
- Real ACES planning tests prove `auth_method`, `spn`, `dataset`, and both inline
  and source-backed `file` fail before dispatch, while supported composition
  still plans.
- RuntimeTarget tests prove the same common gate serves `validate()` and
  `apply()`, a declared-but-not-evidence-backed account feature fails apply, no
  dispatch occurs, and the diagnostic contains the governed feature name but
  not its authored value.
- Capability-envelope tests cover resources and non-DELETE operations without
  double-reporting. DELETE operations do not materialize a feature and should
  not be rejected for their historical payload.
- Conformance tests prove the narrowed manifest still passes the
  `provisioning-only` fixture/live target gates. Profile inference alone is not
  realizability evidence: adding an unsupported provisioner term can leave the
  profile unchanged, so a negative honest-ledger case is required.
- Cross-boundary composition tests distinguish reachable, declared behavior
  from dormant renderer code. The current inline-file E2E fixture must not be
  cited as manifest support after `file` is removed; it should either exercise
  retained terms or be explicitly scoped as provisioner-only future evidence.
- Diagnostics remain single-line, bounded, and free of account values, inline
  content, secret/provider substrings, and raw payloads.

## Whole-Repo Scope

The implementation must evaluate changes against:

- `docs/adr/index.yaml` ADR-031 and ADR-032
- `docs/architecture/aces-cutover-evidence-1264.md`
- `docs/architecture/aces-provisioning-plan-transport-preflight-1522.md`
- `shifter/shifter_platform/shared/aces/manifest.py`
- `shifter/shifter_platform/shared/aces/backend-manifest.json`
- `shifter/shifter_platform/shared/aces/composition_envelope.py`
- `shifter/shifter_platform/shared/aces/runtime_target.py`
- `shifter/shifter_platform/shared/aces/package_loader.py`
- `shifter/shifter_platform/tests/shared/aces/test_backend_manifest_publication.py`
- `shifter/shifter_platform/tests/shared/aces/test_backend_conformance_gate.py`
- `shifter/shifter_platform/tests/shared/aces/test_runtime_target.py`
- `shifter/shifter_platform/tests/shared/aces/test_composition_realization_e2e.py`
- `shifter/engine/provisioner/aces_plan.py`, `aces_composition.py`,
  `aces_gcp_composition.py`, `aces_gcp_apply.py`, and their tests as realization
  evidence; edits there are needed only if the issue changes realization
- `cms/aces/dispatch.py`, `engine/services/_aces_range.py`, `engine/ecs.py`, and
  `aces_range_ops.py` as unchanged dispatch/persistence boundaries
- `config/_aces_settings.py`, `config/env-manifest.json`, and installation
  runtime inventory as unchanged feature-flag/config boundaries
- `.importlinter`, `scripts/check_layer_imports/**`, `scripts/adr_guard/**`,
  `.gc/plan-rules.md`, and existing quality workflows

## Gotchas And Anti-Patterns

- `file` is one coarse capability. Keeping it because inline text works still
  admits source-backed files, so it is not an honest partial claim.
- ACES treats unset or `password` `auth_method` as a default, not an opt-in
  feature. Negative tests must use a non-default method so the canonical
  extractor actually emits `auth_method`; do not change the extractor locally.
- `password_strength` is not an account-feature capability in the pinned
  contract. Do not imply credential or password realization from
  `supports_accounts=True`.
- A marker file is not an SPN, a parent directory is not a source-backed file,
  and a destination directory is not a dataset. Parsing or preserving a field
  is not realization.
- The account feature set is not OS-conditional. Retained features need evidence
  across Linux and Windows or a separately tracked narrowing; one guest dialect
  must not silently approximate another.
- Echoing authored values into the provisional snapshot proves a commitment,
  not guest readback. Do not use echo-only tests as the sibling issue's evidence
  for re-declaration.
- Do not import or copy private `aces_backend_libvirt` helpers. Public ACES
  models, extractors, fixtures, and conformance APIs are the compatibility
  contract.
- Do not auto-generate the independent apply evidence policy from the manifest;
  that makes the future-overclaim test vacuous.
- `create_shifter_backend_components()` currently discards its `manifest`
  argument. Do not treat that as declaration/implementation agreement or derive
  the evidence policy from it; any test seam must keep the two envelopes
  independently variable.
- Do not add a capability table to CMS, engine, the provisioner CLI, database
  rows, sidecars, environment variables, Terraform, or Kubernetes.
- Do not delete dormant realization code merely to narrow admission. Code
  removal or completion belongs to the corresponding gap issue.
- A generic `provisioning-only` conformance pass does not prove every advertised
  content/account term. Keep term-level negative tests.
- Because accepted plans are persisted asynchronously, rollout must keep the
  default-off flag posture and check for already queued ACES plans that contain
  removed terms. This issue does not need a data migration or best-effort
  provisioner fallback.

## Non-Goals

- No credential, password/auth-method, Kerberos/realm/SPN, dataset, or
  source-package delivery implementation.
- No new ACES schema, profile, contract version, conditional capability
  vocabulary, or dependency upgrade.
- No new API/UI, auth scope, database model/migration, sidecar kind, event type,
  runtime setting, env variable, CLI argument, workflow, Terraform, Kubernetes,
  cloud, or secret-store change.
- No change to `SHIFTER_ACES_NATIVE_PROVISIONING`'s default-off posture and no
  ACES cutover.
- No replacement of the serialized ProvisioningPlan transport, CMS/engine
  service boundaries, request-id dispatch, or provisioner parser.
- No claim that #1563 closes adjacent feature-binding or cross-OS realization
  gaps; those require their own authoritative issue and evidence.

## Validation Expectations

For this architecture-only change:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

The future implementation must also run the targeted shared ACES tests,
provisioner composition tests if touched, ACES fixture/live conformance, Ruff,
format, and import-linter required by `.gc/plan-rules.md`.
