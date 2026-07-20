# Polaris GCP Range-Cell Preflight (#1342)

Status: pre-implementation guidance

Date: 2026-07-05

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1342>

Issue title: Port Polaris to the GCP range-cell backend

This note records architecture guardrails for moving the `polaris` scenario
from the current GDC VM Runtime path to the GCP Compute Engine range-cell
backend. It is not an implementation plan.

## Scope Boundary

The target shape is one isolated GCP range cell per participant, with one Linux
range-host VM running the Polaris Docker/Compose stack and one sibling Windows
Server domain-controller VM for `BOREAS.LOCAL`. The CTF participant flow remains
the entrypoint for launch, status, participant access, and destroy.

This work should specialize Polaris for the existing GCE range-cell substrate.
It must not introduce a parallel CTF provisioning lane, a new public scenario
schema, a new range lifecycle API, or a new cloud-secret abstraction. The GDC VM
Runtime path, the AWS Polaris AMI/SSM path, CTFd board sync, pause/resume
semantics, and the ACES replacement work are out of scope unless a specific
defect in one of those surfaces blocks this port.

No new ADR is required if the implementation stays inside the existing GCE
range-cell decisions from
[gcp-range-cell-backend-preflight-1341.md](./gcp-range-cell-backend-preflight-1341.md).
Add or revise an ADR only if the implementation changes a canonical lifecycle
boundary, public scenario contract, security gate, image source of truth, or
runtime secret-handling rule.

## Architecture Decisions

- The lifecycle stays `ctf` -> `cms` -> `engine` -> provisioner. CTF code may
  refresh and display range status through its current services, but it must not
  import engine/provisioner code or create a second range lifecycle controller.
- The scenario contract remains the existing CMS scenario template and
  `RangeSpec`/`RequestSpec` envelope. Provider-specific image and machine-size
  choices belong at the GCE range profile/image seam, not in a duplicate
  Polaris schema.
- Do not let the current Polaris AWS fields leak into GCE unchecked. In
  particular, `instance_type: m5.2xlarge` is an EC2 shape and `ami_key:
  polaris-*` is an AWS AMI lookup concept. A GCE backend must either ignore,
  translate, or replace those values through a validated provider-specific
  profile; it must not pass them straight to Compute Engine.
- The Polaris participant endpoint is a Kali container inside the Linux
  range-host VM, while the host image may be Ubuntu/Docker-based. Keep that
  semantic split explicit so participant labels, `os_type`, SSH usernames,
  host image selection, and Guacamole/SSH target resolution do not drift.
- The domain-controller IP and Polaris DNS behavior must be derived from the
  planned or persisted GCE range-cell state for the instance with role `dc`.
  Do not bake in `range-0`, `10.1.100.11`, subnet host-order assumptions, or
  the legacy smoke-test fallback as runtime behavior.
- Polaris GCE bootstrap must use the existing setup-plan/orchestrator and GCE
  guest-execution surfaces. The AWS-only `SSMExecutor`, EC2 IMDS hop-limit
  mutation, `boto3`, AWS CLI S3 fetches, and hardcoded AWS regions stay on the
  AWS path.
- The Windows DC boots from an approved Compute Engine image/profile surfaced
  through the GCE range image configuration, such as `GCP_RANGE_DC_IMAGE` and
  its profile settings. Do not reuse a GDC VM Runtime qcow2 URL, AWS SSM AMI
  parameter, or public Windows image reference that bypasses the repo's
  documented image approval path.
- Management exposure is the existing GCE range-cell firewall model: no public
  IPs, SSH/RDP only from approved portal/management CIDRs, and AD/DNS traffic
  only inside the range cell plus explicitly connected range networks. Windows
  guest firewall changes are not a substitute for VPC firewall policy.
- Secrets remain references at rest. Per-instance SSH and non-DC RDP secrets
  use GCP Secret Manager through the existing secret-store adapters; any DC
  domain credential continues through the sensitive-env path unless a
  provider-native secret reference is deliberately added at the same boundary.
  Secret values must not appear in DB rows, GCE metadata, startup scripts,
  process argv, Terraform output, Kubernetes ConfigMaps, events, or logs.
- Direct GCE guest setup must preserve host-key verification. The current GCE
  SSH executor is strict by design, so the implementation needs a trusted
  host-key/known-hosts source or equivalent safe handshake; disabling strict
  host-key checking is not an acceptable shortcut.
- Public status remains the existing range/resource status vocabulary. A range
  is not ready until DC promotion/DNS, Polaris host bootstrap, and access-path
  prerequisites have succeeded; failures should surface through existing
  sanitized status/error envelopes.
- Event-readiness requires evidence from the existing Polaris smoke harnesses
  and GCE isolation checks: participant Kali/RDP/SSH access through the
  management path, Polaris in-cell smoke tests, clean CMS/CTF destroy, and
  cross-range/platform escape tests.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1342 |
| --- | --- | --- |
| CTF participant lifecycle | `ctf.services.range.provision`, `lifecycle`, `status`, `tasks`, and `ctf.bridges` | Keep CTF as a bridge to CMS. Do not call engine or provisioner code directly from CTF. |
| CMS and engine lifecycle | `cms.services._range_create`, `_range_destroy`, `engine.services._range`, `_lifecycle`, and `engine.ecs` | Reuse the normal create/destroy/status path and request correlation. Do not add Polaris-specific lifecycle states. |
| Scenario shape | `cms.scenarios.schema`, `cms.scenarios.hydrator`, `shared.schemas.RangeSpec`, `shared.schemas.RequestSpec` | Extend or route through the existing validated envelope if a new field is unavoidable. Do not fork a Polaris-only DTO. |
| GCE range cells | `engine.provisioner.gcp_range_cells`, `gcp_range_cell_plan`, `gcp_range_cell_resources`, `gcp_guest_secrets`, and `config.load_gce_range_cell_config` | Use the provider/substrate/profile split already introduced for `GCP_RANGE_BACKEND=gce`. Do not overload GDC or AWS names. |
| Guest setup | `SetupOrchestrator`, setup plans, `executors.factory`, `GuestSSHExecutor`, `dc_setup`, and the existing Polaris bootstrap plan/scripts | Keep provider-specific command transport below the setup-plan boundary. Split AWS-only commands from provider-neutral Polaris configuration. |
| Provisioned state | `provisioner_db`, `state_helpers`, range instance outputs, and provider metadata | Persist enough GCE identifiers, secret refs, IPs, and provider metadata for access and idempotent destroy. Do not rely on display names alone. |
| Access brokering | `engine.services._terminal`, `engine.services._common`, `engine.secrets`, and Mission Control Guacamole builders | Feed the existing connection-info shape: private host, username, provider metadata, and secret reference. Do not add a CTF-specific Guacamole path. |
| Runtime env binding | `scripts/gcp/render_runtime_env.py`, `installation/runtime_inventory.py`, `engine.ecs` `_GCP_PROVISIONER_ENV_KEYS`, and `shared.cloud.sensitive_env` | Any new GCP or Polaris runtime knob must be rendered, inventoried, allowlisted, and classified as sensitive/non-sensitive in the existing surfaces. |
| Network policy | GCE range-cell firewall plan and the GCP VPC firewall guidance | Keep platform management CIDRs and range-internal CIDRs separate. Do not expose AD, RDP, or SSH publicly. |
| Smoke evidence | `scenario-dev/polaris/tests/run-all-smoketests.sh`, `scenario_smoketest`, and `isolation-smoketest.sh` | Reuse the existing operator-visible evidence path, updating provider assumptions only where needed. |

## Cross-Cutting Layers The Design Must Pass

- Auth and ownership: CTF participant/organizer checks, CMS user/range
  ownership, engine active-range checks, and Mission Control access checks must
  all remain in force. Provider-specific access details should only appear
  after those checks pass.
- Input and shape validation: scenario YAML must validate through the CMS
  scenario schema, hydrate into the shared request/range specs, persist through
  the current envelope, and reach the GCE provisioner through the existing
  engine request. GCE-specific shape changes need validation at the scenario or
  range-profile boundary, not ad hoc parsing inside bootstrap scripts.
- Config validation: `CLOUD_PROVIDER=gcp`, `GCP_RANGE_BACKEND=gce`, GCE image
  profiles, project/region/zone, service-account email, portal CIDRs, and any
  new Polaris runtime knob must flow through `load_gce_range_cell_config`, the
  GCP runtime env renderer, runtime inventory, and the engine task env
  allowlist.
- Secret handling: secret values flow through `shared.cloud` secret stores,
  `gcp_guest_secrets`, `engine.secrets`, and `shared.cloud.sensitive_env`.
  Logs use existing redaction helpers and safe fingerprints. Shell commands and
  process arguments must carry references or non-secret values only.
- OS and network exposure: GCE instances have no external IPs; firewall rules
  allow management ports only from approved portal/management CIDRs and AD/DNS
  only inside the range cell or explicitly connected networks. Guest firewall
  and service settings must be no broader than the VPC policy.
- Guest execution: GCE host configuration runs through direct SSH execution
  with trusted key material and host-key verification. AWS SSM, GDC pod SSH,
  and provider CLIs do not cross into the GCE guest path.
- Error envelopes and observability: user-visible failures continue through
  existing CMS/engine/CTF/Mission Control error classification. Logs should
  include request/range/instance correlation and sanitized provider metadata,
  not credentials, generated passwords, compose overrides, or command payloads.
- Event and status propagation: provisioning and destroy updates continue
  through the engine lifecycle, provisioner state writes, outbox/event
  reconciliation, and CTF status refresh. Do not add a second status source of
  truth for Polaris.

## Extensibility Seam

The durable seam is the GCE range-cell profile for a logical scenario role,
image profile, placement, DNS/domain settings, and bootstrap artifact source.
For Polaris, that means an explicit Linux range-host profile, an explicit DC
profile, a DC DNS/domain context, and a provider-specific way to retrieve smoke
or bootstrap artifacts. Future changes such as another GCP region, a larger
Polaris host size, a new approved DC image, or a different artifact bucket
should be a profile/config change, not an edit to CTF views, public status
models, or Mission Control access code.

## Whole-Repo Surfaces In Scope

- `docs/architecture/gcp-range-cell-backend-preflight-1341.md` and this note.
- `shifter/shifter_platform/cms/scenarios/templates/polaris.yaml`, the CMS
  scenario schema, and the scenario hydrator if provider-specific scenario
  routing is needed.
- `shifter/shifter_platform/engine/provisioner/config.py`, GCE range-cell
  plan/resources/cells code, GCP guest secrets, instance setup, DC setup,
  Polaris bootstrap plans/scripts, guest executors, provisioner state helpers,
  and range destroy.
- `scripts/gcp/render_runtime_env.py`,
  `shifter/installation/runtime_inventory.py`,
  `shifter/shifter_platform/engine/ecs.py`, GCP task-runner sensitive-env
  handling, and Kubernetes admission policy if runtime env or job shape changes.
- `engine.services`, `mission_control` Guacamole builders, and CTF range status
  services only if the existing state/access shape is insufficient.
- GCP image documentation or image-build workflows if an approved GCE DC image
  or Polaris Linux host image source is missing.
- Provisioner tests, GCP runtime-env tests, access-broker tests, and Polaris
  smoke/isolation validation.

## Gotchas And Anti-Patterns

- Do not run participant workloads as Kubernetes pods or call the GDC VM
  Runtime path a Compute Engine range cell.
- Do not hardcode DC IPs, `range-0`, AWS regions, AWS S3 buckets, GDC qcow2
  image URLs, or EC2 instance types in the GCE path.
- Do not pass AWS `ami_key` or `instance_type` values directly into GCE
  instance creation.
- Do not make `os_type: kali` silently mean an Ubuntu host image unless the
  profile and username/access behavior make that split explicit.
- Do not disable SSH host-key verification to make GCE guest setup pass.
- Do not create duplicate validation layers, exception hierarchies, secret
  adapters, Guacamole endpoints, lifecycle controllers, or Polaris-only status
  enums.
- Do not open AD, RDP, SSH, Docker, or management ports to the internet or to
  broad platform networks.
- Do not mark the range ready before the DC, DNS, Polaris stack, and management
  access path are actually usable.
- Do not persist generated credentials, compose override bodies, startup
  scripts with secrets, or smoke-test flag material in durable logs/events.

## Non-Goals

- No implementation work in this preflight note.
- No Ground Control requirement is attached; issue #1342 is the authoritative
  contract.
- No redesign of GCP range cells, GDC VM Runtime, AWS Polaris, CTFd sync,
  Guacamole, or the public scenario DSL.
- No new pause/resume support for GCE ranges unless separately scoped.
- No new image-build workflow unless the approved GCE Polaris host/DC image path
  is absent and that absence blocks the port.
