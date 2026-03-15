import { describe, it, beforeEach, after } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const testDir = mkdtempSync(join(tmpdir(), "planner-test-"));
process.env.PLANNER_DIR = testDir;

const {
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
} = await import("./lib.js");

after(() => {
  rmSync(testDir, { recursive: true, force: true });
});

function cleanDir() {
  for (const f of readdirSync(testDir)) {
    rmSync(join(testDir, f), { force: true });
  }
}

// -------------------------------------------------------------------------
// Plan CRUD
// -------------------------------------------------------------------------

describe("Plan CRUD", () => {
  beforeEach(() => cleanDir());

  it("creates a plan and sets it as current", () => {
    const plan = createPlan("Test Plan", "A test plan");
    assert.equal(plan.name, "Test Plan");
    assert.equal(plan.description, "A test plan");
    assert.ok(plan.id);
    assert.ok(plan.created);

    const current = getPlan();
    assert.equal(current.id, plan.id);
  });

  it("lists plans with progress", () => {
    createPlan("Plan A");
    createPlan("Plan B");
    const plans = listPlans();
    assert.equal(plans.length, 2);
    assert.ok(plans.some((p) => p.name === "Plan A"));
    assert.ok(plans.some((p) => p.name === "Plan B"));
    // Latest created plan is current
    const current = plans.find((p) => p.is_current);
    assert.equal(current.name, "Plan B");
  });

  it("deletes a plan and clears current", () => {
    const plan = createPlan("To Delete");
    deletePlan(plan.id);
    const plans = listPlans();
    assert.equal(plans.length, 0);
    assert.throws(() => getPlan(), /no current plan/i);
  });

  it("switches current plan", () => {
    const a = createPlan("A");
    createPlan("B");
    setCurrentPlan(a.id);
    const current = getPlan();
    assert.equal(current.id, a.id);
  });

  it("get_plan includes progress stats", () => {
    createPlan("Progress");
    const phase = addPhase(null, "P1");
    const { step: s1 } = addStep(null, phase.id, "S1");
    addStep(null, phase.id, "S2");
    completeStep(null, s1.id);
    const plan = getPlan();
    assert.equal(plan.progress.total_steps, 2);
    assert.equal(plan.progress.completed, 1);
    assert.equal(plan.progress.percentage, 50);
    assert.equal(plan.phases[0].progress.total, 2);
    assert.equal(plan.phases[0].progress.completed, 1);
  });
});

// -------------------------------------------------------------------------
// Phases
// -------------------------------------------------------------------------

describe("Phase operations", () => {
  beforeEach(() => {
    cleanDir();
    createPlan("Phase Test");
  });

  it("adds a phase", () => {
    const phase = addPhase(null, "Phase 1", "First phase");
    assert.equal(phase.name, "Phase 1");
    assert.equal(phase.order, 1);
    assert.ok(phase.id);
  });

  it("retrieves a phase", () => {
    const phase = addPhase(null, "Phase 1");
    const result = getPhase(null, phase.id);
    assert.equal(result.phase.name, "Phase 1");
    assert.equal(result.plan.name, "Phase Test");
  });

  it("updates a phase", () => {
    const phase = addPhase(null, "Old");
    updatePhase(null, phase.id, { name: "New", description: "Updated" });
    const result = getPhase(null, phase.id);
    assert.equal(result.phase.name, "New");
    assert.equal(result.phase.description, "Updated");
  });

  it("removes a phase and reorders", () => {
    addPhase(null, "P1");
    const p2 = addPhase(null, "P2");
    addPhase(null, "P3");
    removePhase(null, p2.id);
    const plan = getPlan();
    assert.equal(plan.phases.length, 2);
    assert.equal(plan.phases[0].name, "P1");
    assert.equal(plan.phases[0].order, 1);
    assert.equal(plan.phases[1].name, "P3");
    assert.equal(plan.phases[1].order, 2);
  });

  it("throws on missing phase", () => {
    assert.throws(() => getPhase(null, "nonexistent"), /Phase not found/);
  });
});

// -------------------------------------------------------------------------
// Steps
// -------------------------------------------------------------------------

describe("Step operations", () => {
  let phaseId;

  beforeEach(() => {
    cleanDir();
    createPlan("Step Test");
    phaseId = addPhase(null, "P1").id;
  });

  it("adds a step with acceptance criteria", () => {
    const { step } = addStep(null, phaseId, "Do thing", "Details", ["It works", "No errors"]);
    assert.equal(step.name, "Do thing");
    assert.equal(step.status, "pending");
    assert.equal(step.description, "Details");
    assert.deepEqual(step.acceptance_criteria, ["It works", "No errors"]);
    assert.equal(step.order, 1);
  });

  it("finds step by ID across phases", () => {
    const p2 = addPhase(null, "P2");
    const { step } = addStep(null, p2.id, "In P2");
    const result = getStep(null, step.id);
    assert.equal(result.step.name, "In P2");
    assert.equal(result.phase.name, "P2");
  });

  it("updates a step", () => {
    const { step } = addStep(null, phaseId, "Original");
    updateStep(null, step.id, {
      name: "Updated",
      status: "in_progress",
      notes: "Working on it",
    });
    const result = getStep(null, step.id);
    assert.equal(result.step.name, "Updated");
    assert.equal(result.step.status, "in_progress");
    assert.equal(result.step.notes, "Working on it");
  });

  it("completes a step with notes", () => {
    const { step } = addStep(null, phaseId, "Finish me");
    completeStep(null, step.id, "All done");
    const result = getStep(null, step.id);
    assert.equal(result.step.status, "completed");
    assert.equal(result.step.notes, "All done");
  });

  it("removes a step and reorders", () => {
    addStep(null, phaseId, "S1");
    const { step: s2 } = addStep(null, phaseId, "S2");
    addStep(null, phaseId, "S3");
    removeStep(null, s2.id);
    const phase = getPhase(null, phaseId);
    assert.equal(phase.phase.steps.length, 2);
    assert.equal(phase.phase.steps[0].name, "S1");
    assert.equal(phase.phase.steps[0].order, 1);
    assert.equal(phase.phase.steps[1].name, "S3");
    assert.equal(phase.phase.steps[1].order, 2);
  });

  it("throws on missing step", () => {
    assert.throws(() => getStep(null, "nonexistent"), /Step not found/);
  });
});

// -------------------------------------------------------------------------
// Batch addSteps
// -------------------------------------------------------------------------

describe("addSteps (batch)", () => {
  let phaseId;

  beforeEach(() => {
    cleanDir();
    createPlan("Batch Test");
    phaseId = addPhase(null, "P1").id;
  });

  it("creates multiple steps in order", () => {
    const result = addSteps(null, phaseId, [
      { name: "Step A", description: "First" },
      { name: "Step B", description: "Second" },
      { name: "Step C" },
    ]);
    assert.equal(result.steps.length, 3);
    assert.equal(result.steps[0].name, "Step A");
    assert.equal(result.steps[0].order, 1);
    assert.equal(result.steps[1].name, "Step B");
    assert.equal(result.steps[1].order, 2);
    assert.equal(result.steps[2].name, "Step C");
    assert.equal(result.steps[2].order, 3);
  });

  it("returns phase context", () => {
    const result = addSteps(null, phaseId, [{ name: "S1" }]);
    assert.equal(result.phase.id, phaseId);
    assert.equal(result.phase.name, "P1");
  });

  it("appends to existing steps", () => {
    addStep(null, phaseId, "Existing");
    const result = addSteps(null, phaseId, [{ name: "New" }]);
    assert.equal(result.steps[0].order, 2);
    const phase = getPhase(null, phaseId);
    assert.equal(phase.phase.steps.length, 2);
  });

  it("supports acceptance criteria", () => {
    const result = addSteps(null, phaseId, [
      { name: "S1", acceptance_criteria: ["Works", "No bugs"] },
    ]);
    assert.deepEqual(result.steps[0].acceptance_criteria, ["Works", "No bugs"]);
  });

  it("supports references", () => {
    const result = addSteps(null, phaseId, [
      { name: "S1", references: [{ label: "Issue", url: "https://github.com/org/repo/issues/1" }] },
    ]);
    assert.equal(result.steps[0].references.length, 1);
    assert.equal(result.steps[0].references[0].label, "Issue");
  });

  it("all steps start as pending", () => {
    const result = addSteps(null, phaseId, [{ name: "A" }, { name: "B" }]);
    for (const step of result.steps) {
      assert.equal(step.status, "pending");
    }
  });
});

// -------------------------------------------------------------------------
// External references
// -------------------------------------------------------------------------

describe("External references", () => {
  let phaseId;

  beforeEach(() => {
    cleanDir();
    createPlan("Refs Test");
    phaseId = addPhase(null, "P1").id;
  });

  it("addStep creates step with references", () => {
    const refs = [{ label: "GH Issue", url: "https://github.com/org/repo/issues/42" }];
    const { step } = addStep(null, phaseId, "With ref", "", [], refs);
    assert.deepEqual(step.references, refs);
  });

  it("addStep defaults references to empty array", () => {
    const { step } = addStep(null, phaseId, "No ref");
    assert.deepEqual(step.references, []);
  });

  it("updateStep can set references", () => {
    const { step } = addStep(null, phaseId, "Update me");
    const refs = [{ label: "PR", url: "https://github.com/org/repo/pull/10" }];
    updateStep(null, step.id, { references: refs });
    const result = getStep(null, step.id);
    assert.deepEqual(result.step.references, refs);
  });

  it("updateStep can clear references", () => {
    const refs = [{ label: "Doc", url: "https://example.com/doc" }];
    const { step } = addStep(null, phaseId, "Clear me", "", [], refs);
    updateStep(null, step.id, { references: [] });
    const result = getStep(null, step.id);
    assert.deepEqual(result.step.references, []);
  });
});

// -------------------------------------------------------------------------
// Next step
// -------------------------------------------------------------------------

describe("nextStep", () => {
  beforeEach(() => cleanDir());

  it("returns first pending step", () => {
    createPlan("Next");
    const phase = addPhase(null, "P1");
    addStep(null, phase.id, "Step 1");
    addStep(null, phase.id, "Step 2");
    const result = nextStep();
    assert.equal(result.step.name, "Step 1");
  });

  it("prioritises in_progress over pending", () => {
    createPlan("Next");
    const phase = addPhase(null, "P1");
    addStep(null, phase.id, "Step 1");
    const { step: s2 } = addStep(null, phase.id, "Step 2");
    updateStep(null, s2.id, { status: "in_progress" });
    const result = nextStep();
    assert.equal(result.step.name, "Step 2");
  });

  it("skips completed steps", () => {
    createPlan("Next");
    const phase = addPhase(null, "P1");
    const { step: s1 } = addStep(null, phase.id, "Step 1");
    addStep(null, phase.id, "Step 2");
    completeStep(null, s1.id);
    const result = nextStep();
    assert.equal(result.step.name, "Step 2");
  });

  it("crosses phase boundaries", () => {
    createPlan("Next");
    const p1 = addPhase(null, "P1");
    const p2 = addPhase(null, "P2");
    const { step: s1 } = addStep(null, p1.id, "P1-S1");
    addStep(null, p2.id, "P2-S1");
    completeStep(null, s1.id);
    const result = nextStep();
    assert.equal(result.step.name, "P2-S1");
    assert.equal(result.phase.name, "P2");
  });

  it("reports all done", () => {
    createPlan("Next");
    const phase = addPhase(null, "P1");
    const { step } = addStep(null, phase.id, "Only");
    completeStep(null, step.id);
    const result = nextStep();
    assert.ok(result.message.includes("completed"));
  });
});

// -------------------------------------------------------------------------
// Search
// -------------------------------------------------------------------------

describe("searchPlans", () => {
  beforeEach(() => cleanDir());

  it("finds matching steps", () => {
    createPlan("Search Test");
    const phase = addPhase(null, "Data Model");
    addStep(null, phase.id, "Create migration for users table");
    addStep(null, phase.id, "Add indexes");
    const results = searchPlans("migration");
    assert.equal(results.length, 1);
    assert.equal(results[0].step.name, "Create migration for users table");
    assert.equal(results[0].match_in, "step");
  });

  it("finds matching phases", () => {
    createPlan("Search Test");
    addPhase(null, "Authentication Phase");
    const results = searchPlans("authentication");
    assert.equal(results.length, 1);
    assert.equal(results[0].match_in, "phase");
    assert.equal(results[0].phase.name, "Authentication Phase");
  });

  it("finds matching plans", () => {
    createPlan("CTF Feature Implementation");
    const results = searchPlans("ctf");
    assert.ok(results.length >= 1);
    assert.ok(results.some((r) => r.match_in === "plan"));
  });

  it("returns empty for no matches", () => {
    createPlan("Something");
    const results = searchPlans("zzzznothing");
    assert.equal(results.length, 0);
  });

  it("searches step notes and acceptance criteria", () => {
    createPlan("Notes Test");
    const phase = addPhase(null, "P1");
    const { step } = addStep(null, phase.id, "Generic step", "", ["Must handle OAuth"]);
    updateStep(null, step.id, { notes: "Uses PKCE flow" });
    assert.equal(searchPlans("OAuth").length, 1);
    assert.equal(searchPlans("PKCE").length, 1);
  });
});
