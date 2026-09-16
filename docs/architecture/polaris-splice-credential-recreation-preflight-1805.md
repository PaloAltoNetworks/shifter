# Polaris Splice Credential Recreation Preflight

Issue: GitHub #1805, "Polaris: preserve splice-relay credential across
a14-kali recreation".

This note records the architecture boundary for the future fix. It is not an
implementation plan.

## Boundary and decisions

The splice key is range-local participant scenario material. Its durable source
for the deployed `polaris-vm` path is the retained Compose environment binding:
`KALI_SPLICE_PRIVATE_KEY_B64` on `a14-kali`, paired with
`A9_AUTHORIZED_KEY` on `a9-splice`. The private key file and SSH client config
are projections of that binding and must be recreated whenever the container's
writable layer is recreated.

Keep these responsibilities separate:

- The Kali image owns in-container hydration on every entrypoint run, before
  SSH or XRDP starts.
- `PolarisRangeBootstrapPlan` owns range-local key generation, Compose binding,
  initial container recreation, provider-neutral verification, and invocation
  of the same post-create check/repair contract.
- Operator fleet tooling discovers and selects existing ranges, invokes that
  contract, and reports bounded status. It is not a second credential renderer.
- The splice watcher owns only the flag-19 network attachment. It must not
  hydrate credentials, rotate keys, or make authentication success a condition
  for opening the topology gate.
- Image-bake validation proves that retained Compose configuration survives a
  force-recreation. Fresh-range acceptance proves the real per-range key pair
  and post-gate participant SSH path.

Use one small in-container hydration/check helper as the behavioral source of
truth. The image entrypoint invokes it; bootstrap and fleet repair invoke the
same artifact through `docker exec`. The helper needs separate check and repair
modes so health inspection stays read-only and repair is explicit. Older baked
images that do not contain the helper may receive that exact reviewed artifact
over the existing host execution channel before invocation; do not maintain a
second inline repair implementation for legacy images.

The helper must converge, not merely append:

- decode to a restrictive temporary file, validate it as a usable private key,
  and atomically install `/home/kali/.ssh/splice_relay` as `kali:kali`, mode
  `0600`, under a `0700` `.ssh` directory;
- converge exactly one managed `Host splice-relay` configuration entry with the
  established host, user, and identity-file contract, preserving unrelated user
  SSH configuration;
- fail closed on an absent, empty, malformed, or unusable environment value and
  leave the last valid target untouched;
- emit only named check outcomes. Never emit the environment value, decoded key,
  derived public key, `docker inspect` environment, or raw SSH diagnostics.

The private Compose stack is an external, checksum-pinned bake input; its
`scenario-dev/polaris/build/` output is deliberately untracked under
ADR-004-R8. Therefore changing
`scenario-dev/polaris/containers/boreas-kali/entrypoint.sh` alone cannot satisfy
this issue. The deployed stack's A14 image must consume the same helper and a
new stack artifact and `polaris-vm` image must pass the existing bake and
promotion gates. The tracked RAES container path should remain aligned when it
supports this binding, but it is not evidence that the deployed Compose path was
fixed.

## Cross-cutting incumbents

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Per-range credential binding | `POLARIS_RANGE_BOOTSTRAP_SCRIPT` in `shifter/engine/provisioner/plans/_polaris_scripts.py` | Keep the existing environment names, per-range Ed25519 generation, atomic Compose override rewrite, and selective `dns`/`a14-kali`/`a9-splice` recreation. Do not add a credential DTO or second key store. |
| Setup lifecycle | `PolarisRangeBootstrapPlan`, `SetupStep`, `SetupOrchestrator` | Keep new-range mutation and verification on the existing plan. A failed hydration or verification remains a failed setup step. |
| Host execution | `build_guest_execution_context` and the shared executor exceptions in `executors/base.py` | Preserve AWS SSM versus GCE management-SSH selection. Do not add provider-specific command loops or a new exception hierarchy. |
| Rendering and redaction | `SetupOrchestrator._render_script`, `_mask_sensitive_output`, and `tests/test_plan_template_tokens.py` | Use the existing template-token gate and sanitized setup envelopes. Do not log rendered secret-bearing material or add another renderer/logger. |
| Bootstrap verification | `VERIFY_POLARIS_BOOTSTRAP_COMMON` | Extend the provider-neutral contract rather than forking AWS and GCP splice checks. Presence alone is insufficient: ownership, mode, effective SSH config, and A14/A9 public-key equivalence are required. |
| Participant topology | `INSTALL_SPLICE_WATCHER_SCRIPT`, `scenario-dev/polaris/tests/isolation-smoketest.sh`, and the Bunker walkthrough | Preserve pre-gate isolation and the A14 -> A9 -> Bunker path. Authentication repair must not attach networks or bypass A9. |
| Image qualification | `shifter/packer/scripts/polaris/bootstrap.sh`, GCP `verify-stack.sh`, GCP `validate/linux.sh`, AWS `golden-verify.sh`, and their existing tests | Exercise the actual external Compose artifact and force-recreate `a14-kali` twice; a render-only assertion is not regression evidence. |
| Generated artifact hygiene | `.gitignore`, ADR-004-R8, and `no-tracked-generated-artifacts` | Do not commit `scenario-dev/polaris/build/`, generated key pairs, Compose overrides, fleet reports, or private stack contents. |
| Operator surface | Current provider transport and target-discovery conventions; `mcp/ops` policy/Zod/argv-array boundaries if exposed there | Health is read-only; repair is a distinct mutation with dry-run/selection/audit gates. Do not revive the deleted AWS-only health script as a second source of runtime behavior or misrepresent it as GCP fleet coverage. |

## Security and validation layers

- **Environment binding shape.** Docker Compose parses the external stack and
  `docker compose config` remains the syntax gate. The provisioner supplies the
  value from local `ssh-keygen` plus single-line base64; no public scenario,
  RAES, CMS, or Ground Control schema should gain a private-key field. At the
  consumption boundary, strict base64 decoding and `ssh-keygen` usability
  validation reject corrupt retained state before replacement.
- **Authentication surface.** A9 remains public-key-only and the bare
  participant verb remains `ssh root@splice-relay`. Compare the key type and
  public blob derived from A14 with A9's authorized entry without logging either
  side. Do not relax A9 password policy or authorize an additional fallback key.
- **Filesystem surface.** Use restrictive creation, explicit owner/group and
  modes, same-filesystem atomic replacement, and cleanup traps. Verification
  must check numeric uid/gid equivalence to `kali:kali`, not only display names,
  and must reject symlink/non-regular targets so a compromised writable layer
  cannot redirect a root entrypoint write.
- **OS/process exposure.** Base64 is encoding, not encryption. Compose retains
  the value in container configuration and a participant can ultimately read
  the projected key by design. The value must not be copied into command argv,
  shell tracing, temp filenames, reports, or host logs. Prefer invoking the
  in-container helper so it reads its own inherited environment; never print or
  return `docker inspect` environment data.
- **Command and transport boundary.** Provisioner execution continues through
  `SetupOrchestrator` and its selected executor. If an MCP operator tool is
  added, reuse `EnvSchema`/identifier schemas, `mcp/shared/aws-helpers.js` argv
  arrays where applicable, capability classes, two-phase mutation, audit
  sanitization, and the shared `ok`/`err` envelope. A GCP fleet claim requires a
  real GCE management-SSH target path; the current AWS-only MCP range discovery
  is not provider parity.
- **Logging/error envelope.** Success and failure output may name the range,
  instance, container, check, mode, ownership, or permission mismatch. It must
  not contain key bytes, encoded values, derived public keys, full container
  configuration, shell bodies carrying secrets, or raw SSH output. Because the
  splice value is created inside host shell execution rather than a sensitive
  Python context key, `SetupOrchestrator` replacement masking is defense in
  depth, not permission to echo it.
- **Network policy.** Before `Lights Out`, A14 must remain detached from
  `splice-link`; afterwards it may reach A9 only through that link. Direct A14
  access to Bunker OT remains denied. Credential health and topology state are
  independent report fields.
- **Repository/release gates.** Provisioner template lint, focused shell and
  behavioral tests, Packer tests, gitleaks, and ADR guard remain in force. A new
  external stack digest and rebuilt provider image are release evidence; a
  source change without those artifacts does not meet the deployed-path
  acceptance criterion.

The current `StrictHostKeyChecking no`/`UserKnownHostsFile /dev/null` scenario
client behavior is an existing gameplay tradeoff, not a pattern for operator
transport. Changing A9 host-key trust requires a separate design that supplies a
trusted per-range host key and is outside this defect.

## Extensibility seam

Keep the seam at the helper invocation: `check` versus `repair`, with the
container identity supplied by the caller. Fleet selection additionally needs
provider, environment, range/instance selection, Compose directory/project, and
bounded concurrency as explicit validated inputs. The credential environment
name, filesystem destination, SSH alias, A9 service name, and target account are
the stable Polaris gameplay contract and should remain reviewed constants, not
arbitrary operator-provided paths or commands.

This supports the next reasonable variation -- a renamed Compose project or a
provider-specific fleet transport -- without duplicating hydration or weakening
the fixed credential contract.

## Whole-repository surfaces

- External checksum-pinned Polaris Compose stack and its A14 image/entrypoint.
- `scenario-dev/polaris/containers/boreas-kali/` as the tracked RAES realization,
  without treating it as deployed Compose evidence.
- `shifter/engine/provisioner/plans/_polaris_scripts.py`,
  `_polaris_scripts_aux.py`, and `polaris_range_bootstrap.py`.
- `shifter/engine/provisioner/polaris_bootstrap.py`, `orchestrators/`, and
  `executors/`.
- `scenario-dev/polaris/tests/setup.sh`, `isolation-smoketest.sh`, A9/Bunker
  smoketests, and walkthrough validation.
- AWS and GCP `polaris-vm` Packer bootstrap, qualification, workflows, and tests.
- The selected provider's fleet target-discovery/remote-execution surface; the
  current repository has no tracked replacement for the deleted
  `scripts/polaris-aws-range/check_range_health.py`.
- `.gitignore`, `.gitleaks.toml`, ADR-004-R8, and ADR guard.

## Gotchas and anti-patterns

- Do not rely on the initial imperative `docker exec` staging block; recreation
  must repair itself from retained configuration before participant services
  start.
- Do not make the entrypoint append-only. A pre-existing wrong or partial Host
  stanza must converge, and repeated recreation must not duplicate it.
- Do not write directly over a valid key before decode/key validation succeeds,
  and do not follow a symlink at the destination.
- Do not compare or report private bytes. Do not print public keys either; report
  only match/mismatch.
- Do not pass the key as a CLI argument, enable `set -x`, dump Compose config or
  `docker inspect`, or return raw SSH output through SSM/MCP error envelopes.
- Do not rotate only one half of the pair during repair. The retained A14 value
  is authoritative for A14 recreation; a true pair mismatch is a failed contract
  requiring deliberate pair reconciliation, not an excuse to silently overwrite
  A9 from participant-controlled state.
- Do not restart the stack, A9, the watcher, or unrelated containers to repair an
  A14 file projection.
- Do not couple credential hydration to flag-19 state or network attachment.
- Do not add a generic scenario-secret schema, secrets manager, credential
  repository, validation framework, logging wrapper, exception hierarchy, or
  provider executor for this one projection.
- Do not claim regression coverage from static script substring tests, the
  tracked RAES image alone, or a fresh bootstrap that never force-recreates only
  `a14-kali`.
- Do not commit the external build tree or generated fleet evidence to make the
  test convenient.

## Non-goals

- Implementing hydration, repair, fleet mutation, or tests in this preflight.
- Rotating healthy per-range key pairs or moving participant scenario material
  into a cloud secrets manager.
- Replacing Compose, the `polaris-vm` bake model, `PolarisRangeBootstrapPlan`,
  the watcher, or the provider execution transports.
- Changing the flag-19 trigger, Docker topology, Bunker challenge content,
  scoring, flags, or participant account model.
- General host-key trust redesign, SSH certificate authority introduction, or
  reuse of participant SSH policy for operator access.
- Restarting or repairing unrelated Kali concerns such as RDP, DNS, Vertex,
  Bedrock, sudo, nmap, or tmux as part of splice credential repair.

## Implemented operator contract

The provisioner installs the reviewed helper at
`/opt/polaris/libexec/polaris-splice-credential.py`. Its host modes are the
provider-neutral fleet seam and return only bounded status text:

```text
/opt/polaris/libexec/polaris-splice-credential.py host-check --container a14-kali
/opt/polaris/libexec/polaris-splice-credential.py host-repair --container a14-kali
```

The provisioner exposes those operations for an existing range request as
`range splice-check` and `range splice-repair`. Transport selection remains in
`build_guest_execution_context`, so AWS uses SSM and GCE uses the pinned
management-SSH channel. Repair touches only the A14 credential projection; it
does not restart or recreate any container.
