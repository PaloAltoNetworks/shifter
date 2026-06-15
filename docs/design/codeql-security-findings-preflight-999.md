# CodeQL Security Findings Preflight - Issue 999

## Scope

Issue 999 is a requirement-free security maintenance pass for 13 CodeQL alerts
from upstream PR `PaloAltoNetworks/shifter#1379`. The implementation must clear
the listed alerts in the Brad-Edwards repo first and remain carry-forwardable to
upstream.

This is not a new logging framework, scenario system, exception model, or
workflow redesign. The work is limited to preserving existing behavior while
hardening four security boundaries: sensitive-value logging, user-controlled
path construction, externally visible error envelopes, and log-injection sinks.

## Architectural Decisions

- Treat each alert as a boundary fix, not as a local string replacement.
  Sensitive logging, log injection, path traversal, and exception exposure have
  different taint models and must use the matching existing helper or validator.
- Provisioner code is a standalone runtime. It should use
  `shifter/engine/provisioner/log_redact.py`; do not import Django platform
  `shared` modules into the provisioner to fix logging.
- Django platform code should use
  `shifter/shifter_platform/shared/log_sanitize.py` and
  `shifter/shifter_platform/shared/errors.py`; do not import provisioner
  `log_redact` into Django apps.
- For CodeQL clear-text sensitive logging, `safe_log_value` and `safe_log_id`
  are not enough. Redact by not logging the value at all, or use
  `safe_log_fingerprint` when operators still need within-process correlation.
- For CodeQL log injection, use `safe_log_value` on user-controlled display
  fields, names, keys, and exception text. Do not use fingerprints when readable
  sanitized text is intentionally part of the operational signal.
- Scenario template IDs are identifiers before they become filenames. The YAML
  loader must validate the ID shape and then resolve the candidate path under
  `TEMPLATES_DIR`; the registry and schema remain the canonical higher-level
  scenario contracts.
- View responses must return authored or classified messages, not raw
  `str(exc)`, when CodeQL traces an exception into a response body. Preserve the
  detailed exception in server logs only.
- CTF services should keep using the existing CTF exception hierarchy and
  service-layer authorization. A logging fix must not introduce endpoint-local
  DTOs, validators, or parallel exception classes.

## Cross-Cutting Concerns To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Provisioner log redaction | `log_redact.safe_log_value`, `safe_log_id`, `safe_log_fingerprint` | Use `safe_log_fingerprint` for sensitive identifiers or secret-derived values; use `safe_log_value` for log-injection-only text. |
| Platform log sanitization | `shared.log_sanitize.safe_log_value`, `safe_log_id`, `safe_log_fingerprint` | Keep platform code on the shared helper and keep tests in `tests/shared/test_log_sanitize.py` authoritative. |
| Error envelopes | `shared.errors.classify_user_message`, `UserFacingError`, `safe_user_message` | Responses choose from authored strings or explicit user-message fields; raw exception text stays in logs. |
| Scenario loading | `cms.scenarios.loader`, `cms.scenarios.registry`, `cms.scenarios.schema.ScenarioTemplate` | Loader validates filesystem access; registry handles YAML-vs-DB lookup and metadata; schema validates scenario structure. |
| Scenario editor validation | `cms.scenario_editor._validation.validate_scenario_id`, `validate_definition`, `validate_yaml` | Do not duplicate editor validation inside unrelated views or services. |
| CMS experiments | `cms.experiments.schemas`, `cms.experiments.exceptions`, `cms.experiments.services` | Keep HTTP parsing in views, business validation in services/schemas, and existing exception classes. |
| CTF domain errors | `ctf.exceptions` (`CTFValidationError`, `CTFNotFoundError`, `CTFPermissionError`, `CTFStateError`) | Do not create a second CTF logging/security exception hierarchy. |
| Storage keys | `shared.s3.sanitize_s3_filename`, shared cloud storage adapters | Keep object-key normalization and logging in existing storage surfaces. |
| Logging configuration | `shifter/engine/provisioner/logging_config.py`, `shifter/shifter_platform/config/logging.py` | Do not change formatter behavior to hide a call-site leak; fix the tainted call site. |
| Architecture gates | `.importlinter`, `.ground-control.yaml`, `.gc/plan-rules.md`, `scripts/adr_guard/adr_guard.py` | Respect Django app boundaries and run the repo-required checks for touched subsystems. |

## Security Layers

- Auth surface: the listed Django alert sites sit behind existing view/service
  permissions (`threat_research_required`, CTF participant/organizer service
  gates, and scenario registry access checks). Fixes must preserve those gates
  and must not treat a sanitized log or error message as authorization.
- Secret-handling surface: NGFW SSH key secret references, private keys, event
  payload identifiers, Terraform outputs, bootstrap object locations, and
  generated tokens must not appear in logs as raw values. Prefer removing the
  field from the log line; otherwise log a `safe_log_fingerprint`.
- Config and schema validators: scenario IDs must pass the loader's file-access
  validation before path construction, scenario payloads must still validate via
  `ScenarioTemplate`, experiment inputs via experiment schemas, and CTF inputs
  via existing services/exceptions.
- OS/runtime exposure: fixes should not move secrets into command arguments,
  environment variables, temp files, Terraform stdout, subprocess logs, or
  long-lived process-global state. Fingerprint caches are process-local
  correlation aids, not durable identifiers.
- Error envelope: API and JSON responses must use generic/authored messages for
  unexpected errors and classified fixed literals for known backend failures.
  Full stack traces and raw exception text remain server-side.
- Observability: keep module loggers and useful correlation fields, but classify
  fields as readable safe values, fingerprints, counts/statuses, or omitted
  secrets before logging them.

## Extensibility Seams

- Logging: if another CodeQL logging rule appears, extend the two canonical
  sanitizer modules and their tests rather than adding per-file sanitizers. Keep
  the provisioner and Django implementations separate unless the runtime
  packaging is intentionally redesigned.
- Scenario IDs: if default YAML IDs and editor-created IDs need one shared
  grammar, extract a small helper under `cms.scenarios` and explicitly reconcile
  the current case-policy difference. Do not move scenario ID validation to
  `shared`; it is a CMS/scenario domain concern.
- Error responses: if services need curated client messages, add an explicit
  user-message property or use `UserFacingError`; do not infer response bodies
  from arbitrary exception strings.
- Alert verification: keep fixes source-to-sink aware so the same dataflow break
  clears upstream CodeQL when carried to `PaloAltoNetworks/shifter`.

## Non-Goals And Anti-Patterns

- Do not implement broad repo-wide logging rewrites to make a small alert list
  disappear.
- Do not hash secrets for logs; use omission or random per-process fingerprints.
- Do not rely on `safe_log_value` for clear-text sensitive logging alerts.
- Do not surface raw `str(exc)` to users because an exception class is currently
  expected to contain a friendly message.
- Do not change scenario registry behavior, scenario metadata semantics,
  experiment authorization, CTF domain rules, or Terraform/provisioning behavior
  while fixing scanner findings.
- Do not weaken CodeQL, ADR guard, import-linter, or test enforcement.
- Do not add duplicate validators, duplicate schemas, or local exception
  hierarchies for a scanner remediation.
