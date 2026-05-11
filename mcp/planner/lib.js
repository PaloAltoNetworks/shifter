import {
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
  readdirSync,
  unlinkSync,
} from "node:fs";
import { isAbsolute, join, relative, resolve } from "node:path";
import { homedir } from "node:os";
import { randomUUID } from "node:crypto";

// ---------------------------------------------------------------------------
// Storage
// ---------------------------------------------------------------------------

function plansDir() {
  return process.env.PLANNER_DIR || join(homedir(), ".claude", "plans");
}

function ensureDir() {
  const dir = plansDir();
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
}

function shortId() {
  return randomUUID().slice(0, 8);
}

function now() {
  return new Date().toISOString();
}

const PLAN_ID_PATTERN = /^[a-f0-9]{8}$/;
const PLAN_ID_ERROR = "Invalid plan ID format: must be 8 lowercase hexadecimal characters";

function validatePlanId(id) {
  if (typeof id !== "string" || !PLAN_ID_PATTERN.test(id)) {
    throw new Error(PLAN_ID_ERROR);
  }
  return id;
}

function planPath(id) {
  const validId = validatePlanId(id);
  const base = resolve(plansDir());
  const target = resolve(base, `${validId}.json`);
  const rel = relative(base, target);
  if (rel.startsWith("..") || isAbsolute(rel)) {
    throw new Error(PLAN_ID_ERROR);
  }
  return target;
}

function loadPlan(id) {
  const p = planPath(id);
  if (!existsSync(p)) throw new Error(`Plan not found: ${id}`);
  return JSON.parse(readFileSync(p, "utf-8"));
}

function savePlan(plan) {
  ensureDir();
  plan.updated = now();
  writeFileSync(planPath(plan.id), JSON.stringify(plan, null, 2), "utf-8");
  return plan;
}

// ---------------------------------------------------------------------------
// Current plan
// ---------------------------------------------------------------------------

function currentFile() {
  return join(plansDir(), ".current");
}

function getCurrentPlanId() {
  const f = currentFile();
  if (!existsSync(f)) return null;
  const id = readFileSync(f, "utf-8").trim();
  return id || null;
}

function setCurrentPlanId(id) {
  ensureDir();
  writeFileSync(currentFile(), validatePlanId(id), "utf-8");
}

function clearCurrentPlanId() {
  const f = currentFile();
  if (existsSync(f)) unlinkSync(f);
}

function resolvePlanId(id) {
  if (id) return validatePlanId(id);
  const current = getCurrentPlanId();
  if (!current)
    throw new Error("No plan specified and no current plan set. Create a plan first.");
  return validatePlanId(current);
}

// ---------------------------------------------------------------------------
// Plan CRUD
// ---------------------------------------------------------------------------

function createPlan(name, description = "") {
  const plan = {
    id: shortId(),
    name,
    description,
    created: now(),
    updated: now(),
    phases: [],
  };
  savePlan(plan);
  setCurrentPlanId(plan.id);
  return plan;
}

function listPlans() {
  ensureDir();
  const files = readdirSync(plansDir()).filter((f) => f.endsWith(".json"));
  const currentId = getCurrentPlanId();
  return files.map((f) => {
    const plan = JSON.parse(readFileSync(join(plansDir(), f), "utf-8"));
    const total = plan.phases.reduce((s, p) => s + p.steps.length, 0);
    const done = plan.phases.reduce(
      (s, p) => s + p.steps.filter((st) => st.status === "completed").length,
      0,
    );
    return {
      id: plan.id,
      name: plan.name,
      phases: plan.phases.length,
      total_steps: total,
      completed_steps: done,
      progress: total > 0 ? `${Math.round((done / total) * 100)}%` : "no steps",
      is_current: plan.id === currentId,
      updated: plan.updated,
    };
  });
}

function getPlan(planId) {
  const plan = loadPlan(resolvePlanId(planId));
  const total = plan.phases.reduce((s, p) => s + p.steps.length, 0);
  const done = plan.phases.reduce(
    (s, p) => s + p.steps.filter((st) => st.status === "completed").length,
    0,
  );
  return {
    ...plan,
    progress: {
      total_steps: total,
      completed: done,
      percentage: total > 0 ? Math.round((done / total) * 100) : 0,
    },
    phases: plan.phases.map((phase) => ({
      ...phase,
      progress: {
        total: phase.steps.length,
        completed: phase.steps.filter((st) => st.status === "completed").length,
      },
    })),
  };
}

function deletePlan(planId) {
  const id = resolvePlanId(planId);
  const p = planPath(id);
  if (!existsSync(p)) throw new Error(`Plan not found: ${id}`);
  unlinkSync(p);
  if (getCurrentPlanId() === id) clearCurrentPlanId();
  return { deleted: id };
}

function setCurrentPlan(planId) {
  const id = resolvePlanId(planId);
  loadPlan(id); // verify it exists
  setCurrentPlanId(id);
  return { current: id };
}

// ---------------------------------------------------------------------------
// Phase helpers
// ---------------------------------------------------------------------------

function findPhase(plan, phaseId) {
  const phase = plan.phases.find((p) => p.id === phaseId);
  if (!phase) throw new Error(`Phase not found: ${phaseId}`);
  return phase;
}

function addPhase(planId, name, description = "") {
  const plan = loadPlan(resolvePlanId(planId));
  const phase = {
    id: shortId(),
    name,
    description,
    order: plan.phases.length + 1,
    steps: [],
  };
  plan.phases.push(phase);
  savePlan(plan);
  return phase;
}

function updatePhase(planId, phaseId, updates) {
  const plan = loadPlan(resolvePlanId(planId));
  const phase = findPhase(plan, phaseId);
  if (updates.name !== undefined) phase.name = updates.name;
  if (updates.description !== undefined) phase.description = updates.description;
  savePlan(plan);
  return phase;
}

function removePhase(planId, phaseId) {
  const plan = loadPlan(resolvePlanId(planId));
  const idx = plan.phases.findIndex((p) => p.id === phaseId);
  if (idx === -1) throw new Error(`Phase not found: ${phaseId}`);
  plan.phases.splice(idx, 1);
  plan.phases.forEach((p, i) => {
    p.order = i + 1;
  });
  savePlan(plan);
  return { removed: phaseId };
}

function getPhase(planId, phaseId) {
  const plan = loadPlan(resolvePlanId(planId));
  const phase = findPhase(plan, phaseId);
  return { plan: { id: plan.id, name: plan.name }, phase };
}

// ---------------------------------------------------------------------------
// Step helpers
// ---------------------------------------------------------------------------

function findStep(plan, stepId) {
  for (const phase of plan.phases) {
    const step = phase.steps.find((s) => s.id === stepId);
    if (step) return { phase, step };
  }
  throw new Error(`Step not found: ${stepId}`);
}

function addStep(planId, phaseId, name, description = "", acceptanceCriteria = [], references = []) {
  const plan = loadPlan(resolvePlanId(planId));
  const phase = findPhase(plan, phaseId);
  const step = {
    id: shortId(),
    name,
    description,
    status: "pending",
    notes: "",
    acceptance_criteria: acceptanceCriteria,
    references,
    order: phase.steps.length + 1,
    created: now(),
    updated: now(),
  };
  phase.steps.push(step);
  savePlan(plan);
  return { phase: { id: phase.id, name: phase.name }, step };
}

function updateStep(planId, stepId, updates) {
  const plan = loadPlan(resolvePlanId(planId));
  const { phase, step } = findStep(plan, stepId);
  for (const key of ["name", "description", "status", "notes", "acceptance_criteria", "references"]) {
    if (updates[key] !== undefined) step[key] = updates[key];
  }
  step.updated = now();
  savePlan(plan);
  return { phase: { id: phase.id, name: phase.name }, step };
}

function removeStep(planId, stepId) {
  const plan = loadPlan(resolvePlanId(planId));
  const { phase } = findStep(plan, stepId);
  const idx = phase.steps.findIndex((s) => s.id === stepId);
  phase.steps.splice(idx, 1);
  phase.steps.forEach((s, i) => {
    s.order = i + 1;
  });
  savePlan(plan);
  return { removed: stepId };
}

function getStep(planId, stepId) {
  const plan = loadPlan(resolvePlanId(planId));
  const { phase, step } = findStep(plan, stepId);
  return {
    plan: { id: plan.id, name: plan.name },
    phase: { id: phase.id, name: phase.name },
    step,
  };
}

function addSteps(planId, phaseId, steps) {
  const plan = loadPlan(resolvePlanId(planId));
  const phase = findPhase(plan, phaseId);
  const created = [];
  for (const s of steps) {
    const step = {
      id: shortId(),
      name: s.name,
      description: s.description || "",
      status: "pending",
      notes: "",
      acceptance_criteria: s.acceptance_criteria || [],
      references: s.references || [],
      order: phase.steps.length + 1,
      created: now(),
      updated: now(),
    };
    phase.steps.push(step);
    created.push(step);
  }
  savePlan(plan);
  return { phase: { id: phase.id, name: phase.name }, steps: created };
}

function completeStep(planId, stepId, notes = "") {
  const updates = { status: "completed" };
  if (notes) updates.notes = notes;
  return updateStep(planId, stepId, updates);
}

// ---------------------------------------------------------------------------
// Next step
// ---------------------------------------------------------------------------

function nextStep(planId) {
  const plan = loadPlan(resolvePlanId(planId));

  // Prioritise any step already marked in_progress
  for (const phase of plan.phases) {
    const ip = phase.steps.find((s) => s.status === "in_progress");
    if (ip) {
      return {
        plan: { id: plan.id, name: plan.name },
        phase: { id: phase.id, name: phase.name, order: phase.order },
        step: ip,
      };
    }
  }

  // Otherwise first pending step
  for (const phase of plan.phases) {
    const pending = phase.steps.find((s) => s.status === "pending");
    if (pending) {
      return {
        plan: { id: plan.id, name: plan.name },
        phase: { id: phase.id, name: phase.name, order: phase.order },
        step: pending,
      };
    }
  }

  return { message: "All steps completed!", plan: { id: plan.id, name: plan.name } };
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

function searchPlans(query) {
  ensureDir();
  const q = query.toLowerCase();
  const files = readdirSync(plansDir()).filter((f) => f.endsWith(".json"));
  const results = [];

  for (const f of files) {
    const plan = JSON.parse(readFileSync(join(plansDir(), f), "utf-8"));
    const planText = [plan.name, plan.description].join(" ").toLowerCase();

    if (planText.includes(q)) {
      results.push({
        plan: { id: plan.id, name: plan.name },
        phase: null,
        step: null,
        match_in: "plan",
      });
    }

    for (const phase of plan.phases) {
      const phaseText = [phase.name, phase.description].join(" ").toLowerCase();

      if (phaseText.includes(q)) {
        results.push({
          plan: { id: plan.id, name: plan.name },
          phase: { id: phase.id, name: phase.name },
          step: null,
          match_in: "phase",
        });
      }

      for (const step of phase.steps) {
        const stepText = [
          step.name,
          step.description,
          step.notes,
          ...(step.acceptance_criteria || []),
        ]
          .join(" ")
          .toLowerCase();

        if (stepText.includes(q)) {
          results.push({
            plan: { id: plan.id, name: plan.name },
            phase: { id: phase.id, name: phase.name },
            step: { id: step.id, name: step.name, status: step.status },
            match_in: "step",
          });
        }
      }
    }
  }

  return results;
}

export {
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
};
