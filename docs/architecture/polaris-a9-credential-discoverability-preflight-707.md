# Polaris A9 Credential Discoverability Preflight

Issue: GitHub #707, "Polaris: A9 splice-relay SSH credentials are not
discoverable in the range (blocks entire bunker chain)".

This note records the architecture boundary for the future implementation. It is
intentionally not an implementation plan.

## Boundary

The bug is a scenario-content reachability defect: after the flag-19 splice
opens, participants can discover `splice-relay` on the `splice-link` network
but cannot derive the SSH credential from any participant-visible artifact.

Keep these concepts separate:

- A9 authentication material: the credential or key that lets a participant SSH
  to `splice-relay`.
- Participant discovery artifact: a file, banner, service response, or other
  in-range clue reachable only through the intended participant path.
- Operator walkthroughs and lessons notes: validation and provenance only, never
  participant-facing source material.
- Bunker pivot topology: A14 reaches A9 through `splice-link`; only A9 reaches
  Bunker OT (`172.20.50.0/24`).
- Scenario validation: bake-time static artifact checks and range-time
  participant-path checks are different layers and both matter.

The preferred design is to plant a participant-visible A9 access artifact after
the splice is available, and to make the range-time scenario smoketest prove the
access material is discoverable from a participant runner before it proves the
Bunker chain. Password auth may remain if the clue is deliberate and
participant-visible. If key auth is added, the private key is scenario
credential material and must be staged with least exposure, not treated as an
operator secret.

## Architectural Decisions

- The deployed Polaris compose stack under `scenario-dev/polaris/build/` is the
  live event path. Do not implement the fix only in `scenario-dev/polaris/containers/`
  or SDL files unless the build path is updated too.
- Use existing content-delivery ownership:
  - static A9 content belongs in `A9-splice-landing/` and is copied by
    `build/a9/Dockerfile`;
  - static A14 participant home content belongs in `A14-kali/` or `build/a14/`
    Dockerfile copy steps;
  - per-range or post-gate mutations belong in the provisioner splice-watcher
    path documented by `polaris-repo-to-ami-drift-audit.md`.
- Do not make the operator walkthrough, `lessons-4.md`, or CTFd challenge text
  the only source of the credential. The acceptance criterion is in-range
  discoverability from the participant side.
- Preserve the pivot. A14 may authenticate to A9 after the splice, but A14 must
  not gain direct Bunker OT reachability and A9 must remain the sole Bunker
  gateway.
- Extend the existing `scenario_smoketest` harness for this regression. Do not
  create a second smoketest framework, credential inventory schema, CTFd client,
  or reporting format.

## Cross-Cutting Concerns To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Live Polaris delivery path | `docs/architecture/polaris-repo-to-ami-drift-audit.md` | Choose baked content vs provisioner runtime mutation by whether the artifact is static or range/post-gate specific. |
| A9 content | `scenario-dev/polaris/build/A9-splice-landing/*`, `build/a9/Dockerfile`, `design/assets/A9-splice-landing.md` | Keep A9 minimal and Bunker-only. If adding a file or banner, keep it field-relay themed and reachable only through the intended A9 access path. |
| A14 participant content | `scenario-dev/polaris/build/A14-kali/*`, `build/a14/Dockerfile`, `design/assets/A14-kali.md` | If staging a note or private key on Kali, put it under the `kali` user's home with explicit ownership and permissions. |
| Splice topology | `build/docker-compose.yml`, provisioner splice-watcher path, `scripts/polaris-aws-range/range_health.py` | Do not attach A14 to `bunker-ot` or make A9 reachable before the intended splice in production ranges. |
| Network isolation validation | `scenario-dev/polaris/tests/isolation-smoketest.sh`, `scripts/polaris-aws-range/check_range_health.py` | Any credential fix must preserve "A9 is reachable via splice-link; Bunker OT is reachable only from A9." |
| Range-time scenario validation | `scenario-dev/polaris/tests/scenario_smoketest/*` | Add credential-gate coverage as an adapter or reusable helper with redacted output and argv-array execution. |
| Per-asset smoketests | `scenario-dev/polaris/tests/smoketests/A9-smoketest.sh`, `A10`-`A13` smoketests | Reuse existing Bunker runner assumptions. Do not bypass authentication by docker-execing straight into A9 for participant-path checks. |
| Board metadata | `scenario-dev/polaris/build/ctfd-challenges.json` | Challenge ids, names, flags, and prerequisites stay in CTFd JSON, not a new credential schema. |
| Error/report redaction | `scenario_smoketest.compare`, `report`, `runner` | Report match/mismatch and sanitized reasons. Do not print passwords, private keys, flags, tokens, or full SSH command output by default. |
| ADR and workflow gates | `.ground-control.yaml`, `.gc/plan-rules.md`, `scripts/adr_guard/adr_guard.py` | Architecture/doc changes must keep existing guardrails intact. |

## Security Layers

- Auth surface: the design touches OpenSSH on A9 and optional SSH client config
  on A14. Root access is intentional scenario gameplay, but authentication
  material must be reachable only inside the range and only through the intended
  post-splice path.
- Secret-handling surface: `splice2025` or a private SSH key is participant
  scenario material, not an operator credential. It may appear in participant
  artifacts by design, but must not be copied into CTFd admin tokens, Shifter
  platform secrets, Terraform variables, GitHub workflow inputs, process argv,
  or CI artifacts.
- File-permission gate: a staged private key must be owned by `kali:kali` and
  mode `0600`; `.ssh` must be mode `0700`. `authorized_keys` on A9 must be
  mode `0600` under the target account's `.ssh`.
- SSH policy gate: if key auth replaces the password, update `sshd_config`
  deliberately and test both the accepted key path and rejected password path.
  If password auth remains, ensure the password is deliberately discoverable and
  not merely present in a Dockerfile layer.
- Network boundary: A14 reaches A9 over `splice-link`; A9 reaches Bunker OT;
  A14 must still fail direct connects to A10-A13 and A13 brain. The fix must not
  widen Docker networks or relax host firewall semantics to make auth easier.
- OS/process exposure: smoketests and setup scripts must not pass the password
  or private-key contents through shell command strings, process titles, temp
  filenames, or report paths. Use files and subprocess argv arrays where the
  existing Python harness is involved.
- Validation and parser gates: challenge metadata still parses through
  `scenario_smoketest.board`; range execution still goes through
  `scenario_smoketest.runner`. Do not scrape walkthrough Markdown as a command
  source or credential registry.
- Logging and error envelopes: failures may name challenge id, runner, host,
  and sanitized reason. They must not dump raw SSH stderr that includes command
  lines with secret material, key bodies, CTFd responses, or flags.

## Extensibility Seam

Keep the reusable seam at a small "credential gate" check in the
`scenario_smoketest` adapter layer: given a runner, target host, auth method,
and expected participant-visible evidence location, prove that the evidence is
discoverable from the runner and that the derived auth opens the target.

The next likely variation is another gated host credential or a move from
password to key auth. That should require adding a new adapter entry or changing
the auth-method parameter, not editing the core board parser, CTFd sync path,
report format, or every Bunker smoketest.

Whole-repo surfaces in scope for the future implementation:

- `scenario-dev/polaris/build/a9/Dockerfile`
- `scenario-dev/polaris/build/A9-splice-landing/*`
- `scenario-dev/polaris/build/a14/Dockerfile`
- `scenario-dev/polaris/build/A14-kali/*`
- `scenario-dev/polaris/build/docker-compose.yml`
- provisioner splice-watcher/bootstrap code documented in
  `docs/architecture/polaris-repo-to-ami-drift-audit.md`
- `scripts/polaris-aws-range/range_health.py`
- `scripts/polaris-aws-range/check_range_health.py`
- `scenario-dev/polaris/tests/isolation-smoketest.sh`
- `scenario-dev/polaris/tests/smoketests/A9-smoketest.sh`
- `scenario-dev/polaris/tests/smoketests/A10-smoketest.py`
- `scenario-dev/polaris/tests/smoketests/A11-smoketest.py`
- `scenario-dev/polaris/tests/smoketests/A12-smoketest.py`
- `scenario-dev/polaris/tests/smoketests/A13-smoketest.py`
- `scenario-dev/polaris/tests/scenario_smoketest/*`
- `scenario-dev/polaris/tests/walkthroughs/flags-31-36-bunker.md`
- `scenario-dev/polaris/design/assets/A9-splice-landing.md`
- `scenario-dev/polaris/design/assets/A14-kali.md`
- `docs/architecture/polaris-scenario-smoketest-preflight-617.md`
- `docs/architecture/polaris-repo-to-ami-drift-audit.md`

## Gotchas And Anti-Patterns

- Do not confuse "credential exists in a Dockerfile" with "credential is
  discoverable in range." Dockerfile build instructions are not participant
  artifacts.
- Do not use the walkthrough as the fix. It helps operators, but participants
  do not see it during live play.
- Do not solve this by weakening segmentation, pre-attaching A14 to Bunker OT,
  or running Bunker checks directly with `docker exec a9-splice` as the
  participant-path proof.
- Do not add a broad repository-wide grep for every string that looks like a
  password. This issue needs explicit coverage for known chain-gating access
  material, with redaction and topology-aware execution.
- Do not print `splice2025`, private key bodies, or flags in new reports.
  Existing per-asset tests may be noisy; new `scenario_smoketest` coverage
  should preserve its redaction contract.
- Do not introduce a generic secrets manager, new scenario credential DSL, or
  duplicate challenge schema for a single scenario-content bug.
- Do not silently change A9 from password to key auth without updating
  walkthroughs, design notes, and smoke coverage for the chosen auth method.
- Do not implement only in the ACES/SDL container path while the live event
  still deploys `scenario-dev/polaris/build/`.

## Non-Goals

- Implementing the credential artifact, key auth, or smoketest adapter in this
  preflight.
- Rotating operator, cloud, CTFd, Shifter platform, or GitHub credentials.
- Changing CTFd scoring, challenge flags, prerequisites, hints, or submission
  acceptance.
- Reworking the Bunker challenge design, Modbus controllers, A13 brain protocol,
  or flag values.
- Replacing the splice watcher, range bootstrap, compose topology, or network
  isolation model.
- Creating a general scenario credential inventory framework before the existing
  `scenario_smoketest` adapter model proves insufficient.
