# shifter-ngfw MCP command execution guardrails

The ngfw MCP server runs with the local operator's AWS credentials and
only exposes EC2 discovery metadata (`list_ngfws`). It does **not**
execute PAN-OS CLI commands and does not retrieve NGFW SSH keys from
Secrets Manager. The remaining shell boundary that must stay closed:

1. **Local host shell** — every `aws` invocation runs as an argv array
   via `spawn`/`spawnSync`/`execFile`. Shell strings are forbidden.

## AWS CLI execution

- AWS CLI helpers must execute `aws` with an argument array via
  `spawn`/`spawnSync`/`execFile`, never by interpolating a shell command
  string.
- Shared AWS helpers should accept structured argv segments, not a
  pre-joined command string. Call sites should pass JSON values as a
  single argv element after `JSON.stringify`.
- Shell escaping is not a remediation strategy for this component. If a
  value must be interpreted by a remote shell through SSM, keep that
  interpretation isolated to the remote command payload and do not
  route it through the local MCP host shell.
- Do not import `execSync` from `child_process` in this package.
  ADR-010-R1 forbids the import outright; the `mcp-no-shell-exec`
  static check in `scripts/adr_guard/adr_guard.py` enforces it.

## NGFW admin boundary

- Do not add MCP tools that run PAN-OS CLI commands through SSM/SSH.
- Do not retrieve NGFW SSH private keys from Secrets Manager in this
  server.
- If operational firewall administration is needed, use a separate
  break-glass operator workflow with approval and RBAC.

## Validation and boundaries

- Reuse the existing Zod schemas in `index.js` for tool input shape and
  the shared helpers in `lib.js` (`buildAwsArgv`, `awsExec`, `awsJson`,
  `awsText`, `buildSsmSendCommandArgs`, `buildNgfwSshCommands`,
  `validateNgfwIp`).

## Shared helper module at `mcp/shared/aws-helpers.js`

`buildAwsArgv`/`awsExec`/`awsJson`/`awsText`/`buildSsmSendCommandArgs`,
plus `REGION` and `getProfile`, live in `mcp/shared/aws-helpers.js` and
are re-exported by both `mcp/ngfw/lib.js` and `mcp/ops/lib.js`. Each
MCP server keeps its own npm package and `node_modules`; the shared
module imports only `node:`-prefixed built-ins so there is no
cross-package npm dependency.

Because the helper code lives at one site, the argv-array contract
that ADR-010 enforces — TypeError on shell-string args, spawn-only
execution, `--output json` appended last in `awsJson`,
operation-labeled errors (`aws <service> <op>: <stderr>`) — is
guaranteed identical across MCP servers. Any future MCP server in
this repo MUST import from `mcp/shared/aws-helpers.js`; do not
re-implement the helpers locally.

## Regression coverage

Regression tests for AWS command construction prove that payloads
containing `$()`, backticks, single and double quotes, semicolons,
spaces, and newlines remain literal argv values and are never
evaluated by the local shell. Cover each user-facing tool path that
reaches the shared AWS helpers.

`mcp/ngfw/tool-surface.test.js` asserts that the MCP tool surface does
not expose the removed admin execution tools and that the server does
not call Secrets Manager APIs.

`mcp/ops/spawn-roundtrip.test.js` proves that Node's `spawnSync`
forwards argv elements byte-for-byte for every metacharacter shape
that matters. Because both packages now share `spawnSync` through
`mcp/shared/aws-helpers.js`, that single suite covers the boundary
for every Shifter MCP server.
