# Pre-event scenario smoketest

Operator-run, on-demand verifier for Polaris / NORTHSTORM scenario content
(GitHub issue #617). It answers one question before an event: does every CTFd
challenge's hint path actually produce the flag the board is configured with?

Scenario-content bugs — a flag in CTFd that is not baked into the range
artifact, a broken hint chain, a `sync_polaris_ctfd.py` re-sync that dropped
flag rows — are invisible to infrastructure health checks and only surface
when participants follow a hint and find nothing. This harness catches them.

It is **not** wired to CI, does not mutate CTFd, and does not replace the
per-asset `run-all-smoketests.sh` sweep or the bake-time `verify_flags_baked.py`
artifact check. See `docs/architecture/polaris-scenario-smoketest-preflight-617.md`.

## What it does

1. **Range sweep.** Derives the challenge universe from `ctfd-challenges.json`.
   For each challenge it runs a registered *adapter* — the canonical
   participant path — from the correct runner container, then compares the
   produced value to the board's configured static flag. A challenge with no
   adapter is reported `uncovered` (counted as a failure, never skipped).
2. **CTFd flag-row readback** (optional, read-only). For every CTFd challenge,
   `GET /challenges/{id}/flags` and asserts the row set is non-empty — the
   `lessons-4.md` checklist item 4 check for the 38/39-unsubmittable regression.

Flag bodies never appear in output: comparisons report a match/mismatch verdict
and reduce any value to a short `sha256:` digest.

## Usage

Run from the range host (it executes commands in runner containers via
`docker exec`):

```sh
# Full range sweep against a staged range
python3 -m scenario_smoketest

# A subset of challenges
python3 -m scenario_smoketest --only 1,2,3

# Range sweep plus the read-only CTFd readback
CTFD_TOKEN=... python3 -m scenario_smoketest --ctfd-url https://ctfd.example

# CTFd readback only
python3 -m scenario_smoketest --skip-range --ctfd-url https://ctfd.example
```

The CTFd admin token is read from the `CTFD_TOKEN` environment variable or a
file passed with `--ctfd-token-file` — never from a command-line argument.
`--json-report PATH` writes a redacted machine-readable report. The process
exits non-zero if any challenge fails, is uncovered, or errors.

## Coverage

Adapters live in `adapters/` and are factored from the existing per-asset
smoketests under `../smoketests/`. Coverage is intentionally incremental: the
report makes every uncovered challenge explicit, so the gap is visible rather
than hidden. Add an adapter by registering a callable for a challenge id — see
`adapters/mission1_osint.py` for the pattern.

## Tests

```sh
python -m pytest scenario-dev/polaris/tests/test_scenario_smoketest.py
```
