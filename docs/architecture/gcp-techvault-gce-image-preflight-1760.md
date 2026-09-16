# TechVault Native GCE Image Preflight (#1760)

> **Historical boundary (issue #2062, 2026-08-19):** TechVault is a
> scenario pack. APTL is the former name of LilRAE. The bespoke Shifter
> implementation described here was retired by the RAES hard cut. Exact
> historical commands, paths, symbols, image keys, and workflow names below
> remain factual evidence; they are not current product or integration
> boundaries.

Status: pre-implementation guidance

Date: 2026-07-20

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1760>

Issue #1760 is the shipping contract. This is a requirement-free run. This note
does not implement a Packer source, publish an image, change runtime image
selection, or provision a range.

## Decision Boundary

TechVault needs one native Compute Engine image target in the existing GCP
Packer release path. The release identity is an immutable candidate in family
`shifter-techvault`; it is not an AWS AMI, an SSM parameter, an exported GDC
qcow2, a new scenario schema, or a new runtime image registry.

The target is the GCE equivalent of the existing AWS TechVault golden image:
an Ubuntu 24.04 Docker host with the pinned APTL `techvault-operational` stack,
the `ubuntu` UID-1000 participant seat, XFCE/xrdp, VS Code, and Claude Code. The
stack is captured running and must auto-start on a clean boot. Preserve that
guest contract through the shared `shifter/packer/scripts/techvault/` scripts;
do not fork a GCP copy of the TechVault install or health model.

Use the existing GCE build -> exact-candidate validation -> evidence-bound
promotion path. Do not add a TechVault workflow, publisher, image DTO, database
record, exception hierarchy, or lifecycle controller.

Issue #1760 does not own the companion per-instance `ami_key` resolution work.
The current legacy GCE adapter selects one global Kali/attacker image through
`GCP_RANGE_KALI_IMAGE`, so a deployment cannot concurrently serve plain Kali,
Polaris, and TechVault. A live #1760 smoke may either run after the companion
resolver lands or use an explicitly isolated validation deployment whose Kali
profile is temporarily bound to `shifter-techvault`. That temporary binding is
test configuration, not the permanent product design. Do not close the runtime
gap by hard-coding TechVault as the global Kali image.

No new ADR is needed while the change stays within ADR-004-R23's credentialed
workflow trust boundary, ADR-030's native GCE live-fire boundary, ADR-037's
VM-image provenance rules, and the candidate/family contract in
`gce-range-guest-image-pipeline-preflight-1343.md`. Revise an ADR only if the
implementation changes one of those durable decisions, the image source of
truth, or the runtime credential boundary.

## Architecture Decisions And Guardrails

- `shifter/packer/gcp/` remains the only native-GCE Packer configuration and
  `.github/workflows/packer-gcp.yml` remains the only build entrypoint. The
  source, manifest, label, workflow type, validation type, and family all use
  the same logical key, `techvault`.
- Use a GCE-native Canonical Ubuntu 24.04 source with the Google guest
  environment intact. Do not import the AWS AMI or a generic cloud disk. The
  image must retain metadata networking/SSH support and regenerate any host
  keys removed before capture.
- The `ubuntu` seat is a runtime contract, not a cosmetic username. Its UID must
  be 1000 because the APTL Wazuh material is mode 0400 and consumed by UID-1000
  containers. The bake must establish and verify the account, home ownership,
  Docker-group access, xrdp session, and participant SSH/RDP behavior rather
  than assuming the GCE base image supplies them.
- Preserve running-stack capture semantics. Do not stop the Compose stack in a
  generic cleanup step or rerun `aptl lab start` at range launch. Pre-capture
  hygiene may clear package caches, logs, histories, transient Packer access,
  and SSH host keys only when first-boot regeneration is proven.
- The pinned APTL version is the obvious version seam. It must flow through one
  typed Packer variable and a validated `PKR_VAR_*` environment binding, matching
  the AWS TechVault contract. It must not be interpolated into workflow shell
  source or placed on Packer command argv.
- Reusing the TechVault scripts does not waive ADR-037. The current `curl | sh`
  Docker and NodeSource installers, floating Claude Code npm install, and
  unhashed `pipx install` are supply-chain liabilities when executed as root on
  a cloud-credentialed builder. The GCE target must use reviewed versions and
  official signatures/checksums or hash-enforced locks. Harden the shared
  provider-neutral install path where possible; do not copy the unsafe commands
  into a GCP-only script and create two drifting installers.
- Size build and runtime independently. The build VM needs enough CPU, memory,
  disk, and timeout for the full stack; the published boot disk must cover the
  existing 100-GiB-class TechVault payload. A GCE runtime profile must not use
  the Kali default 80-GiB disk when the source image is larger, and it must not
  pass the scenario's AWS-only `r5.2xlarge` value to Compute Engine.
- Candidate validation needs a TechVault profile in the existing runner-side
  Linux validator. Generic `google-guest-agent active` evidence is insufficient.
  On first boot and after reset, prove Docker/Compose, the APTL config and local
  images, 30 long-running `aptl-*` containers, the expected successful one-shot
  initializer, required services, the `ubuntu` seat, Claude CLI, xrdp, SSH, and
  absence of unexpected failed/unhealthy containers. Reuse the established
  required-service contract (`aptl-wazuh-manager`, `aptl-victim`, `aptl-kali`)
  rather than inventing a second TechVault health definition.
- Validation remains runner-gathered against the exact candidate. The guest has
  no service account, OAuth scopes, or external IP; it cannot label itself.
  Promotion must use evidence bound to the exact candidate, trusted workflow
  run, and revision as required by ADR-004-R23. A mutable
  `validated=passed` label alone is not authoritative promotion evidence.
- Promotion already derives the destination family from the candidate. Keep it
  generic; do not add a TechVault branch or a second promotion workflow. Verify
  the new image before deprecating the previous family head.
- The GDC export step is not part of #1760. Adding a Linux image choice to the
  current broad export condition would also publish `techvault.qcow2` and imply
  a nonexistent `GDC_TECHVAULT_IMAGE_URL` contract. Explicitly keep TechVault
  out of GDC export/wiring unless a separate issue designs and validates that
  consumer.
- The AWS Packer source and `/shifter/ami/techvault` remain unchanged. Shared
  guest scripts may improve in a provider-neutral way, but GCE project/family,
  WIF/IAP, and candidate-promotion mechanics must not leak into the AWS path.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| TechVault guest contract | `shifter/packer/techvault.pkr.hcl`, `shifter/packer/scripts/techvault/*`, `docs/ops/techvault-bake-runbook.md`, and the AWS scenario-bake tests | Reuse the Ubuntu UID-1000 seat, pinned APTL lab, running-stack capture, 30-container convergence, required services, and xrdp/Claude behavior. Keep cloud mechanics provider-specific. |
| Native GCE source | `shifter/packer/gcp/*.pkr.hcl`, `variables.pkr.hcl`, `packer.pkr.hcl`, and `shifter/packer/gcp/README.md` | Add one `googlecompute.techvault` source with the established project/zone/network/SA/IAP, family, labels, and manifest conventions. Do not put `googlecompute` in the parent AWS configuration. |
| Build workflow | `.github/workflows/packer-gcp.yml` | Preserve closed image/environment choices, protected-ref WIF, SHA-pinned actions, job-local permissions, environment-owned project selection, `PKR_VAR_*`, `packer validate/build`, bounded summaries, and manifest upload. Do not accept a caller-supplied project, service account, network, or executable ref. |
| Validation and promotion | `.github/workflows/packer-gcp-validate.yml`, `packer-gcp-promote.yml`, and `gcp/scripts/validate/*` | Extend the existing exact-candidate profile dispatch and runner-side checks. Preserve no-SA/no-external-IP validation, reboot proof, evidence, cleanup, exact-candidate copy, and old-head preservation. |
| Packer/workflow tests | `shifter/packer/tests/test_packer_gcp.py`, `test_packer.py`, and `test_scripts.sh` | Keep provider separation, source/family/manifest catalogs, TechVault script invariants, workflow choices, validation behavior, and negative/fail-closed cases in the existing suites. |
| Operator API | `mcp/ops/lib.js`, `schemas.js`, `tools/images.js`, and `lib.test.js` | If `build_gce_image` is the supported operator surface, extend its existing Zod enum, argv-array dispatcher, infra-mutation policy, and error envelope. Do not add `build_techvault_gce` or interpolate shell. Resolve the current workflow/enum drift rather than adding another list that disagrees. |
| Scenario contract | `cms/scenarios/templates/techvault.yaml`, CMS hydration, `shared.range_cells`, and the existing `RangeSpec`/request envelope | Keep `ami_key: techvault`, `os_type: kali`, and declared SSH/RDP access as authored logical intent. Do not add a GCE family, machine type, disk size, or provider DTO to scenario YAML. |
| GCE realization | `config/_gce.py`, `gcp_range_cell_scenario.py`, `gcp_range_cell_plan.py`, `gcp_range_cell_resources.py`, `gcp_range_cell_outputs.py`, and `executors/factory.py` | The companion resolver must reuse the existing per-instance plan fields for approved image profile, host/participant username, SSH port, sizing, and SA attachment. Keep image-reference/disk validation, Shielded VM rendering, strict host-key verification, and secret-reference outputs. |
| Runtime env propagation | `scripts/gcp/render_runtime_env.py`, `installation/runtime_inventory.py`, `engine/ecs/_env.py`, Helm/Kubernetes provisioner Job allowlists, and `_gcp-dev.yml` | A temporary global smoke binding must traverse the existing `GCP_RANGE_KALI_*` shape. Do not add `GCP_RANGE_TECHVAULT_*` as a second permanent schema under #1760. |
| Runtime setup | `instance_orchestrator.py`, `SetupOrchestrator`, `TechVaultRangeBootstrapPlan`, GCE guest SSH execution, and setup-output masking | Reuse lifecycle, transport, password/SSH setup, cleanup, and error handling. Keep #1446's Vertex credential work separate; do not bake cloud credentials or pretend the AWS Bedrock shard proves Vertex readiness. |
| Logs, state, and errors | `log_redact.safe_log_fingerprint`, GCE provisioner cleanup/status paths, provider metadata/state helpers, and CMS/engine sanitized errors | Record non-secret image/run/range identities and secret references only. Use current exception/status vocabularies and cleanup; add no TechVault status or exception hierarchy. |
| Architecture/security policy | ADR-004-R23, ADR-030, ADR-037, `gcp-guest-images.md`, `gce-range-guest-image-pipeline-preflight-1343.md`, and `credentialed-workflow-dispatch-trust-preflight-1690.md` | Preserve reviewed-code provenance, native-GCE containment, honest VM provenance, candidate evidence, and GCE/GDC/AWS artifact separation. |

## Cross-Cutting Layers The Intended Design Must Pass

1. **Dispatch and input shape.** `image_type` and environment stay closed
   choices. A TechVault version input, if operator-selectable, is validated
   against the existing version shape before export. Project, network, service
   account, and destination family are environment-owned, not caller-selected.
2. **GitHub authorization and WIF.** The job runs only from an allowed protected
   ref and exact repository/environment subject. The WIF provider is the
   external trust boundary; `contents: read` and job-local `id-token: write`
   remain minimal. No key file, PAT, arbitrary ref checkout, or broadened
   principal binding is introduced.
3. **Packer configuration.** `packer init`/`validate` and
   `test_packer_gcp.py` enforce the googlecompute-only source, required typed
   variables, family/label/manifest alignment, disk sizing, and script wiring.
   Dynamic values enter as `PKR_VAR_*`, not `-var` process arguments.
4. **Builder OS and metadata exposure.** The builder uses the existing
   internal-IP/IAP subnet and dedicated build service account. Root-run package
   installers are integrity-verified before execution. Cloud tokens, Packer
   keys, histories, build logs, and transient files do not survive capture or
   enter summaries/artifacts. Runtime images contain no build service account.
5. **Candidate gate.** The trusted runner boots the concrete image with no
   external IP, service account, or scopes, asserts Shielded VM posture, injects
   only a disposable instance SSH key, performs the TechVault checks over IAP,
   repeats them after reset, and always removes the VM. Family/profile mismatch
   or any failed check blocks evidence and promotion.
6. **Promotion/publication.** The immutable candidate, successful trusted
   validation run, source revision, and evidence identity agree before copy.
   The prod family is updated only after the copied image is READY; failure
   leaves the previous head intact. Packer manifests/evidence are workflow
   artifacts, not application persistence.
7. **Scenario/request validation.** The unchanged TechVault YAML continues
   through CMS schema/hydration and the digest-bound `shared.range_cells`
   request validator. `ami_key` stays logical authored intent; provider
   identifiers are backend-owned realization data.
8. **Runtime config shape.** Any isolated smoke binding passes the existing
   runtime renderer, inventory, task env allowlist, admission policy, and
   `load_gce_range_cell_config` image-reference, disk-type, and minimum-size
   validators before a Compute Engine client is constructed.
9. **GCE realization and OS access.** The existing plan creates a no-public-IP
   Shielded VM, injects separate participant/management keys, and records the
   generated host key for strict SSH verification. TechVault requires host and
   participant user `ubuntu` on port 22 and no Polaris-style host service
   account by default. The setup path writes the per-range local password; no
   password or private key enters GCE metadata, argv, DB fields, or logs.
10. **Errors and observability.** Workflow failures use non-zero exits and
    `::error::` with image type, candidate, phase, and run correlation only.
    Runtime failures use existing provisioner cleanup, safe fingerprints,
    request/range/instance correlation, and sanitized CMS/engine envelopes.
    Do not emit environment dumps, metadata bodies, credentials, compose
    secrets, raw cloud errors, or full guest logs.

## Extensibility Seam

The release seam is the existing logical image-type/profile tuple:
`(environment, image_type=techvault, immutable candidate, evidence, family)`.
The TechVault-specific parameter is the pinned APTL version; build sizing and
runtime sizing remain separate provider configuration.

The runtime companion must map the existing authored `ami_key` into fields the
GCE instance plan already owns: image profile, machine/disk sizing, participant
user, host-management user/port, and whether a host service account is
attached. Those traits must remain independent. In particular, adding
`techvault` to `_DOCKER_HOST_AMI_KEYS` would conflate TechVault with Polaris and
incorrectly move SSH to port 2222 and attach the Polaris-style host identity.

This seam lets the next scenario host add a checked-in image/validation profile
without another workflow, public scenario field, env-schema family, cloud
adapter, or lifecycle branch.

## Whole-Repo Surfaces In Scope

- GCE image build and shared guest scripts: `shifter/packer/gcp/**`,
  `shifter/packer/scripts/techvault/**`, and `shifter/packer/tests/**`.
- Credentialed workflows and policy: `.github/workflows/packer-gcp.yml`,
  `packer-gcp-validate.yml`, `packer-gcp-promote.yml`, ADR-004/ADR-037 guards,
  action pinning, and quality path ownership.
- Optional operator exposure: `mcp/ops` image schemas, argv builders, tools,
  policy class, and tests.
- Runtime acceptance only: the TechVault scenario, shared range-cell envelope,
  GCE config/adapter/plan/resources/outputs, strict guest executor, setup
  orchestrator, state/error/cleanup paths, and current runtime-env allowlists.
- Documentation: `shifter/packer/gcp/README.md`, `gcp-guest-images.md`,
  `gcp-range-cell-deploy.md`, `deploy-secrets.md`, and the TechVault runbook
  when the implementation changes their operational truth.

## Gotchas And Anti-Patterns

- Do not call the GCE artifact an AMI or publish it to `/shifter/ami/*`.
- Do not copy the AWS Packer source into `gcp/`; reuse the guest scripts while
  expressing GCE source, networking, identity, labels, family, and manifest in
  the provider-scoped template.
- Do not treat Packer success, a RUNNING VM, 30 container names, or a mutable
  family head as sufficient validation. Prove the participant contract on the
  exact candidate and after reboot.
- Do not count the successful one-shot initializer as a required long-running
  container, and do not reject its expected zero exit while ignoring genuinely
  failed or unhealthy services.
- Do not assume the GCE base has an `ubuntu` UID-1000 user or that the generic
  Kali access mapping will reach it.
- Do not use the Kali default disk/machine profile blindly, translate
  `r5.2xlarge` into a GCE API request, or shrink the runtime disk below the
  source image.
- Do not add TechVault to the Polaris Docker-host key set. Image selection,
  participant endpoint, host management port, and cloud identity are separate
  concepts even though both scenarios use `os_type: kali` over an Ubuntu/Debian
  Docker host.
- Do not attach the range-host service account merely because Polaris does.
  Any Vertex identity for TechVault belongs to #1446 and must preserve the
  per-range secret/metadata isolation boundary.
- Do not write an AWS Bedrock shard on GCP and report that as Vertex readiness.
  #1760 may prove image and range provisioning while explicitly recording the
  #1446 model-credential limitation.
- Do not let the generic Linux export branch silently publish a GDC qcow2 or
  invent a GDC runtime variable for this native-GCE issue.
- Do not duplicate image-type enums, TechVault health scripts, validation
  workflows, promotion logic, exception classes, config parsers, logging
  helpers, secret adapters, or persistence models.
- Do not weaken WIF subject/ref checks, protected Environment rules, IAP-only
  networking, no-SA validation, Secure Boot, strict host-key verification,
  action pinning, Packer tests, SAST, actionlint, or ADR guard to get a bake
  through.

## Non-Goals And Implementation Boundaries

- No issue implementation, image build, workflow dispatch, promotion, tenant
  configuration mutation, or range launch in this preflight.
- No implementation of the companion per-instance GCE `ami_key` resolver.
- No implementation of #1446 TechVault Vertex model credentials and no claim
  that Claude model access works on GCP without it.
- No GDC VM Runtime TechVault image/export, AWS AMI behavior change, SSM
  publication change, or cross-provider image portability promise.
- No public scenario/ACES schema change, CMS/CTF lifecycle change, new runtime
  env family, image catalog/database, service/repository layer, exception
  hierarchy, logging framework, secret store, or promotion controller.
- No automatic prod promotion or weakening of the evidence/protected-ref
  release gates.

## Acceptance Evidence Boundary

Issue #1760 is not proven by static Packer tests alone. The implementation must
show the exact candidate in family `shifter-techvault` in the intended tenant
project, pass the trusted candidate boot/reboot profile, and launch a clean GCE
range through the normal provisioner. The range evidence must identify the
concrete source image, correct `ubuntu` host/participant access on SSH and RDP,
adequate machine/disk sizing, healthy APTL services, no public guest address,
Shielded VM posture, normal sanitized status/cleanup, and successful destroy.
The evidence must state that Vertex model credentials remain governed by #1446
when that issue has not landed.

For implementation changes touching the Packer/workflow/architecture surfaces,
the repository gates include the Packer test suite and `packer validate`,
shellcheck/SAST, `actionlint`, and:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```
