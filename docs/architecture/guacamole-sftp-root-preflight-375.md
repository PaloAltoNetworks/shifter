# Guacamole SFTP Root Preflight (#375)

Status: pre-implementation guidance

This requirement-free issue moves the Guacamole SFTP upload/download root out
of Mission Control's OS map. It is not an implementation plan.

## Decision

The SFTP root is non-secret, realized **per-instance connection metadata**. It
must be emitted with the image/guest connection facts, persisted in
`Range.provisioned_instances`, resolved by `engine.services`, and consumed by
the existing Guacamole RDP request. Mission Control must not select it from
`os_type`, Django settings, or a second presentation-layer registry.

The one canonical connection projection is
`engine.services.get_rdp_connection_info`. It already returns the authorized
host, RDP credential material, SFTP private key where applicable, and
`sftp_enabled`; extend that projection with the resolved root and let
`mission_control._guacamole_session_builders` pass it through unchanged.

The source is image-specific configuration at provisioning time, not a global
portal deployment setting. Reuse the GCE `GCERangeImageProfile` validation path
for GCE images. The AWS/legacy provisioner output must emit the same normalized
realized field; an AMI ID alone cannot establish a safe guest filesystem root.
The initial image records preserve Kali `/home/kali`, Ubuntu `/home/ubuntu`, and
Windows `/C:/Users/Administrator/Downloads`.

## Required Boundaries

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Realized-state transport | `engine/provisioner/state_helpers.py`; AWS Terraform instance outputs; GCE `gcp_range_cell_outputs.py` | Emit the same normalized field on every provider path that can offer RDP/SFTP. Persist metadata only; never a credential value. |
| Closed RAES result contract | `shared/operation_result_payloads.py`; `engine/services/_operation_apply_raes.py` | Add the field to the allowlisted member shape and projection together. Unknown fields currently fail closed; do not bypass that parser. |
| Image configuration | `config/_gce_profile.py`, `_gce_image_keys.py`, and their typed/validated `GCERangeImageProfile` contract | Validate at config load, include it in the profile fingerprint, and keep image-key overrides authoritative. Do not add an unvalidated JSON/env map in Django. |
| Connection resolution | `engine.services._common` and `get_rdp_connection_info` | Resolve one normalized value alongside host, username, secret refs, and `participant_sftp_enabled`; Mission Control remains a consumer only. |
| Authorization | `Range.resolve_active_for_instance`, READY check, `find_instance_by_uuid`, `_require_declared_participant_channel` | Resolve the root only after the existing user/range/READY/member/channel gates. Metadata does not grant access. |
| Guacamole encoding | `GuacRDPUrlRequest` and `RDPConnectionParams` | Preserve the existing `sftp_enabled` and credential gate before emitting both Guacamole SFTP directory parameters. |
| Errors and logs | `BootstrapFailure`, `classify_user_message`, `safe_log_value` / `safe_log_fingerprint` | Invalid/missing metadata must fail closed or disable only SFTP according to the existing explicit SFTP policy; never leak raw provider/config errors or log credentials, URLs, keys, or tokens. |

## Validation And Security Rules

- Treat the root as a guest-visible path, not a host filesystem path. It must
  be a bounded non-empty string with the Guacamole/SFTP path form required by
  the target OS; reject control characters, NUL, and traversal/ambiguous forms.
  Windows retains Guacamole's forward-slash `/C:/...` syntax. Validation belongs
  at the image-config/parser and closed result boundaries, not only in a URL
  builder.
- The field is non-secret and may be persisted, but it is still untrusted
  configuration until those shape checks have run. Do not interpolate it into
  shell commands, process argv, Terraform commands, logs, error bodies, or a
  browser query string outside the encrypted Guacamole JSON-auth payload.
- Keep existing secret handling: RDP passwords and SFTP SSH keys are read
  just-in-time through `engine.secrets`; only secret references cross the
  provisioner result/persistence boundary. Do not move secret reads to image
  config, state parsers, Mission Control, or client code.
- Preserve the Guacamole bootstrap error envelope and logging taint breaks.
  `conn_info` is credential-bearing even when logging only the new root or OS;
  do not log it wholesale.
- The path is valid only in the context of the same RDP/SFTP identity that the
  provisioner recorded. Do not derive it from a generic OS default or reuse a
  host-management account for nested/preconfigured hosts.

## Extensibility And Scope

The required seam is an optional normalized `sftp_root_directory` (or one
consistently named equivalent) in the realized-instance/Engine RDP connection
projection. This permits a new image, a changed participant account, or an
image-key override to carry its own root without editing Mission Control. It
does not require a new global settings namespace or a separate Guacamole
configuration schema.

In scope: image-profile/config validation; AWS, GCE, and RAES output-to-state
projections; the RAES closed payload parser when RAES emits the field; Engine
connection resolution; Guacamole RDP handoff; regression tests for all three
existing roots and a custom-image root. Update `docs/features/terminal.md` only
if it continues to assert a universal OS-to-directory table after the change.

Out of scope: changing RDP/SSH authorization, credential generation or
rotation, Guacamole JSON-auth/token lifecycle, Guacamole networking, guest
filesystem provisioning, direct browser SFTP, SSH-terminal behavior, or a new
user-editable catalog/API for filesystem paths.

Avoid: a Django `SFTP_ROOT_BY_OS` setting, a Mission Control fallback map,
duplicated config parsers, permissive RAES `additionalProperties`, a new
exception hierarchy, or silently substituting a guessed home directory when a
new image omitted its declared root. Those choices either recreate the original
coupling or turn a configuration error into a connection that targets the wrong
guest directory.
