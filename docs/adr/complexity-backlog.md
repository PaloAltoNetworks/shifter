# Python Complexity Backlog (ADR-012)

This doc tracks the per-function `# noqa: C901` exemptions that were in place
when ADR-012's complexity gate was introduced. Each entry is debt: the function
exceeds the repo-wide McCabe threshold
(`PYTHON_COMPLEXITY_THRESHOLD = 15` in `scripts/adr_guard/adr_guard.py`).

The threshold ratchets down as this list shrinks. Refactoring a function below
the threshold means **(1)** remove the `# noqa: C901` comment on its `def`
line and **(2)** delete its row from the table below in the same PR. Ratchet
edits (lowering the constant) update `PYTHON_COMPLEXITY_THRESHOLD`, every
canonical `pyproject.toml`, and the relevant table rows in one PR.

| Package | File | Function | Complexity at introduction |
|---|---|---|---|
| shifter_platform | `shifter/shifter_platform/cms/services.py` | `list_agents` | 16 |
| shifter_platform | `shifter/shifter_platform/cms/services.py` | `create_range` | 16 |
| shifter_platform | `shifter/shifter_platform/cms/services.py` | `initiate_upload` | 16 |
| shifter_platform | `shifter/shifter_platform/ctf/services/participant.py` | `bulk_import_participants` | 16 |
| shifter_platform | `shifter/shifter_platform/ctf/services/submission.py` | `submit_flag` | 19 |
| shifter_platform | `shifter/shifter_platform/ctf/views.py` | `challenge_detail` | 17 |
| provisioner | `shifter/engine/provisioner/main.py` | `_run_single_instance_setup` | 18 |
| provisioner | `shifter/engine/provisioner/main.py` | `run_instance_setup` | 16 |
| provisioner | `shifter/engine/provisioner/main.py` | `run_range_terraform` | 18 |
| provisioner | `shifter/engine/provisioner/main.py` | `_build_range_terraform_variables` | 16 |
| provisioner | `shifter/engine/provisioner/orchestrators/setup_orchestrator.py` | `_execute_step` | 22 |

Total: 11 functions across 2 packages (6 in `shifter_platform`, 5 in
`provisioner`). The remaining 6 lint-scoped Python packages
(`shifter/packer`, `shifter/installation`, `scripts/bootstrap`, `scripts/gcp`,
`scripts/check_layer_imports`, `scripts/check_rds_pending_modifications`)
ship with zero exemptions and must stay clean.

New `C901` violations are not added to this list by default. The expectation
is "refactor or the gate fails"; a new exemption requires explicit reviewer
agreement and a same-PR row added here.

Per-function GitHub tracking issues for each backlog entry are linked from
issue #1135 (the ADR-012 introduction issue); refactor PRs may close the
matching tracking issue in addition to deleting the row above.
