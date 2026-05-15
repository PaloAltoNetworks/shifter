# shifter-ngfw MCP security boundaries

The `shifter-ngfw` MCP server runs with the local operator's AWS
credentials and exposes a single read-only EC2 discovery tool. It does
**not** execute PAN-OS CLI commands, does **not** open SSH or SSM
sessions to firewall instances, and does **not** read NGFW SSH private
keys or any other material from AWS Secrets Manager. The remaining
process boundary that must stay closed:

1. **Local host shell** — every `aws` invocation runs as an argv array
   via `spawn`/`spawnSync`/`execFile`. Shell strings are forbidden.

## Current tool surface

The MCP server registers exactly one tool through `server.tool(...)`
in `mcp/ngfw/index.js`:

| Tool | Action | AWS calls |
| --- | --- | --- |
| `list_ngfws` | Read-only discovery: returns EC2 instances whose `Name` tag contains `ngfw`, with `InstanceId`, `Name`, `State`, `PrivateIp`, and `KeyName` (the EC2 KeyPair name attached to each instance, not the SSH key material). | `aws ec2 describe-instances` via `mcp/shared/aws-helpers.js`. |

The live tool surface is enforced by
`mcp/ngfw/tool-surface.test.js`. That suite parses
`server.tool("<name>", ...)` registrations out of `index.js` and
asserts the set equals exactly `{"list_ngfws"}`. It also asserts that
this document names each registered tool and back-references the
surface test by file name. A future PR that adds a tool must update
the test's `EXPECTED_TOOLS` set **and** this document in the same
change; either edit on its own fails the test.

`mcp/ngfw/lib.js` exports legacy helpers (e.g. NGFW SSH command-pipeline
builders). They are NOT registered as MCP tools and are not part of the
active capability surface. Only `server.tool(...)` registrations in
`index.js` define what the MCP client can invoke.

## AWS CLI execution

- AWS CLI helpers must execute `aws` with an argument array via
  `spawn`/`spawnSync`/`execFile`, never by interpolating a shell command
  string.
- Shared AWS helpers should accept structured argv segments, not a
  pre-joined command string. Call sites should pass JSON values as a
  single argv element after `JSON.stringify`.
- Shell escaping is not a remediation strategy for this component.
- Do not import `execSync` from `child_process` in this package.
  ADR-010-R1 forbids the import outright; the `mcp-no-shell-exec`
  static check in `scripts/adr_guard/adr_guard.py` enforces it.

## Non-goals (explicit boundary)

- No NGFW administration. The MCP server must not gain tools that
  mutate firewall configuration, push commits, reboot devices, or
  forward arbitrary shell commands to firewall instances.
- No Secrets Manager access. The server must not call
  `secretsmanager:GetSecretValue`, `secretsmanager:ListSecrets`, or any
  other Secrets Manager API. NGFW SSH private keys and any other
  secret material remain out of scope.
- No SSH or SSM sessions from this server. Interactive firewall
  administration belongs in a separate break-glass workflow with
  approval and RBAC, not in a general-purpose MCP surface.
- No new MCP tools without a matching update to
  `mcp/ngfw/tool-surface.test.js` and this document.

## Removed administration tools

The following tools were previously registered by this server and have
been removed. They are listed here only so a reader of the security
doc can see what is **no longer** part of the surface; they are not
active capabilities and must not be re-introduced without a new
threat-model review.

- `run_command` — forwarded an arbitrary PAN-OS CLI command to an NGFW
  instance through the portal jump host over SSH.
- `show_system_info` — wrapped `show system info` against the NGFW.
- `show_routes` — wrapped `show routing route` against the NGFW.

The removal also dropped this server's prior dependence on retrieving
NGFW SSH private keys from AWS Secrets Manager. The
`tool-surface.test.js` regression assertions cover both the absent
tool registrations and the absent Secrets Manager API references
(`secretsmanager`, `get-secret-value`, `list-secrets`).

## Validation and boundaries

- Reuse the existing Zod schemas in `index.js` for tool input shape and
  the shared helpers in `lib.js` (`buildAwsArgv`, `awsExec`, `awsJson`,
  `awsText`).
- `EnvSchema` accepts `dev` or `prod` and selects the local AWS profile
  via `PROFILES`. This is credential selection, not authorization;
  do not treat `env=prod` as a security boundary.

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

`mcp/ngfw/tool-surface.test.js` is the canonical guard for the points
above. It asserts that:

- `index.js` registers exactly the expected set of tools (currently
  just `list_ngfws`).
- This document references the surface test and names every live tool.
- This document does not describe any removed tool as an active
  capability (removed-tool names may appear only under the
  `## Removed administration tools` section above).
- `index.js` never calls Secrets Manager APIs.

`mcp/ops/spawn-roundtrip.test.js` proves that Node's `spawnSync`
forwards argv elements byte-for-byte for every metacharacter shape
that matters. Because both packages share `spawnSync` through
`mcp/shared/aws-helpers.js`, that single suite covers the local-shell
boundary for every Shifter MCP server.
