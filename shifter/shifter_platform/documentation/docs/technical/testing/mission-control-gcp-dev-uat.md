# Mission Control GCP Dev UAT

This protocol verifies the live GCP deployment from the user and operator point
of view. It is an audit checklist, not a unit test plan.

The machine-readable source of truth for this protocol lives in
`shifter/shifter_platform/tests/uat/mission_control_gcp_dev.yaml`.

## Scope

Included:

- public edge reachability and routing
- Google Identity Platform login surface as exposed through Shifter
- corporate operator login and MFA completion
- Mission Control navigation and read/write surfaces currently exposed in the UI
- range launch and destroy from Mission Control
- terminal and Guacamole access handoff
- CTF participant magic-link entrypoint
- security controls visible from the public surface

Explicitly excluded from pass criteria unless the product contract changes:

- GCP pause and resume parity
- GCP NGFW lifecycle if the current environment does not advertise it as
  supported
- deep scenario-content correctness inside every individual range guest

## Actors

- `public_user`: unauthenticated internet user
- `corporate_user`: allowed `@paloaltonetworks.com` user with MFA
- `bootstrap_admin`: seeded staff and superuser account
- `ctf_participant`: participant entering through a magic link

## Required Inputs

- base URL for the environment
- one valid corporate test account
- one bootstrap admin account
- one valid CTF invite token for a participant fixture
- one known-good scenario and agent combination for range launch
- access to evidence tooling:
  - browser automation with screenshots and network capture
  - `curl`
  - `gcloud`
  - `kubectl`
  - `gh` for workflow evidence when needed

## Evidence Standard

Each executed case should capture enough evidence to support triage without
rerunning the whole suite:

- browser screenshot at the user-visible end state
- final URL and HTTP status
- relevant API response body or DOM assertion
- adjacent control-plane evidence when the defect might be environmental:
  - `kubectl get pods -n shifter-platform`
  - recent logs for the affected pod
  - `gh run view` for the last deploy if rollout drift is suspected

## Execution Order

Run in this order. Do not skip forward after a failure without first collecting
the listed adjacent checks.

### 1. Control Plane Preflight

- confirm the latest `gcp-dev` deploy workflow concluded successfully
- confirm all `shifter-platform` workloads are `Running` and ready
- confirm the TLS certificate and public load balancer are healthy
- confirm the public base URL returns `200`

Adjacent checks if any of the above fail:

- inspect the last `gcp-dev` workflow job breakdown
- inspect portal, Guacamole client, and `guacd` logs
- inspect current ingress and backend health

### 2. Public Edge and Routing

Verify:

- `/` returns `200`
- `/login/` returns `200`
- `/dev-login/` is not public and returns `403`
- `/oidc/authenticate/` redirects to `/login/` on GCP
- `/guacamole/` responds and does not expose a stack trace or raw container error

Adjacent checks:

- Cloud Armor denial logs if a public page returns `403`
- ingress annotations and backend config if the failure is route-specific

### 3. Corporate Identity Flow

Verify:

- the login page loads the provider-backed browser auth shell
- the page exposes corporate email and password entry without posting credentials
  directly to Django
- non-`@paloaltonetworks.com` registration is rejected
- allowed-domain registration path requires email verification before a Shifter
  session is created
- sign-in requires MFA completion before a Shifter session is created
- successful login lands on Mission Control, not a dead-end auth page

Adjacent checks:

- Identity Platform config and blocking-function status
- portal logs around token exchange and session creation

### 4. Bootstrap Admin Access

Verify with the seeded operator:

- authenticated `/mission-control/` returns `200`
- authenticated `/admin/` returns `200`
- the user can reach Mission Control pages without role errors

Adjacent checks:

- Django user flags for `is_staff` and `is_superuser`
- portal logs for permission denials

### 5. Mission Control Shell Audit

Verify the following pages load cleanly after login:

- dashboard `/mission-control/`
- agents `/mission-control/agents/`
- files `/mission-control/files/`
- credentials `/mission-control/credentials/`
- settings `/mission-control/settings/`
- help `/mission-control/help/`
- walkthrough `/mission-control/walkthrough/`

For each page:

- confirm the expected page title is present
- confirm there is no server error banner, broken partial, or authentication loop
- confirm navigation back to dashboard still works

Adjacent checks:

- page-specific API responses in the browser network log
- portal logs for template or permission errors

### 6. Mission Control API Audit

Verify authenticated Mission Control API access for:

- `GET /mission-control/api/agents/`
- `GET /mission-control/api/scenarios/`
- `GET /mission-control/api/range/`
- credentials create/delete API if fixture data is available
- files/scripts list API if fixture data is available

Assertions:

- auth-protected APIs return `200` or an expected empty-state payload
- payload shape matches the page’s expectations
- unauthorized access from a fresh unauthenticated session is rejected cleanly

Adjacent checks:

- browser console and network errors on the associated page
- server logs for serializer or permission faults

### 7. Range Lifecycle Audit

Using a known-good agent and scenario:

- launch a range from the Mission Control dashboard
- verify status transitions are visible and coherent
- verify terminal page becomes reachable when the range is ready
- verify Guacamole SSH or RDP URL retrieval succeeds where the scenario exposes it
- destroy the range from Mission Control
- verify the UI returns to a clean no-range state

Assertions:

- no false-success status transitions
- no orphaned “launching” or “destroying” states after the operation completes
- APIs and UI agree on the final range state

Adjacent checks:

- range API responses
- websocket/terminal logs if status UI stalls
- provisioner logs if launch or destroy fails

### 8. Unsupported Feature Audit

Where a user-visible control exists for an unsupported GCP feature, verify the
behavior is explicit and fail-closed.

Current expectation:

- pause and resume are not parity-complete on GCP and must not silently claim
  success

Adjacent checks:

- the UI state and the API result must agree
- verify the platform does not transition the range to a false terminal state

### 9. CTF Participant Entry Audit

Using a valid invite token:

- open `/ctf/register/?token=<token>`
- verify the participant is authenticated through the magic link flow
- verify the flow lands on Mission Control dashboard rather than the corporate
  login page
- verify the participant can reach the participant-appropriate range/challenge
  surface without corporate operator privileges

Negative cases:

- missing token returns `400`
- invalid token returns `400`
- expired token returns `400`

Adjacent checks:

- participant record and invite token validity
- CTF auth logs

## Exit Criteria

The environment is ready for broader UAT only when:

- all control-plane preflight checks pass
- corporate operator login, MFA, and admin access pass
- Mission Control pages and core APIs pass
- one full launch-to-destroy range cycle passes
- participant magic-link entry is confirmed
- unsupported GCP features fail explicitly rather than pretending to work

If any item fails, attach the captured evidence and open a defect against the
specific surface rather than recording a generic “GCP broken” result.
