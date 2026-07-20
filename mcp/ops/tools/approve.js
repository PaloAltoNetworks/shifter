// Operator-confirmation ("apex") approval tool for the shifter-ops MCP
// server.
//
// The agent reads the token off the operator's terminal (which the
// server printed to stderr just before an apex operation parked) and
// calls this tool with it. Registered as `observability` so every
// profile sees it — without `approve`, no apex op can ever succeed and
// the server degrades to fail-closed-on-every-apex.

import { z } from "zod";
import { registerTool, consumeApexToken } from "../policy.js";

export function registerApproveTool(ctx) {
  registerTool(ctx, {
    name: "approve",
    klass: "observability",
    // Codex review #1201 cycle 2: the apex token must NEVER appear in
    // audit records. `sensitive_args` instructs `_safeOutputArgs` to
    // redact it on the audit/plan-summary surfaces while the handler
    // still receives the raw value to consume the matching pending
    // apex.
    sensitive_args: ["token"],
    description:
      "Release a pending apex operator-confirmation token (printed to server stderr).",
    schema: {
      token: z
        .string()
        .regex(/^[a-f0-9]{32}$/i, "Must be a 32-char hex token from stderr")
        .describe("Apex confirmation token from stderr"),
    },
    handler: async ({ token }) => {
      const ok = consumeApexToken(token);
      return {
        content: [
          {
            type: "text",
            text: ok
              ? "Approved."
              : "Error: token unknown, already consumed, or expired.",
          },
        ],
        ...(ok ? {} : { isError: true }),
      };
    },
  });
}
