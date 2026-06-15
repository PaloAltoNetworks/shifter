"""Pre-event scenario smoketest harness for the Polaris / NORTHSTORM CTF.

An operator-run, range-time verifier (GitHub issue #617). It proves that each
CTFd challenge's canonical participant path produces the value configured for
that challenge against a real staged range, reports per-challenge pass/fail,
and optionally performs a read-only CTFd flag-row readback.

This is NOT a CTFd sync tool, a bake-time artifact verifier, or a CI gate.
See ``docs/architecture/polaris-scenario-smoketest-preflight-617.md``.
"""
