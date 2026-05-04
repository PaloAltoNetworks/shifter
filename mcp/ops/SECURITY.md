# shifter-ops MCP command execution guardrails

The ops MCP server runs with the local operator's AWS credentials and can
reach production-facing AWS APIs. Treat every tool argument as untrusted,
including strings that are later embedded in AWS CLI JSON parameters.

## AWS CLI execution

- AWS CLI helpers must execute `aws` with an argument array via
  `spawn`, `spawnSync`, or `execFile`, never by interpolating a shell command
  string.
- Shared AWS helpers should accept structured argv segments, not a pre-joined
  command string. Call sites should pass JSON values as a single argv element
  after `JSON.stringify`.
- Shell escaping is not a remediation strategy for this component. If a value
  must be interpreted by a remote shell through SSM, keep that interpretation
  isolated to the remote command payload and do not route it through the local
  MCP host shell.
- Do not add a second AWS command builder. Extend the shared helpers so all
  CloudWatch, EC2, ECS, SSM, Secrets Manager, RDS, and S3 call sites share the
  same local no-shell behavior.

## Validation and boundaries

- Reuse the existing Zod schemas in `index.js` for tool input shape and the
  shared helpers in `lib.js` for domain-specific constraints such as
  `resolveLogGroup`, `buildInstanceFilters`, `getSsmDocument`,
  `validateManageCommand`, `MAX_S3_READ_SIZE`, and `isBinaryContentType`.
- Validation is defense in depth, not the primary boundary against local shell
  injection. Do not rely on allowlists such as `SafePath` or management-command
  filtering to make shell string execution safe.
- Keep database SQL protections separate from AWS process execution. The
  `FORBIDDEN_PATTERN` and parameterized SQL helpers are SQL safety controls,
  not command-execution controls.

## Regression coverage

Regression tests for AWS command construction should prove that payloads
containing `$()`, backticks, single quotes, double quotes, semicolons, spaces,
and newlines remain literal argv values and are never evaluated by the local
shell. Cover each user-facing tool path that reaches the shared AWS helpers,
especially CloudWatch filters, SSM command parameters, management-command SSM
payloads, and S3 bucket/key inputs.
