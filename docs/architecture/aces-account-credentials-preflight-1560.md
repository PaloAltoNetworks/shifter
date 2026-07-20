# ACES Account Credential Realization Preflight

Issue: GitHub #1560, "feat: realize ACES account credentials (accounts are
login-less; auth_method unrealized)."

Status: pre-implementation architecture guidance. The issue is the shipping
contract. This note does not implement credentials, mail, or manifest changes
and is not an implementation plan.

## Boundary and Decisions

An ACES account is authored environment state, not the provisioner's management
login and not an OCR participant-role mapping. Keep those identities and their
credentials separate. The compiled ACES `ProvisioningPlan` remains the only
platform-to-provisioner intent contract; raw credentials and generated private
keys must never be added to it.

For each enabled account, realization selects a credential strategy from the
authored `auth_method` after the existing ACES shape validation. An absent or
empty method is the ACES default `password`; the only additional method currently
demonstrated by the pinned contract and repository scenarios is the canonical
`publickey` spelling. Because ACES 0.19.1 models `auth_method` as an open string,
Shifter must reject every other value before dispatch and repeat that fail-closed
check in the separate provisioner consumer before cloud or guest mutation. This
is a small backend realization policy, not a new account schema or enum. Do not
normalize aliases or silently fall back to a password.

`password_strength` is authored intent and must be retained by the existing
process-local `AcesPlanAccount` projection. A password strategy must explicitly
map the pinned ACES values (`weak`, `medium`, `strong`, `none`) to backend-owned
generation policy. It must not ignore the field and always generate today's
strong RDP password. `none` must be handled as an explicit no-password semantic
or rejected if a safe login realization is impossible; it must never accidentally
enable a blank password. Public-key realization generates a per-account keypair,
installs only the public half in the target account, and stores only the private
half in the cloud secret store.

Credential generation and installation occur per `(range_id, node instance,
account)` at realization time. Do not put a password or private key in GCE
startup metadata, instance labels, process argv, environment variables, the
serialized plan, apply outputs, runtime snapshots, diagnostics, events, audit
records, or logs. Reuse the post-boot control-plane-to-guest path: deterministic
Secret Manager identity, the provisioner management SSH secret, strict host-key
checking, `GuestExecutionContext`, `SetupOrchestrator`, and verified setup plans.
The guest must not receive permission to read Secret Manager. Only opaque secret
references may be retained in backend-owned state, and those references must not
enter ACES operation evidence under ADR-031-R4.

Account creation may remain in idempotent startup composition, but credential
installation must wait for the guest and account to exist and must be verified.
An account is not realized until the requested login mechanism works: password
state set and unlocked for an enabled password account, or correctly owned and
mode-restricted `authorized_keys` for a public-key account. `disabled` takes
precedence and must leave every login mechanism unusable; no usable credential
may be installed for it. Reconciliation must read-or-create the same secret and
reapply the same public material rather than rotating credentials on every boot
or retry. Destroy must reconstruct and delete every per-account secret just as it
deletes the per-instance ACES management SSH secret.

`mail` needs one cross-OS meaning. A Windows marker file is not realization, and
Windows local SAM accounts have no generic mail-routing-alias primitive. The
implementation must either use a declared, available guest mail provider on both
supported dialects and verify alias lookup/routing, or remove `mail` from both the
manifest and independent realization ledger until such a provider exists. It
must not downgrade Linux's meaning to metadata/marker-file parity or claim a
Windows-only description/registry value as a mail alias. The guest-dialect seam
may select OS commands, but the observable mail semantic must remain the same.

Re-declare `auth_method` in `SHIFTER_PROVISIONER_CAPABILITIES`, the generated
manifest, and `REALIZED_ACCOUNT_FEATURES` only in the same change that provides
cross-boundary proof for every admitted method and both supported OS dialects.
The declaration and independent apply time ledger remain separately authored.
The existing upstream account-feature extractor stays authoritative for deciding
whether an account exercises the `auth_method` capability; do not duplicate its
field-presence rules.

## Canonical Incumbents to Reuse

| Concern | Canonical incumbent | Required boundary |
| --- | --- | --- |
| SDL/account shape | `aces_sdl.accounts.Account`; `aces_backend_protocols.account_features.provisioner_account_features` | Keep upstream validation and vocabulary authoritative. Add only the backend's supported method-value policy; do not create a Shifter DTO/schema. |
| Admission and non-approximation | `shared.aces.runtime_target`, `shared.aces.composition_envelope`, `shared.aces.realization_ledger` | Both `validate()` and `apply()` must reject unsupported/unproved methods before dispatch. Declaration and evidence policy must remain independent. |
| Transport/consumer validation | `serialize_provisioning_plan`; `aces_plan.py`, `aces_composition.py` | Preserve the serialized plan and bounded process-local projection. Mirror the supported-method allowlist across the deployable boundary and pin parity with a test, as contract/version literals already are. |
| Secret lifecycle | `gcp_guest_secrets._read_or_create_secret`, `_aces_secret_id`, `ensure_aces_ssh_secret`, delete helpers; `utils.crypto` | Extend the deterministic read/create/delete pattern and existing cryptographic generators. Never log values or return raw credentials in apply/evidence payloads. |
| Guest transport | `executors.factory.build_guest_execution_context`, `GuestSSHExecutor`, provisioner-issued host key and management SSH key | Drive private-IP setup using the existing trusted management channel; do not grant guest cloud-secret access or use GCE metadata as a secret channel. |
| Password install | `plans.set_local_password.SetLocalPasswordPlan`, `SetupOrchestrator` | Reuse its `chpasswd`-via-stdin and PowerShell `SecureString` behavior, sensitive context naming, verification, retry, and error handling. Parameterize the target username; do not fork OS password scripts. |
| Public-key install | `LinuxBootstrapPlan` authorized-key ownership/mode behavior, Windows `administrators_authorized_keys` handling in `gcp_range_cell_resources`, setup-plan conventions | Reuse the ownership, ACL, quoting, execution, and verification patterns. Arbitrary non-admin Windows accounts require their own correctly ACLed user key path; do not append all keys to the Administrators file. |
| Errors and logs | `AcesPlanError`/`AcesGcePlanError`, ACES `Diagnostic`, `shared.log_sanitize`, provisioner `log_redact`, `SetupOrchestrator` masking | Report stable method/account addresses and coarse failure stages only. Never include credential values, rendered secret-bearing scripts, command output containing a secret, or raw provider exceptions in ACES evidence. |
| Evidence | `aces_snapshot.snapshot_resources`, `events.publish_aces_*`, `docs/architecture/aces-cutover-evidence-1264.md` | Keep snapshots topology-only. Prove guest effects by controlled cross-boundary tests/readback, not by echoing plans, secret refs, or generated values into sidecars. |
| Feature flag/workflow | `SHIFTER_ACES_NATIVE_PROVISIONING`, existing ACES dispatch and `aces-range` command | Add no second flag, CLI payload, env binding, workflow, or persistence schema. Default-off behavior remains unchanged. |

## Cross-Cutting Layers the Design Must Pass

- **ACES parser and planner:** the pinned Pydantic account model validates the
  base shape. The canonical account-feature extractor and manifest govern the
  plan-time feature claim. Shifter's shared envelope must additionally reject an
  unsupported open-string method before persistence or dispatch.
- **Serialized-plan consumer:** `parse_plan` must retain and validate
  `auth_method` and `password_strength`, reject malformed or unsupported values,
  and bind accounts only to declared nodes. This is defense across a separate
  deployable, not a second authored contract.
- **Secret store and IAM:** the provisioner creates/reads/deletes deterministic,
  per-account secrets using its existing Secret Manager client and permissions.
  Range guests receive neither secret-store credentials nor secret references.
- **Config/env shapes:** reuse the current GCE config and default-off ACES flag.
  No password, key, secret ref, supported-method list, or mail-provider detail may
  arrive through an environment variable or new runtime setting.
- **Cloud/OS exposure:** GCE metadata may carry non-secret management/public
  material only. Passwords/private keys travel in memory from Secret Manager to
  the existing SSH executor; only passwords/public keys enter guest commands,
  through non-argv mechanisms. Linux file modes/ownership and Windows
  ACL/SecureString rules are mandatory.
- **Observability and error envelopes:** setup output passes the existing
  sensitive-context masker; outer failures must be reduced to bounded sanitized
  diagnostics/status. `run_aces_range_provision` must not publish raw exception
  text if it can contain rendered commands or provider secret material.
- **Persistence/evidence:** the plan remains authored intent, backend state may
  retain opaque references only if an authorized retrieval consumer needs them,
  and ACES snapshots/operation records remain free of references and values.
  Adding a credential retrieval API is not implied by secret creation.
- **Repository enforcement:** preserve `.importlinter` (`aces_*` only in
  `shared.aces`), ADR guard, layer checks, secret scanning, and the existing
  ACES manifest/conformance/parity suites.

## Extensibility Seam

The seam is a credential strategy selected by the canonical authored method and
parameterized by OS dialect, password strength, range id, concrete node-instance
key, and username. It produces secret lifecycle operations plus an idempotent,
verified guest-install action; it does not produce a new persisted account model.
Adding a future method (for example Kerberos) requires one strategy, explicit
admission in both shared and provisioner policy, and cross-OS evidence, without
editing password/public-key behavior. Mail has a separate guest-dialect adapter
because mail routing and login authentication are different concepts.

## Gotchas and Anti-Patterns

- The ACES default `password` does not cause
  `provisioner_account_features()` to emit `auth_method`; enabled bare accounts
  still need a real password credential even though only non-default methods
  exercise that manifest feature.
- `auth_method` is an open string in ACES 0.19.1. Re-advertising the coarse
  feature without a value allowlist would admit arbitrary methods and recreate
  the over-claim.
- A provisioner management key is not an authored account credential. Do not
  reuse one private key for participant/operator accounts or authorize it for
  every account.
- Node `count` means credentials must be per concrete instance, not per authored
  node address. Username alone is not a globally unique secret id.
- Windows OpenSSH's common `Match Group administrators` configuration reads one
  shared `administrators_authorized_keys` file. Appending an authored account key
  there can authorize it for every local administrator, violating per-account
  isolation. Use a verified account-specific authorization path/configuration or
  reject that account/method combination; do not trade isolation for login success.
- Startup-script quoting is irrelevant to password secrecy: GCE metadata is an
  exposure surface even when shell injection is impossible.
- The current setup masker is defense in depth, not permission to print a
  secret. Sensitive context keys must include `password`, `secret`, or `token`,
  and scripts/verification should never echo values.
- Do not use password hashes in the plan or evidence as a workaround; hashes are
  credentials and can be cracked, correlated, and replayed into `/etc/shadow`.
- Do not propagate credential-operation return values into
  `apply_aces_range_cell` outputs, instance provider metadata,
  `snapshot_resources`, status reasons, or cleanup exception messages.
- Do not invent password/public-key fields that the pinned ACES account contract
  does not carry. Generated credential material is backend-owned realization.
- Do not conflate `mail`, `auth_method`, OCR participant access, the provisioner
  management login, and portal/Guacamole RDP credentials. They have different
  contracts and lifecycles.
- A renderer/unit assertion is insufficient. Capability re-declaration needs a
  normal launch-path test proving login state on Linux and Windows and proving
  that plan/evidence/log/metadata surfaces contain no secret.

## Non-Goals and Implementation Boundaries

- No new SDL, account DTO, API schema, database model/migration, event/sidecar
  kind, exception hierarchy, feature flag, environment setting, Terraform input,
  Kubernetes secret, workflow, or parallel guest executor.
- No participant-role assignment, Guacamole/portal credential brokerage, UI,
  credential display, or general secret-retrieval API. If a later product flow
  must reveal a generated credential, it must use an authorized engine service
  boundary and is separate from proving guest realization.
- No reuse or modification of the cyberscript account/RangeSpec path and no
  change to the provisioner management credential semantics.
- No Kerberos/SPN/domain-join realization, password rotation UI, recovery flow,
  or additional auth method without its own real strategy and evidence.
- No claim that a marker, account description, registry value, parsed field,
  secret-store row, or generated keypair alone proves login or mail realization.
