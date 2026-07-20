// Risk Register tools for the shifter-ops MCP server.
//
// The tool descriptors are split across ./risk/* submodules by concern
// (queries, mutations, comments) to keep each file and function within
// the length budgets. This module is the thin registrar: it imports the
// pure descriptor factories and registers them in a fixed order.

import { registerTool } from "../policy.js";
import {
  listRisksTool,
  getRiskTool,
  riskDashboardTool,
  riskMatrixTool,
  riskAuditLogTool,
} from "./risk/queries.js";
import {
  createRiskTool,
  updateRiskTool,
  deleteRiskTool,
  restoreRiskTool,
} from "./risk/mutations.js";
import {
  addRiskCommentTool,
  deleteRiskCommentTool,
} from "./risk/comments.js";

export function registerRiskTools(ctx, deps) {
  registerTool(ctx, listRisksTool(deps));
  registerTool(ctx, getRiskTool(deps));
  registerTool(ctx, createRiskTool(deps));
  registerTool(ctx, updateRiskTool(deps));
  registerTool(ctx, deleteRiskTool(deps));
  registerTool(ctx, restoreRiskTool(deps));
  registerTool(ctx, addRiskCommentTool(deps));
  registerTool(ctx, deleteRiskCommentTool(deps));
  registerTool(ctx, riskDashboardTool(deps));
  registerTool(ctx, riskMatrixTool(deps));
  registerTool(ctx, riskAuditLogTool(deps));
}
