# Guacamole First-Click RDP Preflight

Issue: GitHub #395, "RDP connection fails on first attempt, redirects to
Guacamole login".

This note records the architecture boundary for fixing first-click Guacamole
RDP reliability. It is intentionally not an implementation plan. The goal is to
keep the fix inside the existing Portal access broker, Guacamole JSON-auth,
secret, config, and platform contracts.

## Decision

Treat the failure as a Guacamole access-brokering / token-readiness problem
unless evidence proves the range guest itself is not ready. A first-click fix
must preserve the current contract:

- The browser POSTs an `instance_uuid` to the Django Mission Control endpoint.
- `engine.services.get_rdp_connection_info` owns range membership, READY-state,
  instance lookup, host resolution, and RDP credential resolution.
- `mission_control.guacamole` owns JSON-auth payload construction, signing,
  token exchange with Guacamole, and browser URL construction.
- `mission_control.views._guacamole` owns request parsing, settings lookup,
  error envelopes, and non-secret request logging.
- The browser only opens a URL after the server has returned a usable URL.

If the implementation needs to wait for Guacamole to accept a newly minted JSON
auth session, the wait belongs behind the existing Guacamole token broker in
`mission_control.guacamole`, not in range provisioning, CTF, templates, or
browser-specific sleeps. The readiness policy should be bounded and
parameterized through Django settings / environment (attempt count, per-attempt
timeout, and backoff) so the same seam can cover RDP now and SSH later if the
shared JSON-auth token path shows the same failure mode.

Do not pre-create permanent Guacamole connection rows, enable direct Guacamole
login/OIDC, or route users around Portal auth as a workaround.

## Canonical Incumbents

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Browser launch | `static/js/terminal-guacamole.js`, `templates/ctf/participant/range.html` | Keep both launch surfaces on the standard Mission Control endpoint. If client behavior changes, avoid duplicate divergent logic. |
| HTTP endpoint | `mission_control.views._guacamole.guacamole_rdp_url` | Reuse `_parse_json_body`, `_require_instance_uuid`, `_get_guac_settings`, `_ViewError`, and `classify_user_message`; do not add a parallel response envelope. |
| Range authorization and connection data | `engine.services.get_rdp_connection_info` plus `engine.services._common` resolvers | Do not import models into Mission Control or CTF for this. The service already enforces active range, READY status, instance UUID membership, GUI OS, host, and credentials. |
| Guacamole JSON auth | `mission_control.guacamole.create_guacamole_rdp_url`, `create_guacamole_auth_payload`, `sign_and_encrypt_payload`, `get_guacamole_auth_token` | Keep this module as the JSON-auth broker. Extend here if token readiness needs a bounded retry/probe. |
| Secret reads | `engine.secrets.get_rdp_password` and `shared.cloud.get_secrets_store()` | RDP passwords and SSH keys remain provider-secret values resolved at access time. Do not fetch secrets in views, JS, CTF, or Guacamole payload tests. |
| Error messages | `shared.errors.classify_user_message`, `shared.log_sanitize.safe_log_value` | Return fixed non-sensitive messages; log operational detail without tokens, URLs, encrypted payloads, RDP passwords, or SSH keys. |
| Runtime config | `config/settings.py`, `entrypoint.sh`, `scripts/gcp/render_runtime_env.py`, Portal SSM parameters, Helm/Kustomize Guacamole runtime secret wiring | New readiness knobs are non-secret config. JSON auth keys and DB credentials stay in secret stores. |
| Platform reachability | AWS `platform/terraform/modules/guacamole/**`, GCP `platform/charts/shifter/**`, `platform/k8s/gcp/**` | Preserve private Portal-to-guacamole-client API reachability and existing ALB/Ingress `/guacamole` browser routing. |
| Observability | existing logger calls and `risk_register.services.audit_session_event` if session audit is added | Use non-secret IDs and outcomes only. Generated Guacamole tokens/URLs are sensitive. |

## Cross-Cutting Layers

Security layers the intended design must satisfy:

- Auth surface: keep `@login_required`, `@require_POST`, CSRF, `_get_user`,
  `Range.get_active_for_user`, `Range.get_instance_by_uuid`, and
  `Range.Status.READY` in the path. CTF participants must continue using the
  standard Mission Control RDP endpoint.
- Secret-handling surface: `GUACAMOLE_JSON_AUTH_SECRET` is hydrated from the
  provider secret store and must match guacamole-client `JSON_SECRET_KEY`; RDP
  guest credentials come from provider-native per-instance secret references.
  No new committed env, tfvars, ConfigMap, URL, log, or database storage for
  secret values.
- Config shape: `GUACAMOLE_BASE_URL` is the public browser URL;
  `GUACAMOLE_API_BASE_URL` is the server-to-server API URL. Do not conflate
  them. Any readiness knob should be a typed setting parsed once, not magic
  constants copied into JS or templates.
- Network/runtime surface: server-side token exchange must keep using the
  private guacamole-client service path when configured. Browser navigation
  must keep using the public `/guacamole` route. Do not broaden Security
  Groups, NetworkPolicies, range firewalls, or expose RDP directly.
- OS/process exposure: do not place JSON auth payloads, auth tokens, RDP
  passwords, SSH private keys, or generated URLs in process argv, shell traces,
  SSM command strings, browser-visible debug logs, or analytics payloads.
- Error envelope: Guacamole token/readiness failures should map to a
  non-sensitive 5xx/503 shape; engine validation failures remain sanitized 400
  responses. A browser redirect to the Guacamole login page is not an
  acceptable success path.
- Persistence: JSON-auth connections are ephemeral. Do not add durable
  Guacamole DB connection rows or Django session/cache token storage unless a
  separate lifecycle, revocation, and cleanup design is accepted.

Maintainability incumbents the implementation must build on:

- `mission_control.guacamole` for JSON-auth crypto, token exchange, and URL
  construction.
- `mission_control.views._guacamole` for request parsing, settings, errors,
  and logs.
- `engine.services` for range/instance ownership, status, host, and
  credential resolution.
- `shared.cloud` / `engine.secrets` for provider-neutral secret reads.
- `platform/terraform/modules/guacamole`, `platform/charts/shifter`, and
  `scripts/gcp/render_runtime_env.py` for the Guacamole runtime wiring.
- ADR/import/secret guardrails: `.importlinter`,
  `scripts/check_layer_imports/layer_imports.yaml`, `docs/adr/index.yaml`,
  `.gitleaks.toml`, ADR-004 secret-env/tfvars checks, and Kubernetes/Terraform
  linters for platform changes.

Extensibility seam:

Keep a single Guacamole JSON-auth session readiness seam in
`mission_control.guacamole`, parameterized by protocol label, attempts,
backoff, and timeout. That allows future SSH, VNC, or Guacamole-version
differences to reuse the same broker without editing Mission Control views,
CTF templates, or range provisioning logic.

## Whole-Repo Scope

In scope for an implementation:

- Django access path:
  `shifter/shifter_platform/mission_control/guacamole.py`,
  `mission_control/views/_guacamole.py`, `mission_control/urls.py`,
  `engine/services/_terminal.py`, `engine/services/_common.py`,
  `engine/secrets.py`, `shared/errors.py`, and `shared/log_sanitize.py`.
- Browser launch surfaces:
  `static/js/terminal-guacamole.js`,
  `static/js/terminal-guacamole.test.js`, and
  `templates/ctf/participant/range.html` if client behavior changes.
- Runtime configuration:
  `config/settings.py`, `entrypoint.sh`,
  `scripts/gcp/render_runtime_env.py`, AWS Portal SSM/user-data wiring, Helm
  values/templates, and Kustomize overlays if new config is added.
- Platform Guacamole reachability:
  `platform/terraform/modules/guacamole/**`,
  `platform/charts/shifter/templates/guacamole-client-deployment.yaml`,
  `platform/charts/shifter/templates/ingress.yaml`,
  `platform/k8s/gcp/base/guacamole-client-deployment.yaml`, and network
  policy/security-group files only if evidence shows platform reachability is
  the actual defect.
- Documentation:
  the current Guacamole technical doc still describes the older direct
  `?data=` flow in places; do not use that stale sequence as the source of
  truth for code changes without updating it.

## Gotchas And Anti-Patterns

- Do not add a blind frontend sleep before `window.open`. It hides the race,
  differs by browser, and duplicates behavior across Terminal and CTF.
- Do not make the first click open multiple Guacamole tabs or retry browser
  navigation with fresh tokens. Retry, if needed, belongs server-side before a
  URL is returned.
- Do not conflate Guacamole token readiness with range READY state, guest RDP
  service readiness, xrdp startup, or network firewall openness. Prove which
  boundary is failing before changing another one.
- Do not log or audit generated URLs, Guacamole auth tokens, encrypted JSON
  payloads, RDP passwords, SSH private keys, or secret reference values under
  credential-like field names.
- Do not fetch RDP credentials from `mission_control.guacamole`, Django views,
  CTF views, templates, or JavaScript. The engine service boundary already
  resolves them.
- Do not introduce a second request schema, exception hierarchy, HTTP client
  abstraction, cloud secret adapter, or CTF-specific RDP workflow for this bug.
- Do not broaden ALB/Ingress path routing, Security Groups, NetworkPolicies, or
  range RDP exposure as a speculative reliability fix.
- Do not enable Guacamole OIDC/direct login as a fallback for failed JSON auth;
  Portal remains the user auth boundary for this flow.

## Non-Goals

- This preflight does not implement the first-click fix.
- Do not redesign Guacamole authentication, replace JSON auth, or migrate to
  durable Guacamole DB-managed connections for this issue.
- Do not change range provisioning, guest credential generation, RDP password
  rotation, SFTP behavior, CTF scoring, or scenario schema.
- Do not redesign the Terminal UI or popup-blocker behavior beyond what is
  required to preserve a single successful first-click launch.
- Do not weaken existing ADR, import-linter, secret-scanning, Terraform, or
  Kubernetes enforcement.

## Validation

At minimum, architecture or `shifter/shifter_platform` changes on this path
must run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Add the stack-native checks for touched surfaces: Mission Control/engine unit
tests for Guacamole URL generation and RDP connection info, Jest tests for
browser launch changes, import-linter for Python import changes, Terraform
lint for platform module changes, and Kubernetes linters/schema validation for
Helm/Kustomize manifest changes.
