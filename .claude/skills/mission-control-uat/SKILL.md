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

Expect these to be available or provided separately:

- `corporate_user_email`
- `corporate_user_password`
- `corporate_user_totp_seed`
- `bootstrap_admin_email`
- `bootstrap_admin_password`
- `bootstrap_admin_totp_seed`
- `participant_invite_token`
- `launch_agent_name`
- `launch_scenario_name`

If required inputs are missing, stop immediately and report exactly which inputs
are missing. Do not invent fixtures.

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

## Execution Pattern

1. Read the YAML suite and the markdown protocol.
2. Execute the phases in order.
3. For each case, capture:
   - final URL
   - HTTP status
   - screenshot of the final visible state
   - relevant DOM assertion or response body
   - browser network evidence for auth/API failures
4. If a case fails, run the listed `adjacent_checks` before moving on.
5. Treat this as a user-visible audit of the exposed system, not an exploratory poke session.

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
4. Compact pass summary for successful cases

If all cases pass, say that the remaining work is UAT expansion or deeper scenario-content validation, not deploy-plumbing remediation.
