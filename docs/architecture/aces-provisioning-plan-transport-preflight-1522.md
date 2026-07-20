# ACES Provisioning Plan Transport Preflight

Issue: GitHub #1522, "REV1 ACES: make the provisioning plan transport
versioned and fail closed."

Status: pre-implementation architecture guidance. This note does not implement
the transport validator, runtime changes, tests, conformance runner changes, or
live validation.

## Boundary

#1522 is a contract-integrity blocker for ACES live realization (#1477) and
validation (#1264). The platform/provisioner boundary may continue to carry the
serialized ACES `ProvisioningPlan`; it must not become an unversioned, best-effort
map reader that can silently drop terms before cloud mutation.

ADR-024 remains the migration doctrine, ADR-031 remains the feature-flagged
parallel-path doctrine, and ADR-032 remains the realization doctrine. The
clarification in ADR-032 is intentional: a bounded process-local realization
projection is allowed only after the transport is validated; it is not a new
authoring contract, persisted schema, public DTO, or ACES replacement model.

## Architecture Decisions

- Treat the serialized plan envelope as a versioned transport contract with
  explicit producer metadata. Realization must reject unsupported contract or
  producer versions before any GCE/AWS/Terraform/SSH/SSM/guest mutation.
- Keep `shared.aces.runtime_target.serialize_provisioning_plan` as the producer
  and `shifter/engine/provisioner/aces_plan.py` as the consumer. Do not add a
  second producer, second persisted payload shape, or provisioner-side `aces_*`
  dependency.
- Consumer validation must be fail-closed for unknown resource types, malformed
  resource entries, duplicate addresses, duplicate aliases/names, dangling node
  network refs, ACL endpoint refs, and composition target refs.
- Compatibility tests must use public ACES APIs/fixtures, public conformance
  surfaces, or Shifter-owned serialized fixtures. Private reference-backend
  helpers such as `aces_backend_libvirt._payload` and private realization
  functions are not a compatibility contract.
- The `aces-sdl` upgrade policy must be explicit: supported producer/contract
  versions live with the ACES shared constants/manifest metadata, dependency
  metadata agrees with ADR wording, and upgrades are gated by consumer negative
  tests plus ACES conformance tests.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Migration and cutover doctrine | `docs/architecture/aces-migration-adr.md`, ADR-024, `docs/architecture/aces-migration-parity-inventory.yaml` | Keep ACES parallel, feature-gated, and parity-gated. |
| RuntimeTarget producer | `shared.aces.runtime_target`, especially `interpret_provisioning_plan` and `serialize_provisioning_plan` | Add version/producer metadata at the one producer boundary; do not fork serialization. |
| Contract/profile constants | `shared.aces.contracts`, `shared.aces.manifest`, `shared/aces/backend-manifest.json` | Keep supported ACES contract/profile/version metadata in one shared place. |
| Provisioner consumer | `shifter/engine/provisioner/aces_plan.py`, `aces_composition.py`, `aces_range_ops.py` | Validate before returning `AcesPlan` or calling `apply_aces_range_cell` / destroy. |
| Image and realization policy | `aces_gce_image.py`, `aces_image_resolver.py`, `aces_gcp_apply.py`, `aces_gcp_firewall.py`, tenant image registry readers in `provisioner_db.py` | Keep concrete image/sizing/network/cloud choices backend-owned. |
| Event/status projection | `events.py`, `RangeEventOutbox`, `cms.handlers.range_events.apply_range_status`, `reconcile_range_events`, `shared.aces.projections` | Transport failure becomes sanitized operation/range failure, not a new lifecycle. |
| Sanitization | `shared.log_sanitize`, provisioner `log_redact`, bounded diagnostics in `shared.aces.runtime_target` | Log ids, versions, resource addresses, and classes only; do not dump payload bodies. |
| API/errors | `shared.api.errors`, `shared.errors`, `shared.exceptions.CMSError`, existing provisioner exception translation | Do not create an ACES-only exception hierarchy or expose raw provider/parser errors. |
| Import enforcement | `.importlinter`, `scripts/check_layer_imports`, `scripts/adr_guard` | Keep `aces_*` imports in `shared.aces` and tests; the provisioner consumes plain data. |
| Tests/conformance | `tests/shared/aces/test_runtime_target.py`, `test_backend_conformance_gate.py`, provisioner `tests/test_aces_plan.py`, `test_aces_range_ops.py` | Add negative/version-skew coverage beside existing ACES tests instead of new harnesses. |

## Cross-Cutting Layers The Design Must Pass

- ACES contract/profile validation: producer-side validation stays in
  `interpret_provisioning_plan`, `shared.aces.manifest`, and ACES conformance
  tooling. Shifter must not duplicate ACES profile inference.
- Transport shape validation: the consumer must validate envelope kind,
  contract version, producer id/version, JSON-object shape, resource entry
  shape, known resource types, identities, aliases, dependency fields, and every
  topology reference before returning an `AcesPlan`.
- Security and secret handling: serialized plans and diagnostics must not carry
  provider credentials, secret values, private keys, generated runtime config,
  Terraform variables, SSM command text, token-bearing URLs, or full payload
  dumps. Composition inline content marked sensitive must not be logged.
- OS/process exposure: no ACES payload bodies, secrets, provider variables, or
  generated commands may be passed through process argv, shell strings,
  workflow summaries, SSM documents, Kubernetes env literals, or Terraform args.
  Existing request-id keyed provisioner CLI invocation remains the boundary.
- Error envelopes: provisioner parse/validation failures may become failed range
  status with bounded messages, but raw ACES, Terraform, cloud, SSH, SSM, guest,
  or parser exceptions must stay behind sanitized diagnostics/logs.
- Runtime env/config validators: no opportunistic `ACES_*` env reads for
  supported versions. If an operator-configurable compatibility window is ever
  needed, add it through typed settings, env-manifest/runtime inventory, and
  renderer tests.
- Auth surface: #1522 should not add user-facing endpoints. If evidence is
  later surfaced, existing CMS/Mission Control session/API-token permissions and
  owner checks must run before projection lookup.
- Persistence surface: `range_config` continues to hold the serialized plan for
  the ACES path. Do not persist the provisioner realization projection as a
  second source of runtime truth.
- Cloud mutation boundary: validation must complete before `apply_aces_range_cell`,
  `destroy_aces_range_cell`, Terraform, provider SDKs, SSH/SSM executors, guest
  bootstrap, or image resolution that could mutate or allocate resources.
- Workflow/repo guards: ADR guard, import-linter, layer checks, provisioner
  tests, ACES shared tests, and stack-native checks required by touched paths
  remain hard gates.

## Extensibility Seam

The seam is the transport metadata and validator policy, not a new schema
family. The first supported compatibility set should name:

- transport/envelope kind and contract version;
- producer name and producer package/version;
- supported resource-type set;
- supported ACES SDL/compiler version window or exact set.

A later ACES version, backend profile, resource type, or producer should add one
entry to that policy plus public-fixture/conformance evidence. It should not
require copying parser logic into CMS, CTF, Mission Control, engine services, or
Terraform/provider modules.

## Whole-Repo Scope

Future implementation must evaluate changes against:

- `docs/adr/index.yaml` ADR-031 and ADR-032
- `docs/architecture/aces-migration-adr.md`
- `docs/architecture/aces-runtime-target-backend-manifest-preflight-1233.md`
- `docs/architecture/aces-backend-conformance-gate-preflight-1263.md`
- `docs/architecture/rev1/architecture.md` A1
- `shifter/shifter_platform/shared/aces/runtime_target.py`
- `shifter/shifter_platform/shared/aces/contracts.py`
- `shifter/shifter_platform/shared/aces/manifest.py`
- `shifter/shifter_platform/shared/aces/backend-manifest.json`
- `shifter/shifter_platform/pyproject.toml` and dependency lock metadata when
  the `aces-sdl` version changes
- `shifter/shifter_platform/tests/shared/aces/**`
- `shifter/engine/provisioner/aces_plan.py`
- `shifter/engine/provisioner/aces_composition.py`
- `shifter/engine/provisioner/aces_range_ops.py`
- `shifter/engine/provisioner/aces_gcp_apply.py`
- `shifter/engine/provisioner/aces_gcp_firewall.py`
- `shifter/engine/provisioner/aces_gce_image.py`
- `shifter/engine/provisioner/provisioner_db.py`
- `shifter/engine/provisioner/tests/test_aces_plan.py`
- `shifter/engine/provisioner/tests/test_aces_range_ops.py`
- `.importlinter`, `scripts/check_layer_imports/**`, `scripts/adr_guard/**`

## Gotchas And Anti-Patterns

- Do not silently skip unknown resources or malformed composition terms.
- Do not drop dangling network, ACL, account, content, or feature target refs.
- Do not default unsupported or malformed versions to "current."
- Do not treat private reference-backend helpers as Shifter's compatibility
  oracle; use public ACES APIs/fixtures or Shifter-owned fixtures.
- Do not make `AcesPlan*` dataclasses a public schema, persisted model, API DTO,
  or authoring vocabulary.
- Do not infer images, providers, subnets, secrets, machine types, or lifecycle
  behavior from scenario ids, file paths, os_family, or Polaris-specific names.
- Do not add a second exception hierarchy, status enum, event bus, validator
  package, manifest source, or upgrade-policy document.
- Do not weaken ADR/import/conformance checks to make a version-skew test pass.

## Non-Goals

- No implementation of the transport validator in this preflight.
- No live cloud, Terraform, GCP, AWS, SSH, SSM, Docker, or guest execution.
- No change to the default-off ACES-native provisioning flag.
- No cutover to ACES and no closure of #1477 or #1264.
- No new ACES profile claim beyond `provisioning-only`.
- No new CMS/API/UI endpoint, data migration, runtime env var, Terraform input,
  Kubernetes manifest, secret store, or workflow unless a later implementation
  explicitly changes that surface.
- No replacement of existing Shifter range specs, engine models, status/event
  paths, or provisioner provider factories.

## Validation Expectations

For this architecture note, run:

```bash
python3 scripts/adr_guard/adr_guard.py --files docs/adr/index.yaml docs/architecture/aces-provisioning-plan-transport-preflight-1522.md --level fast
```

The future implementation must also run the ACES shared tests, provisioner ACES
tests, negative/version-skew transport tests, public-fixture/conformance gates,
and any stack-native checks required by the files it touches.
