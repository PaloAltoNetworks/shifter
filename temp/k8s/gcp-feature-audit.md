# Shifter Feature Audit for GCP Port

Date:
- 2026-04-10

Purpose:
- Build a comprehensive inventory of Shifter features and capabilities from the code and docs.
- Audit the current GCP/GDC implementation against that inventory.
- Produce a gap analysis focused on feature parity, not just infrastructure bring-up.

Audit constraints:
- Notes are written incrementally during the audit.
- This file is a working log, not just a final summary.
- NGFW support is out of immediate delivery scope, but feature parity requirements are still recorded when they affect architecture.

Initial scope buckets:
- Cyberscript and experiment execution
- CMS scenario model and scenario editor
- Portal GUI and operator flows
- Terminal UI and SSH access
- RDP and Guacamole integration
- Scenario/runtime provisioning model
- Range lifecycle and status
- CTF/event-specific platform behavior
- GCP/GDC control-plane and range-plane implementation

Working assumptions at audit start:
- The user requires AWS feature parity on GCP for Shifter platform features, not a reduced subset.
- The only explicitly deferred capability is NGFW support for the immediate delivery target.

Audit rule clarified during review:
- Feature parity is mandatory across Shifter platform capabilities when comparing AWS and GCP implementations.
- Infrastructure details may differ between clouds.
- Deliberate scope reduction is not acceptable unless the user has explicitly exempted the feature.
- Current temporary exemption: NGFW support only.

Checkpoint 1:
- Top-level documented feature buckets are present in the docs tree:
  - Agents
  - Ranges
  - Terminal
  - Credentials
  - CTF/event flows
  - Scenario catalog
  - Technical platform domains: Mission Control, Engine, CMS, infrastructure, Guacamole, GDC provisioning
- The audit should therefore compare GCP against the full operator-facing and authoring-facing platform, not just guest provisioning.

Checkpoint 2: documented product surface
- User-facing docs explicitly present Shifter as supporting:
  - Agent upload and management
  - Range launch, status, cancel, destroy
  - Browser terminal access
  - RDP access through Guacamole
  - Scenario catalog with Basic Range, AD Attack Lab, Cortex BYOT, and NGFW scenarios
  - CTF/event workflows and scoring
- Terminal docs promise SSH terminal access plus RDP across common instance types, including Kali, Windows workstations, Windows Server/DC, and Ubuntu.
- Scenario docs promise:
  - Basic Range: Kali + victim workstation with agent
  - AD Attack Lab: Kali + Windows DC + joined workstation
  - Cortex BYOT: Kali + DC + 2 workstations + server + agents + segmented subnets
- Test coverage indicates the platform surface is not limited to launch/destroy:
  - engine service tests cover create, cancel, destroy, pause, resume, SSH connection lookup, RDP lookup, terminal, and NGFW terminal
  - CMS tests cover assets, credentials, scenarios, uploads, exports, services, and experiments
  - CTF tests cover events, challenges, participant views, organizer access, scoring, programmable flags, notifications, scheduler handlers, and range services

Interim implication:
- The parity target for GCP must include:
  - operator-facing platform flows
  - scenario/runtime semantics
  - access semantics
  - CTF/event services
  - authoring/editing surfaces
- A GCP path that only provisions guests but omits those surfaces is not feature parity.

Checkpoint 3: authoring/modeling surfaces
- CyberScript is a real DSL and runtime contract, not just documentation:
  - YAML template -> `ScenarioTemplate` validation -> hydration -> `RangeSpec` -> Engine -> Provisioner
  - template variables resolve against provisioned instance properties at runtime
- The scenario editor is a real staff-facing feature surface:
  - list/detail/create/edit/clone/delete/export/validate workflows exist
  - custom scenarios are stored in DB and merged with built-in YAML scenarios
  - validation is enforced through the same `ScenarioTemplate` schema
- The built-in CyberScript examples and docs define full-featured scenarios with:
  - domain controllers
  - joined victims
  - XDR agent embedding
  - segmented subnet topologies
  - mixed Windows and Linux guests
- That means parity on GCP must preserve the semantic meaning of the existing scenario DSL, not just accept the same YAML fields while degrading behavior underneath.

Modeling-specific observation:
- The current schema has already been modified to add `asset_type` with `vm_runtime_vm` vs `scenario_pod`.
- That extension is acceptable only if it preserves the existing scenario semantics by default and only introduces optional new expression power.
- Any validation that turns previously valid scenario patterns into GCP-incompatible subsets is a parity regression unless it is isolated to an explicitly optional asset mode.

Checkpoint 4: runtime and operator-flow contracts
- Engine service layer defines platform-visible lifecycle contracts for:
  - create range
  - get range status
  - cancel range
  - destroy range
  - pause/resume range
  - SSH terminal lookup
  - RDP connection lookup
  - NGFW terminal lookup
- Mission Control defines the user-facing GUI around those contracts:
  - dashboard / ranges
  - agents
  - terminal page
  - Guacamole RDP signed URL generation
  - NGFW SSH URL generation
- Guacamole integration is not cosmetic; it is a first-class access path with:
  - signed JSON-auth payloads
  - RDP parameters
  - SFTP upload/download support
  - OS-specific home/download directories
- CTF services are coupled to range lifecycle:
  - participant range provisioning
  - status polling
  - event-wide bulk provision/cleanup
  - scheduler-triggered start/end/reminder behavior

Interim implication:
- GCP parity must be judged at the level of these operator-visible contracts.
- “GCP can provision a guest somehow” is insufficient if:
  - Mission Control cannot expose the same access/session UX
  - CTF services cannot provision and clean up ranges through the same abstractions
  - pause/resume semantics diverge materially

Checkpoint 5: editor, GUI, and experiment surfaces
- The scenario editor is schema-driven and cloud-agnostic at the service layer:
  - create/update/clone/delete/validate all run through `ScenarioTemplate` validation
  - any capability removed from schema or hydration is automatically removed from the editor
- Mission Control GUI is also cloud-agnostic at the view layer:
  - ranges dashboard
  - agent upload/management
  - browser terminal page
  - Guacamole-backed RDP and NGFW URL endpoints
- Guacamole URL generation itself is provider-neutral; the cloud/provider-specific part is the engine connection-info lookup underneath.
- Experiment orchestration is mixed:
  - task launching is already provider-neutral through the cloud task-runner abstraction
  - but experiment command construction still contains AWS-specific behavior for Python scripts (`aws s3 cp s3://...`)
- Implication:
  - editor/GUI parity mostly depends on preserving engine/runtime contracts
  - experiments need explicit GCP parity review because provider-neutral task dispatch alone is not enough if script retrieval or execution paths remain AWS-specific

Checkpoint 6: portable storage/event abstractions vs AWS-era experiment assumptions
- Agent upload/storage is mostly portable:
  - CMS still uses AWS-oriented names like `AWS_S3_BUCKET_NAME`, `s3_key`, and `cms.assets.s3`
  - but the implementation delegates to `shared.cloud.get_object_storage()`, which already has a GCP/GCS adapter
- Queue/task abstractions are also present for GCP:
  - portal-side task runner uses Kubernetes Jobs on GCP
  - queue/event abstractions map to Pub/Sub on GCP
- Experiments are the main remaining mismatch in this bucket:
  - upload/download helpers can work through the shared object-storage abstraction
  - but experiment orchestration and surrounding docs/comments still assume AWS primitives such as S3 object fetches and SSM-style execution
  - concrete hardcoded portability break already confirmed: Python experiment scripts are fetched with `aws s3 cp s3://${BUCKET_NAME}/...`
- Implication:
  - storage naming cleanup is not urgent for parity if the adapters work
  - experiment execution semantics are a real feature-parity risk and must be audited as functionality, not just naming

Checkpoint 7: what the active GCP range plane actually preserves
- Existing Shifter scenario semantics still default to VM-backed guests on GCP:
  - `asset_type` defaults to `vm_runtime_vm`
  - the built-in scenario templates do not currently opt into `scenario_pod`
- The active GCP range plane is not a reduced “pods only” path:
  - `range_terraform_runner.py` routes GCP to `gdc_range_networks.py` + `gdc_vmruntime_assets.py` + `gdc_scenario_pods.py`
  - mixed pod/VM subnets on the same L2 network are explicitly supported
- VM Runtime guests preserve the important Shifter guest contract:
  - Kali / Ubuntu / Windows / DC templates exist
  - outputs include IP, SSH secret ref, SSH username, and provider metadata
  - guest setup on GCP uses the same high-level plans as AWS (bootstrap, XDR, domain join, DC setup), but executes over SSH instead of SSM
- Confirmed by code/tests:
  - GCP VM Runtime outputs are shaped for Mission Control terminal and RDP lookups
  - DC setup has a GCP-specific runtime promotion path
  - Linux/Windows/DC credentials are resolved for Guacamole on GCP

Important clarification:
- The current GCP work does NOT globally forbid DCs, Kali terminal access, XDR, or domain join.
- Those features remain available for the default VM Runtime path.
- The explicit restrictions apply only to the optional `scenario_pod` asset type.

Checkpoint 8: real GCP parity gaps
- Range pause/resume is not implemented for GCP:
  - portal/CMS/engine entry points exist
  - GCP task launching exists
  - but provisioner `range_ops.py` still hard-fails for any non-AWS provider
- `scenario_pod` is intentionally abridged relative to normal Shifter guest behavior:
  - schema rejects Windows, DC, NGFW, domain join, XDR, and AMI/image override semantics
  - provisioner starts inert `sleep` containers instead of scenario-specific services
  - pod-backed assets are skipped entirely by the guest setup pipeline
  - engine access APIs reject SSH/RDP for pod-backed assets
  - Mission Control terminal UI still renders generic SSH/RDP affordances, so pod-backed assets can surface as UX failures rather than being hidden or represented differently
- Experiments are not fully parity-safe yet:
  - task and queue abstractions are portable
  - but the orchestration path still embeds AWS-specific script-fetch behavior (`aws s3 cp ...`)
- GCP docs/README state is materially stale:
  - GCP infra docs still describe VM/runtime integration as a non-goal even though the codebase now contains a substantial GDC VM Runtime implementation
  - this creates false expectations during verification and rollout

Checkpoint 9: contract-boundary rollback
- Backend-selection concerns leaked into the wrong layers during the mixed pod/VM work:
  - `cms.scenarios.schema.InstanceConfig` gained `asset_type`
  - `cyberscript.schemas.range.InstanceSpec` and `InstanceContext` gained `asset_type`
  - `cms.services` started projecting `asset_type` into Mission Control-facing `RangeContext`
  - `engine.services` started denying SSH/RDP based on `asset_type`
- This violates the intended boundary:
  - existing SDL should remain the contract
  - shared schemas should stay cloud/runtime neutral
  - CMS and Mission Control should not need backend-awareness for pod vs VM selection
- Rollback action underway:
  - remove `asset_type` and pod-specific validation from CMS/shared schemas
  - remove `asset_type` from CMS `RangeContext` projection
  - remove pod-specific SSH/RDP rejection from engine service lookups
  - leave internal provisioner/runtime branching in place temporarily until backend resolution is reintroduced as a purely internal provisioner concern

Checkpoint 9: non-GCP-specific drift discovered during audit
- `ai_agent` appears in built-in scenario templates and CMS docs, but is not modeled in the active scenario schema or hydration path.
- This appears to be product/doc drift rather than a GCP-specific regression.
- The sibling NORTHSTORM/MechaG docs describe additional scenario-pack requirements:

Checkpoint 10: GCP identity/bootstrap cutover
- The earlier GCP path wrongly depended on a manually populated OIDC runtime secret. That was not equivalent to the AWS bootstrap experience.
- The GCP control-plane path now provisions Identity Platform directly in Terraform and exposes the project API key/project ID to runtime.
- Django auth is now provider-seamed:
  - AWS keeps Cognito/OIDC through `mozilla-django-oidc`
  - GCP uses first-party Identity Platform login inside Shifter
- The first GCP operator is now bootstrap-seeded through the Identity Platform admin API using env-backed credentials or an interactive prompt.
- Operator-only corporate login requirements are enforced in-app:
  - `@paloaltonetworks.com` allowlist
  - verified email
  - TOTP MFA enrollment/sign-in
- Bootstrap operator privilege elevation is runtime-configured through `PLATFORM_BOOTSTRAP_STAFF_EMAILS` and `PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS`, so identities do not need to be committed to the repo.
- AWS regression check:
  - `/login/` still routes to the OIDC init path when `AUTH_PROVIDER=oidc`
  - dev auth routes remain blocked in production after exempting them from OIDC session refresh interception
  - per-asset service-specific images or behaviors
  - containerized Kali with AI tooling preinstalled
  - Samba DC as the first choice for scale
- Those scenario-pack requirements are not the same as AWS parity requirements. They are additional future scenario modeling/runtime work unless equivalent behavior already exists elsewhere outside the current schema/runtime path.

Current parity readout
- Mostly preserved on GCP today:
  - Scenario editor as a product surface
  - Mission Control GUI structure
  - Browser terminal UI shell
  - Guacamole SSH/RDP integration for VM-backed guests
  - Core scenario semantics for the default built-in Shifter scenarios (Kali, Windows, Ubuntu, DC, XDR, domain join)
  - CTF/event orchestration service layer
  - Cloud storage, queue, secret, and task-runner abstractions
- Not yet parity-complete on GCP:
  - Pause/resume lifecycle
  - Experiments execution portability
  - Any use of `scenario_pod` as a drop-in substitute for normal Shifter instances
  - Documentation fidelity for the actual GCP implementation

Audit conclusion at this stage
- The GCP port is significantly closer to full Shifter parity than an earlier “pods only” read would suggest, because the default path for normal scenarios is VM Runtime and keeps the established guest setup flow.
- The remaining work is now concentrated and concrete:
  - finish provider-complete lifecycle support
  - either raise `scenario_pod` toward feature parity or keep it clearly optional and never let it silently replace normal Shifter semantics
  - remove AWS-only assumptions from experiments
  - update docs so verification targets the actual architecture

Checkpoint 10: GCP range lifecycle parity implemented
- `engine/provisioner/range_ops.py` no longer hard-fails GCP range pause/resume.
- Range lifecycle targets are now classified from engine-owned runtime state:
  - AWS VM-backed assets use the existing EC2 pause/resume flow
  - GCP VM Runtime guests use a new VM Runtime power-operation path
  - GCP pod-backed assets use a real lifecycle path instead of a no-op
- `engine/provisioner/gdc_vmruntime_assets.py` now exposes a VM Runtime power helper that:
  - resolves the VM namespace/name from provisioner state
  - invokes `kubectl virt start|stop`
  - waits for running/stopped state before returning
- `engine/provisioner/gdc_scenario_pods.py` now exposes a scenario Pod power helper that:
  - resolves namespace, pod name, image, network, and static IP from engine-owned runtime state
  - stops pods by deleting them and waiting for deletion
  - resumes pods by recreating the deterministic Pod manifest and waiting for the expected IP/ready state
- Verified with provisioner tests:
  - new GCP lifecycle classification and mixed-range tests pass
  - existing NGFW retry tests still pass
- This closes the GCP pause/resume blocker for VM Runtime-backed ranges without changing CMS, Mission Control, or the shared SDL contract.

Checkpoint 11: production-quality re-audit of lifecycle parity
- Reopened `P1` after a deeper audit. The current implementation is not yet production-quality lifecycle parity.
- Blocker: the provisioner image does not currently install `kubectl` or the `kubectl virt` plugin, but the GDC VM Runtime pause/resume path requires both.
  - Result: deployed GCP VM pause/resume would fail even though unit tests pass.
- Blocker: scenario Pod pause/resume currently deletes and recreates bare Pods with no persistent writable storage.
  - Result: mutable guest state is lost across pause/resume, which is not equivalent to AWS stop/start semantics.
- Drift: scenario Pod resume reconstructs a reduced manifest from runtime state instead of recreating the original object exactly.
  - Current recreation drops original `range-id` / `request-id` labels and uses the current config's image pull policy rather than persisted provisioned state.
- Conclusion: GCP lifecycle wiring exists, but lifecycle parity is not complete at a production standard until the above issues are fixed.

Checkpoint 12: GCP lifecycle fail-closed
- For the current CTF phase, GCP `pause` and `resume` are now intentionally disabled in `engine/provisioner/range_ops.py`.
- Only the GCP lifecycle modes fail closed; the AWS pause/resume path is unchanged.
- Destroy is still supported on GCP because destroy goes through the dedicated asset teardown path and does not depend on pause/stop first.
- This prevents Mission Control and CTF flows from getting a false success signal for GCP pause/resume before parity-safe persistence semantics exist.

Checkpoint 13: GDC bootstrap rerun safety hardened
- `scripts/bootstrap/deploy.py` now checks current state before mutating the live GDC bootstrap substrate:
  - bootstrap staging reuses `/root/.ssh/id_rsa`, `/root/.ssh/id_rsa.pub`, and `/root/bm-gcr.json` from the workstation when they exist and the service-account key is still active in IAM
  - instance `ssh-keys` metadata writes are skipped when the current metadata already matches the expected bootstrap key
  - `shifter-gcp-dev-gdc-access` and `shifter-gcp-dev-gdc-vm-image-gcs` skip adding a new Secret Manager version when the desired payload already matches the latest version
  - remote bundle upload now clears `/root/shifter-gdc-bootstrap/<cluster>` before copying, so a failed prior stage cannot leave partial bundle contents behind
- Automated proof:
  - full `scripts/bootstrap/tests/test_deploy.py` passes
  - the new rerun-safety tests prove the code only mutates metadata or secret versions when drift exists
  - `ruff` and ADR guard pass on `scripts/bootstrap/deploy.py`
- Live read-only proof against `prod-rwctxzl6shxk`:
  - existing workstation bootstrap material was reused successfully
  - workstation key id and newly staged key id both resolved to `d6edc4b1cc096f95b105b810d838e786b040a3e9`
  - all six GDC hosts already matched the expected `ssh-keys` metadata
  - the latest `shifter-gcp-dev-gdc-vm-image-gcs` payload already matched the workstation key payload
  - the latest `shifter-gcp-dev-gdc-access` payload exists and is readable
- Current conclusion:
  - the GDC bootstrap substrate path is now retry-safe enough to rerun after a failed stage without blindly minting a new key, rewriting already-correct metadata, or churning identical secret versions
  - this is a prerequisite for the next live proof run of the full GCP bootstrap path

Checkpoint 14: Helm values layering and GKE ingress health ownership
- The GCP cutover now uses Helm values layering in the expected multi-environment shape:
  - `platform/charts/shifter/values.yaml` contains the chart defaults
  - `platform/charts/shifter/values-gcp-dev.yaml` contains the environment override for `gcp-dev`
  - `platform/charts/shifter/values-gcp-prod.yaml` contains the environment override for `gcp-prod`
  - bootstrap renders a generated runtime values file and applies it as the final override layer
- The portal ingress health path is now owned explicitly by the chart instead of relying on the GKE default `/` probe:
  - `platform/charts/shifter/templates/portal-backendconfig.yaml` defines a `BackendConfig`
  - `platform/charts/shifter/templates/web-service.yaml` attaches it to the `portal-web` Service with `cloud.google.com/backend-config`
  - the configured request path is `/health/`, which matches the existing portal readiness/liveness path
- Automated proof:
  - Helm render test proves the chart emits the `BackendConfig` resource and Service annotation
  - targeted bootstrap tests and `ruff` passed after the chart change
  - ADR guard passed on the changed files

Checkpoint 15: full bootstrap now leaves a usable Shifter platform
- Live proof run:
  - `PATH="$HOME/.local/bin:$PATH" ./scripts/bootstrap/deploy.py gdc-bootstrap --project-id prod-rwctxzl6shxk --cluster-id cluster1`
  - bootstrap completed successfully after reconciling the GDC substrate, Terraform, image pushes, and Helm release
- Live platform proof after bootstrap:
  - Helm release `shifter` upgraded successfully in `shifter-system`
  - portal, workers, Guacamole, and scheduler workloads were already present and remained healthy through the reconcile
  - the GKE/GCE `BackendConfig` was materialized in-cluster
  - the Google health check for the portal backend now uses `/health/`
  - backend health converged to `HEALTHY` for the active zones on `k8s1-433d7137-shifter-platform-portal-web-8000-bcbc998a`
  - external portal ingress at `http://34.54.58.95/` now returns `HTTP/1.1 200 OK`
  - external Mission Control entrypoint at `http://34.54.58.95/mission-control/` now returns the expected `302` redirect to `/dev-login/?next=/mission-control/`
- Important implementation note:
  - the initial 502 after the chart rollout was convergence delay while the GCE backend health check switched from `/` to `/health/`
  - once the new health check propagated, the platform became externally reachable without any manual out-of-band deployment step

Checkpoint 16: full teardown back to `ctf-test-lab` only
- User-directed teardown scope:
  - destroy the entire `gcp-dev` install and GDC substrate
  - preserve `ctf-test-lab`
  - do not start a fresh bootstrap after cleanup
- Live teardown execution:
  - Terraform destroy was run against the `gcp-dev` environment and removed the GKE control plane, Pub/Sub, Redis, Artifact Registry, runtime secrets, and the rest of the Terraform-managed stack
  - Terraform did not finish cleanly because Cloud SQL user deletion ordering was wrong for `guacamole_admin`; the SQL instance and remaining control-plane residue were then removed manually
  - the non-Terraform GDC substrate was removed manually: hub membership, six `cluster1-abm-*` hosts, `cluster1-*` firewall rules, `cluster1-gdc-us-central1`, `cluster1-gdc`, the two GDC bootstrap secrets, the `baremetal-gcr` service account, the `shifter-gcp-dev-tf-bootstrap` service account, and the Terraform state bucket
  - stale project-level IAM bindings from earlier GDC/VM Runtime spike work were removed so the project no longer retained dead workload identity principals
- Verified post-cleanup state:
  - `gcloud compute networks list --project prod-rwctxzl6shxk` shows only `ctf-test-lab`
  - `gcloud compute instances list --project prod-rwctxzl6shxk` shows only `ctf-test-a2-dc`, `ctf-test-a2-windc`, and `ctf-test-attacker`
  - `gcloud compute firewall-rules list --project prod-rwctxzl6shxk` shows only the four `ctf-test-*` rules
  - `gcloud sql instances list --project prod-rwctxzl6shxk` is empty
  - `gcloud secrets list --project prod-rwctxzl6shxk` is empty
  - `gcloud iam service-accounts list --project prod-rwctxzl6shxk` shows only the Compute Engine default service account
  - `gcloud container hub memberships list --project prod-rwctxzl6shxk` is empty
  - `gcloud storage buckets list --project prod-rwctxzl6shxk` is empty

Checkpoint 17: pre-bootstrap hardening for the next fresh GCP rebuild
- User-directed goal:
  - tighten the next GCP bootstrap so it does not recreate the prior insecure posture
  - keep the change set pragmatic: secure enough not to leave the range exposed, without turning this into a full enterprise hardening program
- Implemented hardening changes:
  - GDC admin/workstation path:
    - `scripts/bootstrap/deploy.py` now enables `iap.googleapis.com`
    - GDC SSH firewall source range changed from `0.0.0.0/0` to `35.235.240.0/20` (IAP TCP forwarding)
    - GDC LB/admin firewall source range changed from `0.0.0.0/0` to the private GDC subnet CIDR
    - GDC hosts are now created with `--no-address`, so they no longer receive public IPs
    - bootstrap SSH/SCP and kubeconfig fetches now use `--tunnel-through-iap`
  - Control-plane bootstrap posture:
    - `scripts/gcp/render_runtime_env.py` now refuses `secure_portal_mode=True` unless both `public_hostname` and `managed_tls_enabled` are set
    - `scripts/bootstrap/deploy.py` now renders GCP runtime env with `secure_portal_mode=True`, eliminating the old silent public-debug fallback for GCP bootstrap
    - `scripts/bootstrap/deploy.py` now fails before Terraform apply if `platform/terraform/gcp/environments/gcp-dev/terraform.tfvars` does not define:
      - `public_hostname`
      - `enable_managed_tls = true`
      - at least one `gke_master_authorized_cidrs` entry
  - GKE control-plane restriction:
    - `platform/terraform/gcp/modules/platform-core` now supports `gke_master_authorized_cidrs`
    - `platform/terraform/gcp/environments/gcp-dev` now passes that variable through
    - this keeps the current public GKE endpoint path bootstrap-compatible while preventing an open-to-the-world control-plane
  - Edge protection:
    - `platform/terraform/gcp/modules/platform-core` now provisions a baseline Cloud Armor security policy for the public ingress
    - the policy currently blocks stable preconfigured WAF SQLi and XSS signatures, with default allow after those denies
    - the chart now wires that policy into both public GKE backends via `BackendConfig`:
      - portal service
      - guacamole-client service
- Automated proof:
  - `uv run --with pytest python -m pytest -q scripts/gcp/tests/test_render_runtime_env.py scripts/bootstrap/tests/test_deploy.py`
  - `uv run --with ruff ruff check scripts/bootstrap/deploy.py scripts/bootstrap/tests/test_deploy.py scripts/gcp/render_runtime_env.py scripts/gcp/tests/test_render_runtime_env.py`
  - `terraform fmt -check -recursive platform/terraform/gcp`
  - `tflint --chdir platform/terraform/gcp/modules/platform-core --config /home/atomik/src/shifter-k8s/.tflint.hcl`
  - `tflint --chdir platform/terraform/gcp/environments/gcp-dev --config /home/atomik/src/shifter-k8s/.tflint.hcl`
  - `helm lint platform/charts/shifter -f platform/charts/shifter/values-gcp-dev.yaml`
  - `python3 scripts/adr_guard/adr_guard.py --all --level ci`
- Current operator prerequisites before the next fresh bootstrap:
  - set a real `public_hostname` in `platform/terraform/gcp/environments/gcp-dev/terraform.tfvars`
  - set `enable_managed_tls = true`
  - set one or more real `gke_master_authorized_cidrs` values for the admin network(s) that should be allowed to reach the public GKE API endpoint during bootstrap
- Explicit non-goals in this checkpoint:
  - the cluster has not been rebuilt yet under the new posture
  - private-only GKE control-plane endpoint is not enabled yet because the current bootstrap still performs `get-credentials` and Helm from the operator machine
  - Cloudflare / additional edge controls are still future work

### Checkpoint 18: GCP Docs and ADR Reconciliation

- Reconciled the technical GCP docs so they match the current branch reality:
  - GCP control-plane deployment is Helm-packaged and bootstrap-managed
  - `./scripts/bootstrap/deploy.py gdc-bootstrap` is the authoritative branch-local bring-up path
  - `_gcp-dev.yml` remains validation/staged workflow logic and is not the authoritative deploy contract yet
  - the secure GCP posture is documented consistently across infrastructure, networking, manual deployment, CI/CD, and developer setup docs
- Added new ADR entries in `docs/adr/index.yaml`:
  - `ADR-007` captures the permanent cutover to Helm-packaged, bootstrap-managed GCP control-plane deployment
  - `ADR-008` captures the fail-closed GCP bootstrap posture: managed TLS, real hostname, authorized admin CIDRs, Cloud Armor on public backends, and IAP-only operator access to private GDC hosts
- Validation:
  - `python3 scripts/adr_guard/adr_guard.py --all --level ci`
