---
id: GEN-003
title: "Operator Automation Command Execution Safety"
status: ACTIVE
type: NON_FUNCTIONAL
priority: MUST
wave: 1
created_at: 2026-05-09T05:11:30.075004Z
updated_at: 2026-05-09T05:11:30.084669Z
---

# GEN-003: Operator Automation Command Execution Safety

## Statement

Operator automation interfaces that execute external commands shall treat tool inputs as untrusted and execute local CLIs via argv arrays or equivalent structured APIs. Local shell-string interpolation shall be forbidden, and regression coverage shall prove shell metacharacter payloads remain literal arguments across supported operator tool paths.

## Rationale

The repo contains MCP servers that run with operator AWS credentials. The command-execution boundary is security-critical and must be represented as a requirement-backed NFR.

## Traceability

- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#457` (Command injection in mcp/ngfw run_command allows shell execution on the portal host)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#459` (Multiple shell injection paths in mcp/ops allow code execution on the MCP host)
- CONSTRAINS → ADR `ADR-010` (MCP servers invoke external CLIs via argv arrays, never shell strings)
- IMPLEMENTS → CODE_FILE `mcp/shared/aws-helpers.js` (Shared AWS CLI argv-array execution helpers)
- DOCUMENTS → DOCUMENTATION `mcp/ops/SECURITY.md` (ops MCP command execution guardrails)
- DOCUMENTS → DOCUMENTATION `mcp/ngfw/SECURITY.md` (ngfw MCP command execution guardrails)
- TESTS → TEST `mcp/ops/lib.test.js` (ops MCP AWS helper tests)
- TESTS → TEST `mcp/ops/spawn-roundtrip.test.js` (argv metacharacter round-trip tests)
- TESTS → TEST `mcp/ngfw/script-execution.test.js` (NGFW remote-shell payload regression tests)
- IMPLEMENTS → CODE_FILE `scripts/adr_guard/_guard/checks/mcp_policy.py` (mcp-no-shell-exec static check (check_mcp_no_shell_exec))
