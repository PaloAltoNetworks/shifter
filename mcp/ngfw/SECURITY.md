# shifter-ngfw MCP command execution guardrails

The ngfw MCP server runs with the local operator's AWS credentials and
forwards PAN-OS CLI commands to NGFW appliances by way of an SSM
`AWS-RunShellScript` invocation on a portal jump host. Two shell
boundaries must stay closed:

1. **Local host shell** — every `aws` invocation runs as an argv array
   via `spawn`/`spawnSync`/`execFile`. Shell strings are forbidden.
2. **Remote portal shell** — the SSM `--parameters` JSON containing the
   commands list runs on the portal as `/bin/sh`. The user-supplied
   PAN-OS command must not appear in that script as raw shell text.

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

## Remote SSM payload

The PAN-OS CLI command supplied to `run_command`, `show_system_info`,
and `show_routes` is forwarded to the NGFW via the portal jump host.
The portal command pipeline is built by
`buildNgfwSshCommands({ sshKey, ngfwIp, command })` in `lib.js`:

- The user command is base64-encoded (`command + "\n"` so PAN-OS
  receives a complete line — the appliance is line-oriented and needs
  Enter to execute) into a single argv-safe token. Base64 outputs only
  `[A-Za-z0-9+/=]`, none of which are shell-special inside single
  quotes, so `printf %s '<base64>'` cannot be broken open by
  attacker-controlled bytes.
- The portal decodes the base64 (`base64 -d`) and pipes the resulting
  bytes into `ssh`'s stdin. The portal shell never sees the raw command.
- The SSH private key rides via a single-quoted heredoc terminator
  (`<< 'EOFKEY'`). The single quotes around the terminator suppress
  expansion of `$`, backticks, and `$( )` inside the heredoc body.
- The temporary key path is per-invocation (`/tmp/ngfw-<uuid>.pem`) so
  concurrent MCP calls cannot clobber or delete each other's key
  material. `buildNgfwSshCommands` validates any caller-supplied
  `keyPath` against `^/tmp/ngfw-[A-Za-z0-9._-]+\.pem$` so a future
  caller cannot widen the boundary.
- `ngfwIp` is interpolated into the SSH target argument. It is sourced
  from EC2 `describe-instances` (AWS-controlled), but
  `validateNgfwIp` enforces a strict dotted-quad IPv4 check before
  interpolation as defense in depth.

Single-quote escaping of arbitrary command bytes is explicitly NOT the
remediation strategy. Base64 is the boundary.

## Validation and boundaries

- Reuse the existing Zod schemas in `index.js` for tool input shape and
  the shared helpers in `lib.js` (`buildAwsArgv`, `awsExec`, `awsJson`,
  `awsText`, `buildSsmSendCommandArgs`, `buildNgfwSshCommands`,
  `validateNgfwIp`).
- Validation is defense in depth, not the primary boundary against
  shell injection. Do not rely on a PAN-OS command allowlist to make
  shell-string execution safe; `run_command` is by design an arbitrary
  PAN-OS CLI helper.

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

For the remote-shell boundary, the `buildNgfwSshCommands` tests assert
that the raw PAN-OS command never appears as a substring in the SSM
shell-command list, that arbitrary metacharacter payloads (including
the heredoc terminator itself) round-trip via base64 to PAN-OS, and
that the `printf '...'` segment contains only base64-class characters.

`mcp/ops/spawn-roundtrip.test.js` proves that Node's `spawnSync`
forwards argv elements byte-for-byte for every metacharacter shape
that matters. Because both packages now share `spawnSync` through
`mcp/shared/aws-helpers.js`, that single suite covers the boundary
for every Shifter MCP server.
