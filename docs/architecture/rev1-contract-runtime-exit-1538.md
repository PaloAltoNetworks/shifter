# REV1.2 Contract And Runtime Architecture Exit-Verification Record (#1538)

Status: contract-and-runtime exit-verification evidence record

Date: 2026-07-28

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1538>

Design source: `docs/architecture/rev1-contract-runtime-exit-preflight-1538.md`

Gate baseline: `origin/dev` at `00243876efe4` (the commit this record was authored
against). The immutable per-revision capture is the routed Quality run at this
gate's own pull-request head SHA; each automated row below also cites the
already-merged producer evidence that stands independently of this run.

## What this is

The reviewed evidence bundle for the REV1.2 (Contract and Runtime Architecture)
milestone exit criterion: *the ACES/RAES process boundary is versioned and
rejects partial plans; provider-selection and backend boundaries fail closed;
and the named runtime blockers are complete with linked evidence*. Each row
names the gate claim, its canonical producer at the current RAES revision, the
gate posture, the evidence status, and the immutable locator with observed
conclusion (or the explicit fail-closed limitation and its owner).

The historical issue wording says "ACES". The repository has since completed the
incompatible RAES naming/contract cut (ADR-024, #1862): current producers, tests,
and commands use the `raes==2.0.0` / `raes-env-packs==3.0.0` contracts and
`shared.raes` paths. ACES names in merged blocker final-reports are the code
state at those merge SHAs and are cited as-is; the current gate revision holds
the renamed `raes_*` producers.

## What this is not

This record does not re-run a gate, re-decide a verdict, copy logs, snapshots,
provider output, or gate definitions, or introduce any schema, parser, status
enum, service, workflow, or persistence. It does not implement or remediate any
blocker, capture fresh live evidence, alter provider support, change runtime or
cloud state, or resolve the selector contradiction disclosed below. It never
manufactures stronger evidence than a producer emits: a row is `captured` only
when it cites an immutable producer-owned report or run reference with the
observed conclusion; otherwise it is `live-manual` residual with a named owner.
A closed issue, source path, test name, generated manifest, configured image
mapping, deployed VM, firewall object, or successful command is not, by itself,
execution evidence for the claim.

## Column semantics

- **Gate posture**: `blocking` (a failure blocks the routed pull-request or merge
  path), `advisory` (runs but does not block), `live-manual` (evidence is
  produced by a deliberate run in a deployed environment, not by pull-request
  CI), or `not-implemented` (no gate exists yet).
- **Evidence status**: `captured` only when the row cites an **immutable
  producer-owned locator** — a merged implementation issue's `gc:final-report`
  record and its PR merge SHA, or a pinned routed CI run — plus the observed
  conclusion. Unnamed gate execution, a source path, a test name, "the routed
  lane at the gate SHA", and any local pre-push test run are **not** capture —
  they are non-authoritative confirmation, never the capture basis. Because this
  exit record is a documentation-only change, this gate PR's own routed code
  test lanes are path-filtered and **skip**; they neither capture nor confirm
  the producers. Each producer's immutable capture is therefore the routed run
  at its merge SHA (cited via its `gc:final-report`), and the only same-tree
  confirmation is the local pre-push producer run. A row lacking an immutable
  locator is `not-yet-demonstrated` (or `live-manual`), and the final column
  states the owned residual limitation and what a live capture would require.
- The three "conformance" meanings stay distinct: installation backend-bundle
  configuration conformance, RAES manifest/profile conformance, and provider
  range-substrate lifecycle conformance. A pass in one is not evidence for
  another. Bundle conformance is not proof that RAES realizes on a provider.

## Native blocking dependencies

The six native `blocked_by` dependencies of #1538 are complete and merged to
`dev`, each with an immutable final-report record on its issue thread. A
dependency-chain issue may support a claim row but cannot replace one of these
six closure records.

| Issue | Title | State | Immutable record (PR, merge SHA, observed conclusion) |
| --- | --- | --- | --- |
| #728 | Migrate AWS support into a backend bundle | closed | [final report](https://github.com/Brad-Edwards/shifter/issues/728#issuecomment-4961616091): PR #1635 merge `efa424a1c02b`, CI green |
| #729 | Migrate GCP support into a backend bundle | closed | [final report](https://github.com/Brad-Edwards/shifter/issues/729#issuecomment-4962543409): PR #1640 merge `94695f59f6c4`, CI green |
| #1562 | Open reachability firewalls for authored service ports | closed | [final report](https://github.com/Brad-Edwards/shifter/issues/1562#issuecomment-4952769018): PR #1608 merge `2f089ad32f9f`, CI green |
| #1566 | Tenant-facing management surface for the image registry | closed | [final report](https://github.com/Brad-Edwards/shifter/issues/1566#issuecomment-4964322351): PR #1642 merge `a0e83b3ee208`, CI green |
| #1567 | Object-storage-backed package sources at launch | closed | [final report](https://github.com/Brad-Edwards/shifter/issues/1567#issuecomment-4965570738): PR #1651 merge `bad73fb4b27c`, CI green |
| #1569 | Verify composition realization in-guest | closed | [final report](https://github.com/Brad-Edwards/shifter/issues/1569#issuecomment-5027628582): PR #1788 merge `f5b580a80e62`, CI green |

## Evidence index

| Gate claim | Canonical producer (current RAES revision) | Gate posture | Evidence status | Immutable locator + observed conclusion, or owned residual limitation |
| --- | --- | --- | --- | --- |
| Fail-closed RAES transport + negative topology | `shared/raes/{runtime_target,domain_topology,contracts}.py`, `engine/provisioner/raes_plan.py` + `raes_plan_domain.py`, `raes_service.py`; parity `tests/shared/raes/test_plan_provisioner_parity.py` | `blocking` | `captured` | [#1522 final report](https://github.com/Brad-Edwards/shifter/issues/1522#issuecomment-4942756318) (transport versioned + fail-closed, PR #1556 merge `8e0a9f3ceb0c`) and [#1606 final report](https://github.com/Brad-Edwards/shifter/issues/1606) (domain-topology expressivity, PR #1703 merge `23cf1d25a35a`): producer version pinned (`SUPPORTED_RAES_VERSION = "2.0.0"`, ADR-032-R7); consumer validates transport/producer version and rejects unknown resources, dangling refs, and unsupported domain profiles before any mutation; negatives in `test_domain_topology_admission.py`, `test_plan_provisioner_parity.py`, provisioner `test_raes_plan.py`. Confirmation only: the local pre-push provisioner/platform subset runs are green (this doc-only PR's routed code lanes path-skip). |
| Explicit root-configured, fail-closed provider selection | `installation/{loader,schema,registry}.py`, backend renderers, `installation/runtime_inventory.py`, `config._runtime_env.resolve_cloud_provider`, provisioner `config.resolve_cloud_provider`, cloud factories | `blocking` | `captured` | [#728 final report](https://github.com/Brad-Edwards/shifter/issues/728#issuecomment-4961616091) (PR #1635 merge `efa424a1c02b`) and [#729 final report](https://github.com/Brad-Edwards/shifter/issues/729#issuecomment-4962543409) (PR #1640 merge `94695f59f6c4`) deliver the `installation` registry/loader/schema where selection lives; [#1323 final report](https://github.com/Brad-Edwards/shifter/issues/1323#issuecomment-4954696346) (versioned backend-bundle contract, PR #1626 merge `126b10750b65`) governs it. The selected root backend renders one explicit `CLOUD_PROVIDER` to portal/worker/provisioner roles; missing/unknown deployed values and registered-but-unsupported capabilities fail closed; test/debug defaults are not deployed-provider evidence. Confirmation only: the local pre-push installation run is green (0 failures; this doc-only PR's routed code lanes path-skip). |
| AWS backend contract/conformance (#728) | AWS `BackendBundle`, closed `AwsSettings`, secret-reference grammar, `installation/publication.py`, `installation/published_contract/`, checked `examples/aws.yaml`, doctor/check front doors | `blocking` | `captured` | [#728 final report](https://github.com/Brad-Edwards/shifter/issues/728#issuecomment-4961616091) (PR #1635 merge `efa424a1c02b`): drift, breaking-change, registry-conformance, example, loader, closed-settings, secret-reference, and generated-output-classification gates. Confirmation only: the local pre-push run of these producers is green (this doc-only PR's routed code lanes path-skip). Scope: configuration/bundle conformance, not proof RAES realizes on AWS. |
| GCP backend contract/conformance (#729) | GCP `BackendBundle`, closed `GcpBackendSettings`, secret-reference grammar, runtime-env renderer/inventory, published contract/snapshot, checked `examples/gcp.yaml`, doctor/check front doors | `blocking` | `captured` | [#729 final report](https://github.com/Brad-Edwards/shifter/issues/729#issuecomment-4962543409) (PR #1640 merge `94695f59f6c4`): the same contract gates as AWS plus GCP renderer/inventory parity (`test_gcp_bundle.py`, `test_settings_gcp.py`). Confirmation only: the local pre-push run of these producers is green (this doc-only PR's routed code lanes path-skip). Does not by itself prove GCE/GDC range lifecycle or in-guest realization. |
| RAES manifest/profile conformance | `shared/raes/manifest.py`, checked `shared/raes/backend-manifest.json`, `tests/shared/raes/{test_backend_conformance_gate,test_backend_manifest_publication}.py` (RAES `raes_conformance` oracle, `provisioning-only` profile) | `blocking` | `captured` | [#1263 final report](https://github.com/Brad-Edwards/shifter/issues/1263#issuecomment-4911090404) (backend conformance gate, PR #1436 merge `0ae01a8fecb9`) and [#1261 final report](https://github.com/Brad-Edwards/shifter/issues/1261#issuecomment-4880294279) (published provisioning-only manifest, PR #1317 merge `9b120e979a2b`): manifest builder ↔ published artifact byte parity and the external `raes_conformance` runner passing against the published manifest with a non-vacuous capability set. Confirmation only: the local pre-push run of these producers is green (this doc-only PR's routed code lanes path-skip). Manifest/profile conformance only — not package conformance, launchability, guest realization, or live-target evidence. |
| Authored service reachability (#1562) | RAES `Node.services`, provisioner `raes_service.py`, `raes_gcp_firewall.py`, GCE firewall plan/apply/destroy, authored-ACL precedence | `blocking` (plan/parser) + `live-manual` (reachability) | `captured` (plan/parser) | [#1562 final report](https://github.com/Brad-Edwards/shifter/issues/1562#issuecomment-4952769018) (PR #1608 merge `2f089ad32f9f`): provisioner `test_raes_gcp_firewall.py` covers TCP/UDP ingress derivation, port aggregation, source dedupe, and **empty-sources fail-closed**. Confirmation only: the local pre-push run (159-test provisioner subset) is green (this doc-only PR's routed code lanes path-skip). A firewall object is L4 intent, not a ready listener: a live same-range allow/deny probe is `live-manual` (owner: REV1.3 live-range matrix, tracked by #987/#1264). |
| Tenant-manageable image mappings (#1566) | `engine.services._raes_image`, `RaesImageMapping`, `cms/api/raes_image_registry.py`, `raes_image_registry` command, provisioner read resolver | `blocking` | `captured` | [#1566 final report](https://github.com/Brad-Edwards/shifter/issues/1566#issuecomment-4964322351) (PR #1642 merge `a0e83b3ee208`): platform `test_raes_image_registry_command.py`, `services/test_raes_image.py`, `cms/test_raes_image_registry_api.py` cover authorized register/list/soft-disable through the service seam, exact-/any-version read, and missing/disabled mapping rejected before realization. Confirmation only: the local pre-push run of these producers is green (this doc-only PR's routed code lanes path-skip). No concrete provider image id is exposed here. |
| Digest-verified object-backed package launch (#1567) | `shared/raes/object_source.py` (`stage_object_pack`), provider-neutral `ObjectStorage`, `cms/scenarios/pack_validation`, `shared/raes/package_loader.py`, `_raes_range_create` | `blocking` | `captured` | [#1567 final report](https://github.com/Brad-Edwards/shifter/issues/1567#issuecomment-4965570738) (PR #1651 merge `bad73fb4b27c`): platform `test_object_source.py`, `test_package_loader.py` cover immutable object identity, bounded extraction, traversal/link/special-file rejection, pack validation, associated-artifact digest, single-SDL selection, and cleanup. Confirmation only: the local pre-push run of these producers is green (this doc-only PR's routed code lanes path-skip). A successful download or extraction alone is not a package launch. |
| Real composition + sanitized in-guest outcome (#1569) | canonical `scenario-dev/shifter-raes-validation` pack, `run_raes_backend_validation`, `cms/raes/validation.py`, Engine operation-result apply, `shared/schemas/raes_operation.py`, provisioner `raes_composition_verification.py` + realization/probes | `blocking` (mechanism) + `live-manual` (realization) | `captured` (mechanism); `not-yet-demonstrated` (live) | Mechanism: [#1569 final report](https://github.com/Brad-Edwards/shifter/issues/1569#issuecomment-5027628582) (PR #1788 merge `f5b580a80e62`) — ranges reach `READY` only after content/accounts/features verify on every concrete guest target, snapshots are sanitized, and backend validation rejects topology-only success; gated by provisioner `test_raes_composition_verification.py`, `test_raes_content_delivery.py`, platform `cms/raes/test_validation.py`, `test_run_raes_backend_validation.py`, e2e `test_composition_realization_e2e.py` (local pre-push run green; this doc-only PR's routed code lanes path-skip). **Live residual:** a deployed normal-path `run_raes_backend_validation` run reaching `READY` with a non-vacuous allowlisted snapshot of verified content/account/feature entries is `live-manual` and **not captured this run** (record-and-cite depth chosen). Owner: REV1.3 release-evidence gate #1539 via `docs/architecture/rev1-release-evidence-index-1540.md` ("ACES realization (live)" row) and `docs/architecture/aces-cutover-evidence-1264.md`. Unit/e2e tests, VM creation, command exit, or seeded rows do not substitute. |

One live run may support more than one row (an object-backed validation pack can
also produce #1569 evidence), but the rows and conclusions stay separate so one
missing assertion cannot be hidden by a generally successful launch.

## Deliberate fail-closed limitations (tested, not prose)

Each limitation is material to a gate claim; the current capability authority
excludes it and a negative test or admission check proves the boundary fails
closed. A limitation is never rendered as a pass.

- **RAES profile is `provisioning-only`.** The published manifest and
  `raes_conformance` run assert the provisioning profile only; participant-runtime
  and other profiles are out of this gate's claim. Producer: `shared/raes/manifest.py`,
  `test_backend_conformance_gate.py`.
- **IPv4-only network family.** GCE network address-family admission rejects
  non-IPv4 topology terms fail-closed. Producer: provisioner `raes_plan_domain.py`
  / network-family admission (see `aces-gce-network-address-family-preflight-1568.md`).
- **Exact RAES contract version.** Only `raes==2.0.0` / `raes-env-packs==3.0.0`
  are accepted; unknown producer/transport versions are rejected, not coerced.
  Producer: `raes_plan.py` (`SUPPORTED_RAES_VERSION`), `test_plan_provisioner_parity.py`.
- **Live RAES realization adapter is GCE-only.** The RAES launch service admits
  only the GCE VM range-cell adapter. **AWS and GDC RAES realization are recorded
  as fail-closed limitations for the live-RAES claim** — a green AWS/GCP backend
  bundle does not imply a RAES realization adapter exists for that provider, and
  `CLOUD_PROVIDER=gcp` does not imply GDC support. Producer:
  `_assert_raes_adapter_supports` / provider-range-backend admission.
- **Reachability is L4 exposure intent.** `Node.services` and derived firewalls
  express allowed paths; they do not install listeners, prove readiness, or grant
  participant authorization.

## Selector contradiction resolved

The gate baseline originally disclosed that runtime selectors remained despite
ADR-024's hard-cut decision. Issue #1311 removed those selectors from validation,
catalog, image-management, application settings, and deployment renderers. This
historical REV1.2 verdict remains bounded to the runtime-verification boundary
named by #1538; the later hard-cut evidence is recorded by #1311.

## Concept boundaries (the several meanings of "provider")

None may be inferred from another:

- root installation backend: `shifter.yaml backend` (`aws` or `gcp`);
- derived runtime cloud adapter family: `CLOUD_PROVIDER`;
- GCP range substrate: `GCP_RANGE_BACKEND` (`gce` or `gdc`);
- RAES concrete image-mapping/realization provider: currently `gce`;
- identity provider: `AUTH_PROVIDER`;
- RAES backend profile: `provisioning-only`.

## Boundaries

This record contains only commit, pull-request, run, and report references,
public producer/test identifiers, closed reason/status/profile classes, bounded
counts, timestamps, and conclusions. It carries no tokens, user email, secret
references or values, range/scenario/request identifiers, internal addressing,
concrete image refs, object bucket/key coordinates, provider identifiers or
payloads, Terraform state/plan/output, guest output, or raw RAES runtime
snapshots. It executes on no runner, deploy host, or guest and requires no new
endpoint, workflow permission, or credential.

## Consumed by

The REV1.2 exit (#1538) links this bundle to confirm the ACES/RAES process
boundary is versioned and fails closed, provider selection and backend
conformance are demonstrated for both supported paths, and the six native
runtime blockers are complete with linked evidence — while the live-RAES
realization residual and the selector contradiction remain explicit and owned.
The REV1.3 release-verification gate #1539 then captures the deployed-environment
live-realization evidence at the release SHA per
`docs/architecture/rev1-release-evidence-index-1540.md`.
