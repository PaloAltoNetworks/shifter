# QA & Validation Protocols

Current smoke and validation protocols for a freshly deployed Shifter tenant.
These replace the deprecated v1 QA skeleton (`_deprecated/v1/qa/`), which predates
the four-element architecture (Mission Control, Engine, CMS, Admin).

Each protocol is **hybrid**: automated CLI/DB checks an operator can run with cloud
credentials, plus manual Browser checks for the flows that require an interactive
login (Cognito MFA cannot be driven headlessly).

## Protocols

- [Native CTF Smoke & Validation](native-ctf-smoketest)—the built-in Shifter CTF
  (`ctf/` app): events, challenges, flags, scoring, teams, scoreboard, and
  per-participant range provisioning. Covers the happy-path journey **and** the
  concurrency/integrity/state-machine regression guards.
- [Range Functional Smoke](range-functional-smoke)—the participant journey against
  a known-up example range: an interactive terminal that exchanges real data with a
  range host, and a Guacamole session driven to a client-level connection. Fully
  automated and operator-invoked; it gates no deploy.
- [GCP Event Capacity Gate](../ops/gcp-event-capacity)—30 real participant
  login/bootstrap/RDP display-sync/hold journeys plus fail-closed provider and
  workload health budgets.

!!! note "Scope"
    These protocols validate the **native** Shifter platform. External packs
    keep their scenario acceptance protocols in the owner repository.
