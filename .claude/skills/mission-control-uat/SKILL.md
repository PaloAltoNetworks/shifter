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
- private authenticated Mission Control access over a localhost/admin path
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

- default environment URL and project details
- private operator access details

Input policy:

- `corporate_user_*`: do not require these for agent-run UAT. Real public
  corporate login and MFA are a human-UAT concern.
- `launch_scenario_name`: discover from the live Mission Control scenario list
  after login; prefer `Basic Range`, then `AD Attack Lab`, then the first
  clearly supported non-NGFW scenario
- `launch_agent_name`: discover from the live Mission Control agent list after
  login; prefer an obviously active/default agent, otherwise use the first
  available agent and record which one was chosen
- `participant_invite_token`: this is the only positive-flow fixture that should
  normally remain externally supplied; if absent, run the negative magic-link
  cases and mark only the positive magic-link case blocked
- `private operator access`: use this for all agent-run authenticated coverage:
  1. `gcloud container clusters get-credentials ...`
  2. `kubectl port-forward -n shifter-platform svc/portal-web 18080:8000`
  3. `http://localhost:18080/dev-login/`
  4. email `uat-admin@example.com`, `user_type=admin`
  5. continue authenticated phases on `http://localhost:18080`

Do not invent credentials or tokens. Do discover what is already present.

## Tooling

Prefer:

- Playwright/browser MCP for UI flows, redirects, screenshots, and network capture
- `curl` for direct HTTP checks
- `gh` for deploy/workflow evidence
- `kubectl` and `gcloud` for **read-only** adjacent checks and evidence
- GitHub issue creation for confirmed failures in the current repo

## Rules

- Do **not** write code.
- Do **not** edit repo files.
- Do **not** deploy.
- Do **not** mutate infrastructure.
- Do **not** widen scope beyond the suite.
- Do **not** stop at the first failure; run the case’s `adjacent_checks` and collect evidence.
- Do **not** stop before doing discovery and the maximum unblocked subset of the suite.
- Do **not** create issues for blocked cases or unconfirmed suspicions.
- Do **not** wait until the end of the run to record confirmed failures.
- Do **not** let public corporate-auth failures block Mission Control/API/range
  testing when the localhost admin path is available.

## Execution Pattern

1. Read the YAML suite and the markdown protocol.
2. Discover locally available inputs from the files listed above.
3. Build an execution plan:
   - full suite for all cases whose prerequisites can be satisfied
   - blocked-only list for cases that truly cannot run
4. Execute the phases in order.
   - Treat public corporate login as a human-UAT finding, not an agent-run
     prerequisite.
   - Use the localhost admin path for authenticated Mission Control/API/range
     testing.
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

## Private Authenticated Access Path

For agent-run authenticated coverage on `gcp-dev`:

1. Get GKE credentials for the live cluster.
2. Port-forward the portal service locally:
   - `kubectl port-forward -n shifter-platform svc/portal-web 18080:8000`
3. Open `http://localhost:18080/dev-login/`
4. Create a local admin session with:
   - email `uat-admin@example.com`
   - `user_type=admin`
5. Continue Mission Control, API, and range tests against
   `http://localhost:18080`.

This is the primary authenticated path for agent-run UAT. It does not count as
a pass for the separate human-UAT public corporate-auth surface.

## Issue Handling

Record confirmed failures immediately while context is fresh.

For each confirmed distinct failing surface:

1. Search existing open GitHub issues in the current repo for the same surface,
   case ID, URL, or symptom.
2. If a matching open issue exists, add the new evidence there instead of
   creating a duplicate.
3. If no matching issue exists, create a new GitHub issue immediately after the
   failure is confirmed and adjacent checks are complete.

Create issues only for:

- confirmed failing cases
- user-visible regressions
- control-plane failures that directly explain a user-visible failing case

Do not create issues for:

- blocked cases caused by missing fixtures
- unsupported features that are already expected to fail and are behaving as specified
- duplicate symptoms already covered by an open issue from the same run

Each created or updated issue must include:

- case ID
- environment (`gcp-dev`)
- actor
- exact URL or API
- user-visible symptom
- expected behavior
- evidence captured
- adjacent checks and what they showed
- likely failing surface

Suggested labels when available:

- `bug`
- `uat`
- `gcp-dev`

The final report must include the issue number for each confirmed failing case
that resulted in a created or updated issue.

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

If all agent-run cases pass, say that the remaining work is human UAT for the
public corporate login/MFA surface plus deeper scenario-content validation.
