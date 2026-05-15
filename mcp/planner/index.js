#!/usr/bin/env node

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import {
  PLAN_ID_PATTERN,
  createPlan,
  listPlans,
  getPlan,
  deletePlan,
  setCurrentPlan,
  addPhase,
  updatePhase,
  removePhase,
  getPhase,
  addStep,
  addSteps,
  updateStep,
  removeStep,
  getStep,
  completeStep,
  nextStep,
  searchPlans,
} from "./lib.js";

function ok(text) {
  return { content: [{ type: "text", text }] };
}

function err(e) {
  return { content: [{ type: "text", text: `Error: ${e.message}` }], isError: true };
}

const STEP_STATUSES = ["pending", "in_progress", "completed", "skipped", "blocked"];
const PLAN_ID_SCHEMA = z
  .string()
  .regex(PLAN_ID_PATTERN, "Plan ID must be 8 lowercase hex characters");

const server = new McpServer({ name: "shifter-planner", version: "1.0.0" });

// ==========================================================================
// Plan tools
// ==========================================================================

server.tool(
  "create_plan",
  "Create a new plan. Automatically becomes the current plan.",
  {
    name: z.string().describe("Plan name"),
    description: z.string().optional().describe("Plan description"),
  },
  async ({ name, description }) => {
    try {
      return ok(JSON.stringify(createPlan(name, description), null, 2));
    } catch (e) {
      return err(e);
    }
  },
);

server.tool(
  "list_plans",
  "List all plans with progress summary.",
  {},
  async () => {
    try {
      const plans = listPlans();
      if (plans.length === 0) return ok("No plans found.");
      return ok(JSON.stringify(plans, null, 2));
    } catch (e) {
      return err(e);
    }
  },
);

server.tool(
  "get_plan",
  "Get full plan details including all phases, steps, and progress. Uses current plan if no plan_id specified.",
  {
    plan_id: PLAN_ID_SCHEMA.optional().describe("Plan ID (defaults to current plan)"),
  },
  async ({ plan_id }) => {
    try {
      return ok(JSON.stringify(getPlan(plan_id), null, 2));
    } catch (e) {
      return err(e);
    }
  },
);

server.tool(
  "set_current_plan",
  "Set which plan is the active/current plan.",
  {
    plan_id: PLAN_ID_SCHEMA.describe("Plan ID to set as current"),
  },
  async ({ plan_id }) => {
    try {
      return ok(JSON.stringify(setCurrentPlan(plan_id), null, 2));
    } catch (e) {
      return err(e);
    }
  },
);

server.tool(
  "delete_plan",
  "Delete a plan permanently.",
  {
    plan_id: PLAN_ID_SCHEMA.describe("Plan ID to delete"),
  },
  async ({ plan_id }) => {
    try {
      return ok(JSON.stringify(deletePlan(plan_id), null, 2));
    } catch (e) {
      return err(e);
    }
  },
);

// ==========================================================================
// Phase tools
// ==========================================================================

server.tool(
  "add_phase",
  "Add a new phase to a plan.",
  {
    name: z.string().describe("Phase name"),
    description: z.string().optional().describe("Phase description"),
    plan_id: PLAN_ID_SCHEMA.optional().describe("Plan ID (defaults to current plan)"),
  },
  async ({ name, description, plan_id }) => {
    try {
      return ok(JSON.stringify(addPhase(plan_id, name, description), null, 2));
    } catch (e) {
      return err(e);
    }
  },
);

server.tool(
  "update_phase",
  "Update a phase's name or description.",
  {
    phase_id: z.string().describe("Phase ID"),
    name: z.string().optional().describe("New phase name"),
    description: z.string().optional().describe("New phase description"),
    plan_id: PLAN_ID_SCHEMA.optional().describe("Plan ID (defaults to current plan)"),
  },
  async ({ phase_id, name, description, plan_id }) => {
    try {
      const updates = {};
      if (name !== undefined) updates.name = name;
      if (description !== undefined) updates.description = description;
      return ok(JSON.stringify(updatePhase(plan_id, phase_id, updates), null, 2));
    } catch (e) {
      return err(e);
    }
  },
);

server.tool(
  "remove_phase",
  "Remove a phase and all its steps from a plan.",
  {
    phase_id: z.string().describe("Phase ID to remove"),
    plan_id: PLAN_ID_SCHEMA.optional().describe("Plan ID (defaults to current plan)"),
  },
  async ({ phase_id, plan_id }) => {
    try {
      return ok(JSON.stringify(removePhase(plan_id, phase_id), null, 2));
    } catch (e) {
      return err(e);
    }
  },
);

server.tool(
  "get_phase",
  "Get a single phase with all its steps.",
  {
    phase_id: z.string().describe("Phase ID"),
    plan_id: PLAN_ID_SCHEMA.optional().describe("Plan ID (defaults to current plan)"),
  },
  async ({ phase_id, plan_id }) => {
    try {
      return ok(JSON.stringify(getPhase(plan_id, phase_id), null, 2));
    } catch (e) {
      return err(e);
    }
  },
);

// ==========================================================================
// Step tools
// ==========================================================================

server.tool(
  "add_step",
  "Add a step to a phase.",
  {
    phase_id: z.string().describe("Phase ID to add the step to"),
    name: z.string().describe("Step name"),
    description: z.string().optional().describe("Step description with details"),
    acceptance_criteria: z
      .array(z.string())
      .optional()
      .describe("List of acceptance criteria"),
    references: z
      .array(z.object({ label: z.string(), url: z.string() }))
      .optional()
      .describe("External references (e.g. GH issues, PRs, docs)"),
    plan_id: PLAN_ID_SCHEMA.optional().describe("Plan ID (defaults to current plan)"),
  },
  async ({ phase_id, name, description, acceptance_criteria, references, plan_id }) => {
    try {
      return ok(
        JSON.stringify(addStep(plan_id, phase_id, name, description, acceptance_criteria, references), null, 2),
      );
    } catch (e) {
      return err(e);
    }
  },
);

server.tool(
  "add_steps",
  "Add multiple steps to a phase in one call. Reduces tool call overhead when populating plans.",
  {
    phase_id: z.string().describe("Phase ID to add steps to"),
    steps: z
      .array(
        z.object({
          name: z.string().describe("Step name"),
          description: z.string().optional().describe("Step description"),
          acceptance_criteria: z.array(z.string()).optional().describe("Acceptance criteria"),
          references: z.array(z.object({ label: z.string(), url: z.string() })).optional().describe("External references"),
        }),
      )
      .describe("Array of steps to create"),
    plan_id: PLAN_ID_SCHEMA.optional().describe("Plan ID (defaults to current plan)"),
  },
  async ({ phase_id, steps, plan_id }) => {
    try {
      return ok(JSON.stringify(addSteps(plan_id, phase_id, steps), null, 2));
    } catch (e) {
      return err(e);
    }
  },
);

server.tool(
  "update_step",
  "Update a step's details. Step is found by ID across all phases.",
  {
    step_id: z.string().describe("Step ID"),
    name: z.string().optional().describe("New step name"),
    description: z.string().optional().describe("New step description"),
    status: z
      .enum(STEP_STATUSES)
      .optional()
      .describe("New status: pending, in_progress, completed, skipped, blocked"),
    notes: z.string().optional().describe("Implementation notes or context"),
    acceptance_criteria: z.array(z.string()).optional().describe("Updated acceptance criteria"),
    references: z.array(z.object({ label: z.string(), url: z.string() })).optional().describe("External references"),
    plan_id: PLAN_ID_SCHEMA.optional().describe("Plan ID (defaults to current plan)"),
  },
  async ({ step_id, name, description, status, notes, acceptance_criteria, references, plan_id }) => {
    try {
      const updates = {};
      if (name !== undefined) updates.name = name;
      if (description !== undefined) updates.description = description;
      if (status !== undefined) updates.status = status;
      if (notes !== undefined) updates.notes = notes;
      if (acceptance_criteria !== undefined) updates.acceptance_criteria = acceptance_criteria;
      if (references !== undefined) updates.references = references;
      return ok(JSON.stringify(updateStep(plan_id, step_id, updates), null, 2));
    } catch (e) {
      return err(e);
    }
  },
);

server.tool(
  "remove_step",
  "Remove a step. Step is found by ID across all phases.",
  {
    step_id: z.string().describe("Step ID to remove"),
    plan_id: PLAN_ID_SCHEMA.optional().describe("Plan ID (defaults to current plan)"),
  },
  async ({ step_id, plan_id }) => {
    try {
      return ok(JSON.stringify(removeStep(plan_id, step_id), null, 2));
    } catch (e) {
      return err(e);
    }
  },
);

server.tool(
  "get_step",
  "Get detailed info for a single step including its plan and phase context.",
  {
    step_id: z.string().describe("Step ID"),
    plan_id: PLAN_ID_SCHEMA.optional().describe("Plan ID (defaults to current plan)"),
  },
  async ({ step_id, plan_id }) => {
    try {
      return ok(JSON.stringify(getStep(plan_id, step_id), null, 2));
    } catch (e) {
      return err(e);
    }
  },
);

server.tool(
  "complete_step",
  "Mark a step as completed, optionally with notes.",
  {
    step_id: z.string().describe("Step ID to complete"),
    notes: z.string().optional().describe("Completion notes"),
    plan_id: PLAN_ID_SCHEMA.optional().describe("Plan ID (defaults to current plan)"),
  },
  async ({ step_id, notes, plan_id }) => {
    try {
      return ok(JSON.stringify(completeStep(plan_id, step_id, notes), null, 2));
    } catch (e) {
      return err(e);
    }
  },
);

// ==========================================================================
// Navigation & search
// ==========================================================================

server.tool(
  "next_step",
  "Get the next actionable step. Prioritises in_progress steps, then first pending. Uses current plan if no plan_id specified.",
  {
    plan_id: PLAN_ID_SCHEMA.optional().describe("Plan ID (defaults to current plan)"),
  },
  async ({ plan_id }) => {
    try {
      return ok(JSON.stringify(nextStep(plan_id), null, 2));
    } catch (e) {
      return err(e);
    }
  },
);

server.tool(
  "search_plans",
  "Search across all plans by keyword. Matches plan names, phase names, step names, descriptions, notes, and acceptance criteria.",
  {
    query: z.string().describe("Search term"),
  },
  async ({ query }) => {
    try {
      const results = searchPlans(query);
      if (results.length === 0) return ok("No matches found.");
      return ok(JSON.stringify(results, null, 2));
    } catch (e) {
      return err(e);
    }
  },
);

// ==========================================================================
// Start
// ==========================================================================

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
