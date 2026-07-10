# QA & Validation Protocols

Current smoke and validation protocols for a freshly deployed Shifter tenant.
These replace the deprecated v1 QA skeleton (`_deprecated/v1/qa/`), which predates
the four-element architecture (Mission Control, Engine, CMS, Admin).

Each protocol is **hybrid**: automated CLI/DB checks an operator can run with cloud
credentials, plus manual Browser checks for the flows that require an interactive
login (Cognito MFA cannot be driven headlessly).

## Protocols

- [Native CTF Smoke & Validation](native-ctf-smoketest) — the built-in Shifter CTF
  (`ctf/` app): events, challenges, flags, scoring, teams, scoreboard, and
  per-participant range provisioning. Covers the happy-path journey **and** the
  concurrency/integrity/state-machine regression guards.

!!! note "Scope"
    These protocols validate the **native** Shifter platform. The standalone
    Polaris CTFd and its sync are validated separately and are out of scope here.
