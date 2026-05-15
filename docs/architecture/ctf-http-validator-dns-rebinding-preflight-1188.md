# CTF HTTP Validator DNS Rebinding Preflight

Issue #1188 closes a DNS rebinding / resolution TOCTOU gap in CTF HTTP flag
validators. This is an outbound validation security fix, not a new flag type,
workflow, proxy abstraction, or challenge schema.

## Boundary

- The canonical HTTP validator remains `ctf.validators.validate_http`.
  `ctf.services.challenge.add_flag` validates organizer-provided
  `validator_config` at creation time, and `ctf.services.submission.submit_flag`
  reaches it only through `verify_flag` / `verify_single_flag`.
- URL syntax, HTTPS-only policy, redirect blocking, timeout bounds, metadata
  hostname blocking, and private/reserved address policy should stay together
  in `ctf.validators`. Do not split creation-time and runtime network policy
  into competing tables.
- The runtime connection must use the address that passed policy, or must
  recheck the address immediately before the connection is made. A plain
  `requests.get(url)` / `requests.post(url)` after a separate DNS check leaves
  the gap open.
- If the implementation pins to a resolved IP, preserve the original HTTPS
  hostname for SNI, certificate verification, Host header, and request target
  semantics. Pinning must not degrade TLS hostname validation.
- If the implementation chooses controlled egress instead, the repo needs a
  documented, enforced egress policy path before relying on it. A comment or
  future infrastructure assumption is not sufficient for this issue.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Flag creation validation | `ctf.services.challenge._validate_http_config` | Keep organizer config validation here and call the same URL policy helper used at runtime. |
| Runtime HTTP validation | `ctf.validators.validate_http` | Keep outbound request construction, timeout capping, redirect blocking, and response parsing centralized here. |
| URL destination policy | `ctf.validators.is_blocked_url`, `_BLOCKED_HOSTNAMES`, `ipaddress`, `socket.getaddrinfo` | Extend this policy into a reusable resolution result rather than creating a second blocklist or DNS parser. |
| Flag dispatch | `ctf.services.challenge.verify_single_flag`, `verify_flag` | Preserve the existing dispatch contract: validators return `bool` and failures fail closed. |
| Submission workflow | `ctf.services.submission.submit_flag` | Do not bypass scoring, rate-limit, attempt, persistence, or participant scoping behavior. |
| Errors | `ctf.exceptions.CTFValidationError` for config writes; boolean false for runtime validator failure | Do not introduce a new exception hierarchy or expose transport internals to participants. |
| Logging | `logging.getLogger(__name__)`; `shared.log_sanitize.safe_log` for user-controlled strings | Log challenge/flag ids and sanitized host/IP policy decisions; do not log submitted flags, auth headers, or full validator URLs with query secrets. |
| Tests | `shifter/shifter_platform/tests/ctf/test_programmable_flags.py` | Add DNS-rebinding coverage beside existing HTTP validator and SSRF tests. |

## Security Layers

- Auth surface: organizer-only flag configuration still enters through
  `api_add_flag` and `add_flag`; participant submissions still enter through
  `api_submit_flag` and `submit_flag`. Authorization is necessary but not a
  network safety control, so runtime policy must run on every HTTP validation
  attempt.
- Config shape: `CTFFlag.validator_config` remains the JSON contract with
  `url`, optional `headers`, `timeout`, and `method`. New connection internals
  must not require persisted per-flag resolved IPs, duplicate DTOs, migrations,
  or new flag types.
- URL parser and policy gate: use `urlparse`, `_BLOCKED_HOSTNAMES`,
  `ipaddress.ip_address`, and `socket.getaddrinfo` policy in one canonical
  helper. The helper must reject private, loopback, link-local, reserved,
  multicast, unspecified, and known metadata hosts for every resolved address,
  including IPv4 and IPv6.
- Connection gate: the address that reaches the socket must be the address that
  passed policy, or the address must be revalidated at connect time. Redirects
  remain disabled so a public endpoint cannot bounce to metadata or private
  infrastructure.
- TLS and HTTP semantics: HTTPS-only remains enforced at creation and runtime.
  Certificate verification must still validate the original hostname; do not
  turn off `verify`, accept arbitrary certificates, or let an IP-literal URL
  replace the original host without preserving SNI and Host behavior.
- Secret-handling surface: submitted flags, custom validator headers, bearer
  tokens in URLs, and response bodies are sensitive. They must stay out of
  logs, exceptions, test snapshot output, process argv, and persisted helper
  state.
- OS/runtime exposure: the Django process should use Python networking APIs.
  Do not shell out to `curl`, pass headers or flags in argv, write request data
  to `/tmp`, or rely on host `/etc/hosts` mutation in production code.
- Error envelope: participant-facing responses keep the existing JSON shape
  from CTF views (`{"correct": false, ...}` or `{"error": ...}` on service
  errors). Runtime network policy failures should produce false validation, not
  leak DNS answers, internal IPs, header names, or provider metadata details.
- Observability: log blocked/rebound decisions with challenge or flag id and
  sanitized hostname/IP class. Avoid high-cardinality full URLs and never log
  the submitted flag or custom header values.

## Extensibility Seam

The seam belongs in a small destination-resolution / connection-preparation
helper in `ctf.validators`, shaped around the parsed URL, original hostname,
resolved address, and policy verdict. That lets a future change add an egress
proxy, allowlisted callback service, resolver cache TTL, metrics, or explicit
IPv6 policy in one place without re-editing `verify_flag`, views, models, or
the flag JSON contract.

If configurability is needed, prefer module-level constants or Django settings
for resolver timeout / maximum addresses / allowed methods. Do not store
ephemeral DNS answers in `validator_config`; rebinding protection is a runtime
connection property, not organizer-authored challenge metadata.

## Gotchas And Anti-Patterns

- Do not validate DNS once and then call the original hostname with `requests`;
  that is the bug.
- Do not fix the issue by disabling TLS verification, skipping SNI, accepting
  IP-literal certificates, or downgrading to HTTP.
- Do not treat `example.com` test mocks that patch only `requests.post` as
  enough. Tests must simulate a hostname whose DNS answer changes from public
  to private/link-local/metadata between validation and connection.
- Do not allow one safe address in a multi-answer response to mask a blocked
  address unless the connection is pinned to the specific safe address.
- Do not create duplicate blocklists in services, views, Terraform, tests, or
  JavaScript. Extend the canonical validator policy.
- Do not add background worker, queue, model, migration, or proxy concepts
  unless the selected remediation actually deploys and enforces controlled
  egress.
- Do not broaden accepted schemes, methods, redirects, timeouts, or response
  formats while touching the validator.

## Non-Goals

- Redesigning CTF flag storage, scoring, submissions, rate limits, or event
  lifecycle.
- Adding new programmable validator types, callback services, or allowlist
  administration UI.
- Building a general outbound HTTP client for the whole platform.
- Adding Terraform, Kubernetes, service mesh, or proxy infrastructure unless
  the implementation intentionally chooses the controlled-egress remediation.
- Changing attachment upload inspection, experiment execution, identity
  providers, or shared cloud adapter behavior.
