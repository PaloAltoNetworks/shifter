#!/usr/bin/env node

// shifter-ops MCP server composition root.
//
// This file is intentionally thin: it creates the server, loads the
// policy, aggregates every domain tool registrar through the exported
// `registerAllOpsTools(ctx)` seam, connects the stdio transport, and
// installs process signal/cleanup handlers. All tool definitions live
// in `tools/*`, request shapes in `schemas.js`, AWS execution in
// `aws.js`, DB/tunnel lifecycle in `db.js`, range reconciliation in
// `reconcile.js`, and GitHub Actions dispatch in `github-actions.js`.
// See docs/architecture/mcp-ops-modularization-preflight-690.md.
//
// The entrypoint guard at the bottom keeps importing this module
// (e.g. from tool-surface.test.js) side-effect-free: no server, no
// signal handlers, no stdio.

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { installToolSchemaDialectNormalizer } from "../shared/tool-schema-dialect.js";
import {
  loadPolicy,
  profileFromEnv,
  validateApexCoverage,
} from "./policy.js";

import { getProfile, aws, awsText, getInstancePlatform } from "./aws.js";
import {
  withClient,
  startPortalTestTunnel,
  stopPortalTestTunnel,
  cleanup,
} from "./db.js";
import {
  findOrphanedInstances,
  terminateOrphans,
  markOrphansDestroyedInDb,
} from "./reconcile.js";
import {
  triggerAmiWorkflow,
  triggerGceImageWorkflow,
} from "./github-actions.js";

import { registerApproveTool } from "./tools/approve.js";
import { registerLogsTools } from "./tools/logs.js";
import { registerEc2Tools } from "./tools/ec2.js";
import { registerEcsTools } from "./tools/ecs.js";
import { registerSecretsTools } from "./tools/secrets.js";
import { registerSsmTools } from "./tools/ssm.js";
import { registerDatabaseTools } from "./tools/database.js";
import { registerRangesTools } from "./tools/ranges.js";
import { registerImagesTools } from "./tools/images.js";
import { registerS3Tools } from "./tools/s3.js";
import { registerCostTools } from "./tools/cost.js";

const _HERE = path.dirname(fileURLToPath(import.meta.url));
const _REPO_ROOT = path.resolve(_HERE, "..", "..");

// Signal handlers are installed inside `main()` (codex review #1202
// cycle 1 finding 1). Module-level registration would fire on import,
// adding `process.exit(0)`-ing handlers and ops cleanup to any host
// process that merely imported `registerAllOpsTools` (e.g. the
// surface tests, or future tooling) — and that contradicts the
// side-effect-free import contract the seam exists to provide.
function installLiveProcessHandlers() {
  process.on("SIGTERM", () => {
    cleanup();
    process.exit(0);
  });
  process.on("SIGINT", () => {
    cleanup();
    process.exit(0);
  });
  process.on("exit", cleanup);
}

// ==========================================================================
// MCP tool registration seam
//
// Phase 6 (#1202): the descriptor-registration block lives inside the
// exported `registerAllOpsTools(ctx)` so `mcp/ops/tool-surface.test.js`
// can drive registration against a fake server + real `.shifter.yaml`
// without opening stdio. The live `main()` below builds the real
// server, loads policy, calls `registerAllOpsTools`, and connects the
// transport; the entrypoint guard at the bottom ensures importing this
// module from a test is side-effect-free.
//
// Every domain registrar receives the shared `deps` bundle — the
// impure runtime boundary (AWS execution, DB access, tunnel lifecycle,
// reconciliation, workflow dispatch) — so handlers can be exercised in
// focused tests with fakes. Pure pieces (registerTool, schemas,
// ok/err) are imported directly by each registrar.
// ==========================================================================

export function registerAllOpsTools(ctx) {
  const deps = {
    getProfile,
    aws,
    awsText,
    getInstancePlatform,
    withClient,
    startPortalTestTunnel,
    stopPortalTestTunnel,
    findOrphanedInstances,
    terminateOrphans,
    markOrphansDestroyedInDb,
    triggerAmiWorkflow,
    triggerGceImageWorkflow,
  };

  registerApproveTool(ctx);
  registerLogsTools(ctx, deps);
  registerEc2Tools(ctx, deps);
  registerEcsTools(ctx, deps);
  registerSecretsTools(ctx, deps);
  registerSsmTools(ctx, deps);
  registerDatabaseTools(ctx, deps);
  registerRangesTools(ctx, deps);
  registerImagesTools(ctx, deps);
  registerS3Tools(ctx, deps);
  registerCostTools(ctx, deps);

  // Codex review #1201 cycle 1 finding 4: every `apex_operations[*].tool`
  // rule in .shifter.yaml must point at a descriptor that actually
  // reached registerTool. Run this AFTER every registerTool call so a
  // typo in .shifter.yaml fails startup rather than silently disabling
  // the intended apex gate.
  validateApexCoverage(ctx.policy);
}

// ==========================================================================
// Start server
// ==========================================================================

// Phase 5 (#1201): load .shifter.yaml at startup. The active profile
// is `SHIFTER_OPS_PROFILE` (read once here; runtime profile flips
// would be a confused-deputy surface). A missing or malformed
// `.shifter.yaml` throws and the server exits before any tool is
// registered — fail closed is the only correct path.
async function main() {
  installLiveProcessHandlers();
  const server = new McpServer({ name: "shifter-ops", version: "1.0.0" });
  installToolSchemaDialectNormalizer(server);
  const policy = loadPolicy({
    path: path.join(_REPO_ROOT, ".shifter.yaml"),
    profile: profileFromEnv(process.env),
  });
  registerAllOpsTools({ server, policy });
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

// Codex review #1202 cycle 1 finding 2: `process.argv[1]` is undefined
// in valid Node import contexts (e.g. `node --input-type=module -e
// "import('./mcp/ops/index.js')"`, embedded runners, repl programmatic
// loads). Guard the conversion so merely importing this module never
// throws before the caller can use the exported registration seam.
const _entrypointArg = process.argv[1];
if (_entrypointArg && import.meta.url === pathToFileURL(_entrypointArg).href) {
  await main();
}
