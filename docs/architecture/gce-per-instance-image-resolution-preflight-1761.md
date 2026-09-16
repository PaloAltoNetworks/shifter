# GCE Per-Instance Image Resolution Preflight (#1761)

> **Historical boundary (issue #2062, 2026-08-19):** TechVault is a
> scenario pack. APTL is the former name of LilRAE. The bespoke Shifter
> implementation described here was retired by the RAES hard cut. Exact
> historical commands, paths, symbols, image keys, and workflow names below
> remain factual evidence; they are not current product or integration
> boundaries.

Status: pre-implementation architecture guidance

Date: 2026-07-20

Issue: GitHub #1761, "gcp: GCE resolves range guest images globally per role
(ignores per-instance ami_key), so only one Kali-image scenario is servable at
a time"

The issue title, body, and acceptance criteria are the shipping contract. This
note fixes the design boundary and does not implement the issue or provide an
implementation plan.

## Decision Boundary

The legacy scenario `ami_key` is a logical image selector, not an AWS AMI id,
GCE image URL, GCE family name, ACES source identity, or machine type. The
scenario-owned compatibility adapter may use that already-authored selector to
choose a backend-owned GCE profile. It must never pass the value to Compute
Engine, concatenate it into a provider resource path, or infer a family name.

Keep the existing four logical GCE profile classes (`linux`, `kali`, `windows`,
and `dc`). Add one optional, bounded, non-secret backend mapping parameter,
`GCP_RANGE_IMAGE_KEY_PROFILES_JSON`, with this closed shape:

```json
{
  "kali": {
    "polaris-vm": {
      "source_image": "projects/example/global/images/family/shifter-polaris-vm",
      "machine_type": "e2-standard-8",
      "disk_size_gb": 210,
      "disk_type": "pd-balanced",
      "bootstrap_capability": "polaris-docker-host"
    }
  },
  "dc": {
    "polaris-dc": {
      "source_image": "projects/example/global/images/family/shifter-polaris-dc",
      "machine_type": "e2-standard-4",
      "disk_size_gb": 100,
      "disk_type": "pd-balanced",
      "bootstrap_capability": "prepromoted-domain-controller",
      "domain_dns_name": "boreas.local",
      "domain_netbios_name": "BOREAS"
    }
  }
}
```

Each entry is a complete `GCERangeImageProfile`; it does not inherit sizing,
disk policy, or realization capabilities from a mutable global role profile.
The typed `bootstrap_capability` selects a realizer behavior without branching
on the logical image key. Pre-promoted DC profiles additionally bind the baked
DNS and NetBIOS identity. Complete entries avoid recreating the current coupling
where selecting the Polaris image also requires swapping the global Kali disk
size to 210 GB. The existing `GCP_RANGE_{LINUX,KALI,WINDOWS,DC}_*` variables
remain the defaults for instances whose `ami_key` is absent or blank.

Resolution is exact and fail closed:

1. Derive the existing logical profile class once from validated `role` and
   `os_type` using `GCERangeCellConfig.get_profile`'s current precedence.
2. With no `ami_key`, return the existing default profile unchanged.
3. With a non-empty `ami_key`, require an exact entry under that logical profile
   class and return that complete profile.
4. An unknown key, a key registered only under another profile class, or an
   invalid mapped profile is a pre-mutation configuration failure. Never fall
   back to the global profile for a keyed instance.

The map belongs in `GCERangeCellConfig`, and `get_profile` remains the single
profile-selection API. `gcp_range_cell_scenario._profile_for_instance` is the
only legacy adapter that reads `ami_key` and passes it to that API. The closed
range-cell request and digest-bound `RangeSpec` artifact do not gain another
field or schema.

No ADR change is required. This specializes the legacy scenario-realization
seam already allowed by ADR-030, ADR-039, and the scenario-to-cell contract. It
does not change lifecycle ownership, the public scenario contract, persistence,
the ACES realization model, or the image build/promotion source of truth.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Authoring authorization | `cms.api.permissions.CMS_WRITE_PERMISSIONS`, `cms.api.serializers.ScenarioInstanceSerializer`, and CMS scenario services | `ami_key` remains staff/authorized CMS-authored scenario intent. Do not add a participant-supplied image selector or image reference. |
| Launch authorization | Mission Control `LaunchRangeView`, CTF range gates, catalog `launchable` filtering, engine launch intents | Preserve actor, scenario visibility, active-range, throttle, backend-admission, and operation-generation checks. Image selection adds no launch bypass. |
| Scenario schema and transport | `cms.scenarios.schema.InstanceConfig`, `cyberscript.schemas.range.InstanceSpec`, persisted-envelope validation, `shared.range_cells.build_scenario_artifact` / `validate_gcp_vm_range_cell_request` | Reuse the existing `ami_key` field and digest-bound artifact. Do not add a GCP field, request DTO, or second validator tree. |
| Legacy realization | `gcp_range_cell_scenario._profile_for_instance`, `GCERangeCellConfig.get_profile`, `GCERangeImageProfile` | Extend this one compatibility seam and existing profile value object. Do not branch on scenario id or add Polaris/TechVault planners. |
| GCE config validation | `load_gce_range_cell_config`, `_validate_gce_image_reference`, `_validate_gce_range_profile`, `_VALID_GCE_DISK_TYPES` | Parse the map once into existing profiles and apply the same image, disk type, disk floor, and machine-type validation to every entry before any provider client is built. |
| Runtime config transport | `scripts/gcp/render_runtime_env.py`, `installation.runtime_inventory`, `engine.ecs._GCP_PROVISIONER_ENV_KEYS`, `shared.cloud.sensitive_env`, `GCPTaskRunner`, and both provisioner Job admission-policy manifests | Carry one canonical compact JSON value through the existing ConfigMap-to-Job literal-env path. Keep renderer, inventory, forwarding, and admission allowlists in parity. |
| Provider resources | `gcp_range_cell_plan`, `gcp_range_cell_resources.instance_resource`, `gcp_range_cells` create-or-observe lifecycle | Feed the selected existing profile into the existing instance plan/resource; preserve no-public-IP, Shielded VM, metadata, service-account, firewall, cleanup, and idempotency controls. |
| Persistence | Engine `Range`/`Instance` state, `gcp_range_cell_outputs`, and `state_helpers` provider metadata | Do not add a table or repository. Record only bounded non-secret selection evidence in existing GCP provider metadata when needed for reconciliation/audit. |
| Errors and logs | `RangeCellContractError`, provisioner `CloudError`, `terraform_ops._safe_failure_message`, `log_redact.safe_log_value` / `safe_log_fingerprint` | Reuse existing lifecycle failure/cleanup handling and sanitizers. Do not add an image exception hierarchy or expose the full map/provider response. |
| Regression evidence | provisioner `test_config.py`, `test_gcp_range_cells.py`, shared range-cell tests, renderer/inventory/parity tests, task-runner/admission tests | Extend the established suites; do not create a separate mapping harness or Python reimplementation of admission CEL. |

`provisioner_ami.get_ami_id` is the AWS behavioral precedent for honoring a
custom `ami_key`, but it is not the GCE resolver: its SSM/ConfigStore path and
AMI terminology must not be called from the GCE range-cell adapter.

The ACES `AcesImageMapping` model, `engine.services._aces_image`,
`provisioner_db_aces.get_aces_image_candidates`, and `aces_gce_image` already
solve a different problem: mapping authored ACES source name/version and
resources for the feature-gated ACES-native lifecycle. Reusing those rows for a
legacy `RangeSpec.ami_key` would conflate contracts and persistence ownership.
The two paths may share `GCERangeImageProfile` and its GCE shape validators, but
not identity, registry rows, API surfaces, or lookup rules.

## Cross-Cutting Layers The Design Must Pass

- **Auth and policy:** CMS authoring continues through `CMS_WRITE_PERMISSIONS`;
  range launch continues through the Mission Control/CTF permissions and
  launchable-scenario filters; backend selection remains server-derived. A
  caller can choose only an authorized scenario. It cannot submit an image ref
  or mutate the platform map through the range-launch API.
- **Scenario shape and provenance:** CMS Pydantic validation and hydration feed
  `InstanceSpec`; persisted-envelope validation normalizes it; the producer
  binds the artifact digest; `validate_gcp_vm_range_cell_request` verifies the
  closed request before `gcp_range_cell_scenario` interprets `ami_key`. The map
  is backend config, never copied into the authored artifact.
- **Mapping shape:** the canonical GCE config loader must reject malformed or
  oversized JSON, duplicate object keys, unknown profile classes, unknown entry
  fields, blank/unsafe mapping keys, non-string image/machine/disk types,
  non-positive or below-policy disk sizes, unsupported disk types, malformed
  image references, and an excessive number of entries. Validate every
  configured entry, not only the first one selected.
- **Renderer and env binding:** the GCP renderer may perform transport-only
  parsing and compact canonical serialization so a newline cannot inject a
  second generated-env assignment. Semantic authority stays in `_gce.py`.
  `runtime_inventory` must classify the key as optional public runtime config
  for portal/worker, provisioner, and range-task roles; `_GCP_PROVISIONER_ENV_KEYS`
  must forward it. Both base and Helm admission policies must allow it only as a
  literal whose value equals `platform-runtime`, with duplicate env names still
  rejected.
- **Secret-handling surface:** image family URLs and sizing are non-secret
  deployment config. `shared.cloud.sensitive_env.split_env` must classify this
  parameter as plain; it belongs in the ConfigMap and literal Job env, not the
  ephemeral Secret. Do not put credentials, signed URLs, image-build manifests,
  Packer inputs, or guest bootstrap secrets in the map.
- **Kubernetes and OS/process exposure:** the JSON may be visible in the
  ConfigMap, Job spec, pod environment, and Kubernetes audit data because it is
  deliberately non-secret. It must not appear in Job `args`, shell command
  strings, process argv, GCE metadata, startup scripts, or workflow command
  interpolation. The existing command remains `range <operation> --request-id
  <uuid>` and the hardened non-root/tokenless provisioner Pod shape is unchanged.
- **Cloud IAM and provider policy:** selection does not grant access. The
  provisioner GSA remains the only Compute mutator and mapped image families
  must be in an approved project it can use. A cross-project image requires the
  narrow image-project grant for that GSA; do not broaden portal/launcher
  identities or use public-image fallback to hide a missing grant.
- **Provider mutation and reconciliation:** all keyed profiles resolve before
  Compute/secret clients or resources are created. Create-or-observe must verify
  that an existing deterministic instance is bound to the expected resolved
  profile identity rather than accepting name-only drift after a ConfigMap or
  family change. Persist the selected logical key/profile reference through the
  existing provider-metadata surface; never create separate application state.
- **Destroy and compensation:** destroy derives deterministic resource names
  from the digest-bound scenario artifact and must not require the keyed image
  mapping or source image to still exist. A missing TechVault image mapping or a
  later-retired key must not strand already-created resources.
- **Errors and observability:** missing/mismatched mappings are fail-loud before
  mutation and flow through existing cleanup/status/event handling. Logs may
  carry request/range/instance correlation, logical profile, a validated key or
  fingerprint, and a stable failure category. User-visible errors name the
  missing configuration action without echoing the raw JSON, malformed value,
  provider body, or scenario payload. Existing generic provider errors are not
  a license to add another exception tree.
- **Persistence and events:** no map, credential, or raw provider response is
  written to `Range.range_config`, launch intents, events, or a new table. If
  selection evidence is persisted, use bounded non-secret fields under the
  existing GCP `provider_metadata`; public lifecycle status and event schemas
  remain unchanged.

## Extensibility Seam

The seam is the single structured map parameter keyed by `(logical GCE profile
class, legacy image key)`, whose values are complete `GCERangeImageProfile`
objects. Adding `techvault` after its GCE image exists, a second Kali-derived
scenario, a larger disk, or a different approved image family is a config entry
only when its typed bootstrap capability already has a GCE realizer. A new
bootstrap behavior requires one adapter capability implementation and evidence;
it must not be inferred from the logical key. This remains one structured
contract, not a new env-var family, schema field, per-image resolver branch,
workflow, or scenario-id conditional.

The map needs a documented size and entry-count bound and closed versionless
shape while it remains this small contract. A future incompatible shape would
require a new parameter name or explicit version; silently accepting extension
fields is prohibited. ACES source/version resolution remains its own versioned
registry seam.

## Whole-Repo Scope For The Intended Design

- Scenario/auth producers: CMS scenario serializer/schema/hydrator and existing
  Mission Control/CTF launch gates, for regression evidence only; their
  contracts should not change.
- Closed transport: `shared.range_cells`, persisted-envelope validation, engine
  range loading, and GCE variable building, for unchanged digest/provenance
  evidence.
- Resolver/runtime: provisioner `config/_gce.py`,
  `gcp_range_cell_scenario.py`, plan/resources/outputs/cells, and focused tests.
- Config transport: `.github/workflows/_gcp-dev.yml`,
  `scripts/gcp/render_runtime_env.py` and tests,
  `shifter/installation/runtime_inventory.py` plus bundle/parity tests,
  `engine/ecs/_env.py`, task-runner sensitive-env tests, and local/bootstrap
  GCP renderer paths.
- Kubernetes: base and Helm provisioner validating-admission policies, their
  semantic policy/render tests, and Helm `runtimeEnv`/`platform-runtime`
  rendering.
- Operations/docs: `docs/dev/gcp-range-cell-deploy.md`,
  `docs/dev/polaris-gcp-range-cell.md`, and `docs/dev/deploy-secrets.md` when the
  behavior ships. Until then those runbooks correctly describe the live global
  workaround and must not claim the map is active.
- Architecture: this note, the #1342 Polaris preflight, the #1343 guest-image
  preflight, the #1344 scenario-to-cell contract, ADR-030, ADR-037, and ADR-039.

## Gotchas And Anti-Patterns

- Do not use `ami_key` as a GCE image/family reference or derive
  `shifter-<ami_key>`; only an exact platform mapping may resolve it.
- Do not fall back from an unknown non-empty key to a global role profile. That
  recreates the wrong-image bug and turns typos into unsafe successful launches.
- Do not map only `source_image` while retaining global disk sizing. Polaris
  needs a boot disk at least as large as its source image; the selected unit is
  the complete existing profile.
- Do not interpret the scenario's AWS `instance_type` as a GCE machine type.
  GCE machine type belongs in the keyed backend profile.
- Do not add one env var per image key. Every new scenario would require edits
  to workflow, renderer, inventory, launcher, and admission allowlists.
- Do not branch on `scenario_id`, special-case Polaris/TechVault in the planner,
  or infer host/bootstrap behavior from image-key literals.
- Do not reuse the ACES registry for legacy keys or add a second database image
  registry, repository, DTO, management API, or migration.
- Do not call AWS `get_ami_id`, GCP Secret Manager ConfigStore, or a provider API
  for runtime key lookup. The mapping is non-secret deployment config and must
  be fully validated before mutation.
- Do not accept malformed unused entries, duplicate JSON keys, unknown fields,
  unbounded maps, or newline-bearing renderer input.
- Do not log the full map or add it to argv, metadata, events, launch intents,
  state blobs, or error envelopes.
- Do not silently accept an existing same-name VM whose resolved image-profile
  binding differs from the current plan.
- Do not remove or repoint the current global Polaris workaround before the
  keyed map is deployed and both keyed and unkeyed launches have passed; rollout
  order is an operational compatibility concern.

## Non-Goals And Implementation Boundaries

- No issue implementation, implementation plan, or production ConfigMap change
  in this preflight.
- No new formal requirement, ADR, public scenario field, OpenAPI field, status,
  event, exception hierarchy, lifecycle controller, or persistence table.
- No redesign of CMS authoring, Mission Control/CTF authorization, range-cell
  network/security policy, guest credential handling, Guacamole, setup plans,
  Packer build/promotion, or GDC VM Runtime images.
- No change to AWS `ami_key` resolution and no attempt to make the AWS
  `instance_type` field provider-neutral.
- No change to ACES-native image source/version/resource realization or its
  tenant-managed image registry.
- No `shifter-techvault` GCE image bake or GCE TechVault bootstrap realizer.
  Until both exist and an approved keyed profile declares that supported
  capability, TechVault on GCE must fail loud before mutation.
- No automatic migration of already-provisioned ranges to a different image.
  Existing resources retain their created image; mapping changes affect new
  provision generations and must be observable during reconciliation.
