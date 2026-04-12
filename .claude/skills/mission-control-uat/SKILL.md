---
name: mission-control-uat
description: Execute the live Mission Control GCP UAT suite from the user point of view using the repo-defined protocol and suite YAML. Use when asked to smoke test, UAT, or audit the deployed GCP Shifter surface without changing code or infrastructure.
---

# Mission Control GCP UAT

This skill is for **test execution**, not implementation.

Use it when the user wants a live verification pass against the deployed GCP
Shifter environment, especially for Mission Control, auth, public edge behavior,
range launch/destroy, and CTF participant entry.

## Source of Truth

Read these first:

- `shifter/shifter_platform/tests/uat/mission_control_gcp_dev.yaml`
- `shifter/shifter_platform/documentation/docs/technical/testing/mission-control-gcp-dev-uat.md`

The YAML file is the execution source of truth. The markdown doc provides
operator guidance and pass/fail framing.

## What This Skill Covers

- control-plane preflight
- public edge and auth routing
- corporate Identity Platform login and MFA
- bootstrap admin access
- Mission Control page audit
- Mission Control API audit
- one launch-to-destroy range lifecycle
- CTF participant magic-link entry

Current exclusions unless the product contract changes:

- GCP pause/resume parity
- GCP NGFW lifecycle unless the live environment explicitly advertises it as supported

## Inputs

First, try to discover inputs from local repo context before treating them as
missing.

Read and mine these sources:

- `temp/k8s/gcp-smoketest-access.md`
- `temp/k8s/gcp-smoketest-checklist.md`
- `/home/atomik/src/shifter/.env`

Use those sources to discover:

- `bootstrap_admin_email`
- `bootstrap_admin_password`
- default environment URL and project details

Input policy:

- `bootstrap_admin_email`: discover locally before asking
- `bootstrap_admin_password`: discover locally before asking
- `bootstrap_admin_totp_seed`: required only if the browser flow needs an
  automated MFA completion and no existing authenticated session is available
- `corporate_user_*`: if separate corporate-user fixtures are not supplied, use
  the bootstrap admin account to execute the corporate auth-path checks
- `launch_scenario_name`: discover from the live Mission Control scenario list
  after login; prefer `Basic Range`, then `AD Attack Lab`, then the first
  clearly supported non-NGFW scenario
- `launch_agent_name`: discover from the live Mission Control agent list after
  login; prefer an obviously active/default agent, otherwise use the first
  available agent and record which one was chosen
- `participant_invite_token`: this is the only positive-flow fixture that should
  normally remain externally supplied; if absent, run the negative magic-link
  cases and mark only the positive magic-link case blocked

Do not invent credentials or tokens. Do discover what is already present.

## Tooling

Prefer:

- Playwright/browser MCP for UI flows, redirects, screenshots, and network capture
- `curl` for direct HTTP checks
- `gh` for deploy/workflow evidence
- `kubectl` and `gcloud` for **read-only** adjacent checks and evidence

## Rules

- Do **not** write code.
- Do **not** edit repo files.
- Do **not** deploy.
- Do **not** mutate infrastructure.
- Do **not** widen scope beyond the suite.
- Do **not** stop at the first failure; run the case’s `adjacent_checks` and collect evidence.
- Do **not** stop before doing discovery and the maximum unblocked subset of the suite.

## Execution Pattern

1. Read the YAML suite and the markdown protocol.
2. Discover locally available inputs from the files listed above.
3. Build an execution plan:
   - full suite for all cases whose prerequisites can be satisfied
   - blocked-only list for cases that truly cannot run
4. Execute the phases in order.
5. For each case, capture:
   - final URL
   - HTTP status
   - screenshot of the final visible state
   - relevant DOM assertion or response body
   - browser network evidence for auth/API failures
6. If a case fails, run the listed `adjacent_checks` before moving on.
7. Treat this as a user-visible audit of the exposed system, not an exploratory poke session.
8. Only stop early if a hard prerequisite for an entire phase cannot be discovered
   or supplied. In that case, execute all still-unblocked phases first and then
   report the remaining blocked cases.

## Default Environment

- base URL: `https://shifter.keplerops.com`
- environment: `gcp-dev`

## Reporting Format

Report in this order:

1. Overall result by phase and case ID
2. Findings first, ordered by severity
3. For each finding:
   - case ID
   - user-visible symptom
   - exact URL or API
   - evidence captured
   - likely failing surface
   - adjacent checks performed and what they showed
4. Blocked cases, each with:
   - case ID
   - exact missing prerequisite
   - whether the prerequisite was attempted via local discovery
5. Compact pass summary for successful cases

If all cases pass, say that the remaining work is UAT expansion or deeper scenario-content validation, not deploy-plumbing remediation.
