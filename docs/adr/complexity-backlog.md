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

| Package | File | Function | Complexity at introduction | Tracking issue |
|---|---|---|---|---|
| shifter_platform | `shifter/shifter_platform/cms/services.py` | `list_agents` | 16 | #1142 |
| shifter_platform | `shifter/shifter_platform/ctf/services/participant.py` | `bulk_import_participants` | 16 | #1145 |

`submit_flag` (was complexity 19, tracking #1146) dropped below the
threshold when its participant→challenge availability checks were
factored out into `assert_challenge_available_for_participant` in
`ctf/services/challenge.py` as part of the issue #769 hint hardening.
The `# noqa: C901` was removed in the same PR.

`challenge_detail` (was complexity 17, tracking #1147) dropped below
the threshold in the same PR (#765 / SonarCloud cycle 1) when its
hint-purchase calc, target-instance lookup, and attempt-state logic
were extracted into `_compute_hint_purchase_info`,
`_resolve_target_connection_info`, and `_compute_attempt_state`
helpers in `ctf/views.py`. The `# noqa: C901` was removed.

`initiate_upload` (was complexity 16, tracking #1144) dropped below
the threshold when its input-validation block (user / name / filename
/ file_size checks) was extracted into
`_validate_initiate_upload_inputs` in `cms/services.py`. The
`# noqa: C901` was removed.

`_execute_step` (was complexity 22, tracking #1152) dropped below the
threshold when its per-attempt body was extracted into
`_run_one_attempt` returning an `_AttemptOutcome` discriminated union
(`_AttemptSuccess` / `_AttemptRetry` / `_AttemptFailHard`), with the
PAN-OS post-success block factored into `_classify_successful_attempt`
+ `_handle_panos_poll` and the per-outcome logging into
`_log_step_success` / `_log_step_failure` /
`_log_panos_commit_outcome`. The retry/raise/fallthrough asymmetry is
preserved (transport-error and PAN-OS poll/commit-fail exhaustion
raise `SetupError`; exit-nonzero exhaustion returns a failed
`StepResult`). The `# noqa: C901` was removed. The underlying
architectural smell — PAN-OS specifics leaking into a generic
`Executor`/`SetupPlan` abstraction (e.g., the `SetupStep.poll_for_job`
flag) — remains, and the long-term fix (a `StepValidator` protocol
that pushes PAN-OS knowledge into a dedicated validator) is tracked
on #1152 even though the C901 entry is closed.

Total: 2 functions in `shifter_platform` (1 in `cms/services`, 1 in
`ctf/services`); zero in `provisioner/`. The other six
lint-scoped Python packages (`shifter/packer`, `shifter/installation`,
`scripts/bootstrap`, `scripts/gcp`, `scripts/check_layer_imports`,
`scripts/check_rds_pending_modifications`) ship with zero exemptions
and must stay clean.

The five originally-exempted functions in `cms/services.py::create_range`
and `provisioner/main.py` (`_run_single_instance_setup`,
`run_instance_setup`, `run_range_terraform`,
`_build_range_terraform_variables`) were refactored below the threshold
in the ADR-012 introduction PR (#1141) and their tracking issues
(#1143, #1148–#1151) were closed in the same PR.

New `C901` violations are not added to this list by default. The expectation
is "refactor or the gate fails"; a new exemption requires explicit reviewer
agreement and a same-PR row added here.

Each row has a `tech-debt`-labeled GitHub tracking issue. The refactor PR
deletes the `# noqa: C901` on the `def` line, deletes the row above, and
closes the matching tracking issue in the same change.

The `python-complexity-gate` adr_guard check parses this table cell-by-cell
(no multi-quantifier regex), keying off the leading four columns:
`<package> | <file> | <function> | <complexity>`. Trailing columns
(tracking issue, owner, etc.) are accepted as long as that leading shape
is intact, so the table can grow new columns without code edits to the
parser. The file and function cells must be backtick-fenced; the
complexity cell must be a positive integer.
