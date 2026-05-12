# AI experiment execution boundary

Issue: #1186

This document defines the v1 capability policy for experiment runs that invoke
Claude Code from range infrastructure. The matching code-level policy version is
`ai-experiment-execution-v1` in `cyberscript.script_context`.

## Threat model

Experiment execution combines cyber-range targets, uploaded scripts, cloud
credentials, network access, and AI-driven command execution. The primary risks
are prompt injection from scenario machines, unintended credential exposure,
unreviewed expansion of Claude Code privileges, and loss of evidence after an
incident.

The platform treats prompts, scenario content, target machine output, and
generated command output as untrusted. Staff-only access and isolated ranges are
defense in depth; they are not the security boundary.

## Execution scope

Claude Code execution is allowed only from the experiment executor path that
builds commands through `ScriptExecutionContext`. The allowed invocation prefix
is:

```text
claude --dangerously-skip-permissions --output-format stream-json
```

`--dangerously-skip-permissions` is allowed for v1 only because these runs are
launched inside provisioned experiment ranges and must run non-interactively.
Any additional Claude privilege flag, alternate output format, or bypass of
`ScriptExecutionContext` is a security-sensitive change and must update this
document and the policy-versioned tests in the same PR.

## Files and artifacts

Claude receives the prompt through one `-p` argument after template resolution
and POSIX single-quote encoding. It may write its transcript to
`/tmp/claude_output.json`; artifact collection must preserve that output as a
Claude transcript artifact for incident review.

The AI process must not receive repository checkout access, operator workstation
files, portal process memory, or arbitrary platform-side files. Uploaded Python
scripts continue to use the validated S3 key path in `ScriptExecutionContext`;
display names are metadata only and must not become shell path segments.

## Credentials

The AI process must not receive portal credentials, Django settings secrets,
database credentials, Terraform state, GitHub tokens, or broad cloud
control-plane credentials. Runtime access for model invocation belongs to the
pre-provisioned range environment and must remain scoped to the intended model
provider path.

If a future provider requires new credentials for AI execution, the change must
define the credential source, lifetime, artifact redaction rules, and blast
radius before enabling the provider.

## Network egress

Network egress for Claude Code is constrained by the range network and its
provider-level controls. The executor must not add portal-side public egress,
new NAT paths, or broad allowlists to make Claude execution work. New egress for
model access, package installation, callbacks, or artifact upload requires an
explicit architecture update and validation coverage.

## Prompt injection handling

Prompts, templates, and target output are untrusted. Templates may resolve only
through the typed `cyberscript.template_vars` and `ScriptExecutionContext`
validators. Prompt text is passed as data to Claude; it is not a shell script
and must not be concatenated into shell control flow.

Operators reviewing a run must assume target output can contain instructions
that try to override this policy. Such output may influence Claude's reasoning
inside the range, but it does not grant platform credentials, repository files,
or additional network access.

## Audit requirements

Every dispatched experiment command batch includes the policy payload with
`version: ai-experiment-execution-v1`. Claude runs use stream-json output and
tee the transcript to `/tmp/claude_output.json` so collection can preserve the
prompt, tool decisions, command output, and errors needed for incident review.

Regression tests must fail if dispatch omits the policy payload or if the
allowed Claude invocation prefix changes without a deliberate update.
