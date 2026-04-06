# ADR Enforcement

This directory holds the machine-readable part of ADR enforcement.

## Files

- `index.yaml`: accepted ADRs and their enforceable rules
- `exceptions.yaml`: time-bounded exceptions to specific rules

The files use JSON syntax with a `.yaml` extension so they stay human-readable while remaining parseable by the standard library.

## Runtime Enforcement

The enforcement entrypoint is:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Optionally pass explicit check names as positional arguments:

```bash
python3 scripts/adr_guard/adr_guard.py layer-imports guardrail-docs --all
```

Current mechanisms:

- `scripts/adr_guard/adr_guard.py`: repo-native policy runner
- `.pre-commit-config.yaml`: local fast checks
- `.github/workflows/_quality.yml`: CI architecture gate
- `.claude/hooks/adr_guard_hook.py`: Claude post-edit validation
- `AGENTS.md`: Codex repo-local policy
- `.importlinter`: Python package-level architecture contracts
- `.tflint.hcl`: Terraform lint configuration. The initial rule set is
  intentionally conservative so it can hard-fail on current signal without
  immediately breaking on unrelated legacy Terraform debt.
- `.gitleaks.toml`: secret scanning configuration

## Adding A Rule

1. Add or update the ADR in `index.yaml`.
2. Implement or wire a check in `scripts/adr_guard/adr_guard.py`.
3. Document the user-visible mechanism in `shifter/shifter_platform/documentation/docs/technical/dev/adr-enforcement.md`.
4. If the rule cannot be enforced yet, add a dated exception in `exceptions.yaml` instead of leaving it implicit.

## Exception Format

Exceptions are explicit and time-bounded:

```json
[
  {
    "rule_id": "ADR-001-R1",
    "owner": "platform",
    "reason": "Temporary migration window",
    "expires_on": "2026-06-30",
    "checks": ["layer-imports"],
    "paths": ["shifter/shifter_platform/ctf/*"]
  }
]
```

Expired exceptions fail `adr_guard`.
