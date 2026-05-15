# Script Context Sanitization Preflight

Issue #700 centralizes experiment script variable sanitization into one
Pydantic-validated context object. The change is a security boundary change, not
a new experiment orchestration abstraction.

## Boundary

- The canonical contract belongs with the existing `cyberscript` template
  variable helpers because both Django and non-Django execution code need the
  same validation semantics. `cms.experiments` may import or re-export it, but
  must not define a second schema.
- The context object owns the sanitized runtime values that are interpolated
  into script execution payloads: scenario instance names, private IPs,
  instance IDs, script S3 keys, local output/script paths, and template
  substitutions.
- `ExperimentOrchestrator` remains the workflow coordinator. It may build
  commands from a validated context, but it must not continue to sanitize names,
  paths, S3 keys, prompts, or template values with local string replacements.
- Uploaded Python script content remains a user-authored script asset. This
  issue does not make arbitrary script content safe; it prevents unsafe
  variable values from being smuggled into the execution layer.
- Do not conflate this object with Django template `Context` or
  `cyberscript.schemas.RangeContext`. If the implementation uses the public name
  `Context`, keep the module name explicit at call sites or choose a clearer
  internal class name such as `ScriptExecutionContext`.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Template variables | `cyberscript.template_vars.extract_variables`, `validate_template`, `resolve_template`, `TemplateString` | Extend or route through this module instead of adding another parser in `cms.experiments`. |
| Pydantic contracts | `cyberscript.schemas.*`, `shared.schemas` re-exports, `cms.experiments.schemas` request DTOs | Keep the reusable execution context Django-free. Keep HTTP form/input DTOs in `cms.experiments.schemas`. |
| Workflow orchestration | `cms.experiments.orchestrator.ExperimentOrchestrator`, `ScriptCommand`, `RunExecutionPlan` | Preserve the run lifecycle and idempotent dispatch behavior; only the command payload shape should change. |
| Task dispatch | `cms.experiments.ecs.start_experiment_task`, `shared.cloud.get_task_runner` | Continue using typed task overrides and JSON payloads. Validate before serialization. |
| Remote execution | `shifter/engine/provisioner/executors/ssm_executor.py` and setup orchestrator patterns | The execution layer should receive already-validated payload data or safe script text; it should not infer sanitization rules. |
| Errors | `cms.experiments.exceptions.ExperimentValidationError`, `ExecutionPlanError`, `shared.exceptions.CMSError` | Reuse existing exception hierarchy. Validation failures should fail plan construction, not dispatch. |
| Logging | `shared.log_sanitize.safe_log`, `config.logging.ECSFormatter` | Escape user-controlled strings in logs and avoid logging full command text, prompt text, payload JSON, or raw validation values. |
| Auth | `shared.auth.threat_research_required`, `cms.experiments.services._validate_user` | Staff/threat-research access is necessary but not sufficient; sanitization must not depend on trusted-user assumptions. |

## Security Layers

- Auth surface: experiment create/start views continue through
  `threat_research_required`, and service calls continue through
  `_validate_user`. The context validation must still run even for authorized
  users.
- Scenario and env-binding shape: scenario instance names come from the
  existing scenario loader/hydrator and `RangeSpec` path. The context should
  accept only names and properties that `TemplateString`/`validate_template`
  already know how to resolve, then normalize the values into a single runtime
  shape.
- Secret handling: current supported template properties are `ip`, `name`, and
  `instance_id`; they are not secrets. Future credential-like variables must be
  modeled with an explicit sensitivity flag and must not be written to argv,
  logs, S3 object keys, local file names, or task env overrides.
- OS/process exposure: `start_experiment_task` passes only operation IDs in the
  container command argv; keep user-controlled context values out of argv where
  possible. If a value must enter SSM shell text, it must come from the
  validated context in its target representation, not from ad hoc f-strings.
- Payload serialization: `EXPERIMENT_PAYLOAD` currently carries JSON in an ECS
  env override. Treat it as a non-secret, sanitized transport. If payloads ever
  carry sensitive context, move them to a provider secret/object reference and
  pass only the reference through the task override.
- Error envelopes: HTTP handlers should continue returning generic messages for
  unexpected errors. Validation errors may identify the bad field/key but must
  not echo raw prompts, command strings, or multiline user-controlled values.
- Remote execution: SSM receives script strings via `Parameters={"commands":
  [script]}`. The implementer should either generate those script strings from
  validated context fields or move to a structured executor payload first; SSM
  must not be the first validation point.

## Extensibility Seam

The required seam is the variable/property registry. Keep allowed properties
and their validators/serializers centralized so the next safe variable
(`hostname`, `username`, or a future non-secret connection detail) can be added
in one place with a target-specific representation such as shell argument, file
path segment, S3 key segment, or display-only value. Secret-bearing variables
need a separate transport classification before they are introduced.

## Gotchas And Anti-Patterns

- Do not add local `re.sub`, `replace`, `shlex.quote`, path slugging, or S3 key
  checks in each command builder as the primary control. Those are target
  encoders behind the context, not competing validators.
- Do not let `instance_name` flow directly into `/tmp/script_<name>.py` or
  `/tmp/output_<name>.log`; use a context-owned safe path segment.
- Do not let `script_s3_key` flow directly into `aws s3 cp` shell text without a
  context-owned S3 key validator.
- Do not preserve the existing comment that shell metacharacters from template
  variables are acceptable because users are staff. Staff-only access is not a
  sanitization strategy.
- Do not duplicate template parsing in JavaScript, views, models, task dispatch,
  or the experiment executor.
- Do not introduce a new exception hierarchy or global error envelope for this
  issue.
- Do not log generated command strings, full ECS payloads, prompts, or raw
  validation errors that include user-controlled newlines.

## Non-Goals

- Redesigning experiment run scheduling, event names, queue topology, artifact
  collection, or range provisioning.
- Making user-uploaded Python scripts safe to execute.
- Replacing SSM, ECS task dispatch, `shared.cloud` task runners, or the existing
  experiment service/view split.
- Adding new template syntax, new variable types, secret variables, or
  cross-range execution features beyond the minimum seam needed for future
  extension.
