# Polaris Scenario Smoketest Preflight

Issue: GitHub #617, "Pre-event scenario smoketest: run every flag's hint path
end-to-end against a staged range".

This note records the architecture boundary for the future implementation. It is
intentionally not an implementation plan.

Supersession note (2026-07-15): #1293 now requires per-scenario adapters and
answer-key material to live in a separately installed plugin. This note remains
the behavioral/security input for the original harness, but its in-tree
coverage-map placement and "no generic framework" non-goal are superseded by
`aces-polaris-scenario-smoketest-coverage-preflight-1293.md`. Core retains only
the provider/pack-neutral framework and ships zero adapters.

## Boundary

The new check is an operator-run, range-time scenario-content verifier. It
should prove that each CTFd challenge entry has a canonical participant path
that produces the value configured for that challenge, against a real staged
Polaris range.

Keep these concepts separate:

- Challenge metadata: `scenario-dev/polaris/build/ctfd-challenges.json` and,
  when explicitly included, `ctfd-onboarding.json`.
- Deployed CTFd state: optional verification through the existing CTFd API
  client, not a new source of truth.
- Range content: files, services, credentials, and network paths inside the
  staged range.
- Walkthroughs: human-readable intent under
  `scenario-dev/polaris/tests/walkthroughs/`.
- Infrastructure checks: machine-executable range checks under
  `scenario-dev/polaris/tests/` that remain in core.
- Scenario solution adapters: separately installed operator code, usually
  derived from reviewed walkthrough and per-asset behavior, that is never
  copied back into the core framework.

The out-of-tree verification plugin may own a small coverage map from challenge
identity to its adapter and non-secret bindings, but that map must not become
another challenge schema. The shared framework does not parse this board,
contain a coverage map, or understand the range topology.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Scenario source order | `scenario-dev/polaris/README.md` source-of-truth section | Reconcile against build artifacts and walkthroughs before older design prose. |
| Challenge metadata | `scenario-dev/polaris/build/ctfd-challenges.json`, `ctfd-onboarding.json` | Do not duplicate challenge names, categories, values, hints, flags, or prerequisites in a second schema. |
| Static flag extraction | `scenario-dev/polaris/build/verify_flags_baked.py::static_flag` semantics | Reuse or factor this parser shape. A challenge without exactly one supported flag must fail closed unless the adapter explicitly supports it. |
| Bake artifact check | `scenario-dev/polaris/build/verify_flags_baked.py` and `test_verify_flags_baked.py` | Keep bake-time literal artifact verification separate from range-time hint-path execution. This issue extends coverage; it does not replace the bake verifier. |
| Range runner topology | `scenario-dev/polaris/tests/run-all-smoketests.sh`, `reset.sh`, and the README asset pivot map | Run checks from the same runner containers participants can reach from: A14, A15, A16, A9, or the range host for isolation. Do not bypass topology to make a test pass. |
| Existing solution material | `scenario-dev/polaris/tests/smoketests/*` and `tests/walkthroughs/*` | Out-of-tree adapter authors should derive checks from reviewed behavior instead of executing Markdown or copying answer material into core. |
| CTFd API access | `scripts/ctfd-workshop/common.py::CtfdClient` and `sync_polaris_ctfd.py::get_all_items` | Reuse the header, timeout, error, and pagination behavior. Do not create another CTFd client or partial schema. |
| CTFd sync workflow | `sync_polaris_ctfd.py`, `sync_polaris_ctfd_onboarding.py`, `sync_range_flags.py` | The smoketest may report CTFd drift but must not mutate CTFd, sync pages, or repair flags as part of validation. |
| Reporting | `shared.scenario_verification` and `docs/technical/shifter_platform/scenario-verification.md` | Render the four closed statuses and aggregate exit from one redacted report DTO. Scenario-specific operator tooling supplies selection and bindings. |
| Architecture gates | `.ground-control.yaml`, `.gc/plan-rules.md`, `scripts/adr_guard/adr_guard.py` | Architecture/doc changes still pass ADR guard. Do not weaken workflow or local enforcement. |

## Cross-Cutting Layers

Security layers the future design must satisfy:

- Auth surface: no participant-facing Django route, CTF service endpoint, or
  CTFd plugin is required for this issue. It should stay an operator-run CLI
  against an authorized staged range.
- CTFd token handling: if live CTFd verification is added, use `CTFD_TOKEN` or a
  local token file with restrictive permissions. Do not pass admin tokens on the
  command line, copy them into participant containers, print them, or make Kali
  responsible for CTFd calls. The Polaris participant flow deliberately has
  Kali and CTFd in separate browser tabs, and Kali is not a CTFd API client.
- CTFd API shape: use `CtfdClient`, including `Authorization: Token ...`,
  `Accept: application/json`, and `Content-Type: application/json`. Pagination
  must follow CTFd metadata instead of assuming one page.
- Challenge schema gate: out-of-tree operator tooling parses JSON with the
  standard JSON parser and validates identity, flag shape, and adapter coverage
  before invoking core. Missing coverage is an acceptance-universe blocker,
  not a `blocked` runtime result and not a silent skip.
- Range execution gate: honor `RANGE_DIR`, `COMPOSE_PROJECT_NAME`,
  `SMOKETESTS_DIR`, existing `docker cp`/`docker exec` runner conventions, and
  `reset.sh` for sticky state. Do not attach extra networks, relax isolation,
  alter service ACLs, or patch files before a path check.
- OS/process exposure: do not build shell strings from challenge names, hint
  text, CTFd descriptions, or other metadata. Prefer Python subprocess argv
  arrays for new wrappers; where existing shell tests are reused, keep
  untrusted metadata out of shell evaluation.
- Walkthrough handling: walkthrough Markdown is reference material. The
  machine contract must live in scripts or adapters that are reviewed as code,
  not in ad hoc extraction of commands from prose.
- Secret handling: CTFd admin tokens, participant credentials, service account
  passwords, private keys, and static flags must not be written to tracked
  reports, CI artifacts, workflow logs, process argv, or Docker environment
  variables. Per-check reports should use stable ids and match/mismatch-class
  reason codes only. Deterministic hashes of expected or produced values are
  not redaction and must not be persisted.
- Error envelopes and logs: reports include only bounded plugin/adapter ids,
  closed status/reason codes, and durations/counts. They must not include raw
  API response bodies, authorization headers, runner targets, command output,
  or submitted/expected values. Use `shared.log_sanitize.safe_log_id` and
  `safe_log_value` for any separate operator log fields.
- Network boundary: tests must exercise the same pivot path as a participant.
  A14 can reach shared/corporate and the splice path only after the designed
  gate; A15 reaches SCADA; A16 reaches Lab; A9 reaches Bunker OT. Host-side
  checks are for orchestration/isolation only.
- Validation gates: changes under `scenario-dev/polaris/tests/` should run the
  staged-range sweep they add or a targeted local unit test for parser/report
  behavior. Changes touching architecture docs or guardrails must pass
  `python3 scripts/adr_guard/adr_guard.py --all --level ci`.

Maintainability incumbents the implementation must build on:

- Existing per-asset smoketests for the flag extraction mechanics.
- Existing walkthroughs for human-readable expected paths.
- Existing CTFd JSON for challenge metadata and configured static flags.
- Existing CTFd API client/pagination helper for any live-board readback.
- Existing range reset/setup scripts for state control.
- Existing Polaris bake preflight note for repo-to-AMI delivery boundaries.

Out-of-tree adapter/tool parameter seam:

Keep scenario-specific parameters at the installed plugin or operator-tool
edges:

- Board inputs: challenge JSON path, optional onboarding JSON path, and optional
  live CTFd base URL for read-only verification.
- Range inputs: `RANGE_DIR`, `COMPOSE_PROJECT_NAME`, `SMOKETESTS_DIR`, and
  runner container names.
- Selection inputs: challenge id/name/category filters for partial reruns.
- Coverage input: a minimal challenge-to-adapter map that identifies the runner
  and executable adapter, not challenge metadata.
- Output inputs: human table/stdout plus optional redacted JSON/JSONL report.

The core extensibility seam is only the fixed entry-point group, versioned
immutable declarations, explicit installed-distribution selection, and
injected runner. Adding another mission, scenario, transport, or optional live
CTFd readback changes the installed plugin/operator tooling, not the core
comparison, discovery, or report contract.

Whole-repo surfaces that remain relevant after extraction:

- `scenario-dev/polaris/tests/run-all-smoketests.sh`
- `scenario-dev/polaris/tests/reset.sh`
- `scenario-dev/polaris/tests/smoketests/*`
- `scenario-dev/polaris/tests/walkthroughs/*`
- `scenario-dev/polaris/build/ctfd-challenges.json`
- `scenario-dev/polaris/build/ctfd-onboarding.json`
- `scenario-dev/polaris/build/verify_flags_baked.py`
- `scenario-dev/polaris/build/test_verify_flags_baked.py`
- `scenario-dev/polaris/README.md`
- `scenario-dev/polaris/design/architecture.md`
- `scenario-dev/polaris/design/shared-constants.md`
- `scripts/ctfd-workshop/common.py`
- `scripts/ctfd-workshop/sync_polaris_ctfd.py`
- `scripts/ctfd-workshop/sync_polaris_ctfd_onboarding.py`
- `scripts/polaris-aws-range/check_range_health.py`
- `docs/architecture/polaris-scenario-bake-preflight-618.md`
- `shifter/shifter_platform/shared/scenario_verification/`
- `shifter/shifter_platform/tests/shared/scenario_verification/`
- `docs/technical/shifter_platform/scenario-verification.md`

The per-scenario coverage map, adapters, topology bindings, and answer material
are deliberately absent from this list because they are no longer core
repository surfaces.

## Gotchas And Anti-Patterns

- The current per-asset smoketests hardcode expected flags and often print flag
  values. They remain infrastructure/operator material and must not be wrapped
  wholesale by the neutral framework. An installed scenario adapter can compare
  the correct sources in memory, but its report must not expose raw values or a
  deterministic value fingerprint.
- `ctfd-challenges.json` currently contains more challenges than the original
  1-38 campaign. Scenario-specific operator tooling must reconcile its declared
  acceptance universe with the selected plugin before the run. A missing adapter
  is a coverage blocker, not `blocked` runtime evidence and not a silent limit
  to the existing asset smoketests. The core framework does not parse the JSON.
- Some existing checks distinguish a human-discovered answer from a
  `FLAG{...}` literal. For example, the Bunker device-id path builds model
  strings while the board stores a static flag. Do not conflate "artifact found
  by the hint path", "answer to submit", and "configured CTFd flag". The
  installed plugin owns that distinction and comparison in memory; its public
  outcome and report expose only a no-value verdict and closed reason code.
- Do not make the harness a CTFd sync repair tool. Verify-after-sync is valuable,
  but mutation belongs in `scripts/ctfd-workshop/*`.
- Do not execute shell snippets scraped from Markdown walkthroughs. Prose is too
  loose to be a command API, and CTFd content can contain strings that should
  never be evaluated by a shell.
- Do not run the full sweep against a participant's active event range. Several
  paths are destructive or stateful, including A5 runaway, Modbus register
  unlocks, and A13 override flow.
- Do not "fix" a failed path by widening Docker networks or bypassing pivots.
  The test must preserve the same segmentation participants experience.
- Do not bury all checks inside one monolithic shell block. Keep per-path logic
  reviewable and reusable so failures identify a challenge, runner, and adapter.
- Do not add a second flag parser, CTFd client, exception hierarchy, or global
  scenario schema when existing scripts already own those concerns.
- Do not archive raw command output as a CI artifact. This is on-demand
  pre-event validation and may reveal flags, credentials, internal hostnames, or
  event-specific operational details.

## Non-Goals

- Tying the scenario-content smoketest to push, pull request, or main deploy CI.
- Replacing `run-all-smoketests.sh`, `reset.sh`, or the per-asset smoketests.
- Replacing the bake-time `verify_flags_baked.py` artifact verifier.
- Creating another generic scenario framework, an ACES SDL runner, or a new
  CTFd schema. The accepted shared plugin seam is the only neutral framework.
- Mutating CTFd challenges, hints, flags, pages, submissions, users, or scores.
- Submitting flags to CTFd from Kali or reviving `flag_submit.sh` as a required
  participant-path dependency.
- Fixing known content bugs, CTFd sync bugs, nginx tuning, range provisioning,
  Guacamole, identity, magic links, or participant invite flows.
