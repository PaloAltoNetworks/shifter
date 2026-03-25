# Audit Rubric

This rubric was derived from the repo's strongest existing patterns, especially the CMS-to-engine range creation flow and the shared-schema/logging setup.

## Rating Scale

- `Implemented`: behavior and structure appear to satisfy the requirement or quality criterion with no material gap found in source review.
- `Partial`: the path exists, but one or more important clauses are missing, fragile, or contradicted by the implementation.
- `Not Implemented`: a required behavior is missing or clearly broken.

## Quality Dimensions

### 1. Requirement Fulfillment

Questions:

- Does the code satisfy the `ACTIVE` Ground Control statement, not just part of it?
- Are sub-clauses implemented, or only the headline behavior?
- Is the participant or organizer surface actually wired end-to-end?

### 2. Boundary Discipline And Architectural Consistency

Questions:

- Does the subsystem follow the same layering discipline as CMS/engine/shared?
- Are cross-domain calls routed through stable seams?
- Are layer rules enforced by repo tooling?

High-quality baseline:

- shared schemas and enums are reused instead of redefined
- service boundaries are narrow and explicit
- layer rules are tool-enforced, not just documented

### 3. Domain Model Clarity

Questions:

- Is there one obvious source of truth for key concepts?
- Do model names, fields, and lifecycle states map cleanly to requirement concepts?
- Are event, participant, challenge, team, range, and notification concepts modeled in ways that reduce ambiguity?

### 4. Service-Layer Correctness

Questions:

- Are invariants enforced where decisions are made?
- Are state transitions validated?
- Are side effects transactional when they need to be?
- Are "logged for now" placeholders standing in for required state?

### 5. Shared Concerns: Schemas, Exceptions, Logging

Questions:

- Does the code use shared schemas and canonical models where available?
- Are domain errors expressed through the local exception hierarchy?
- Does logging capture operationally useful context at the right layer?

### 6. Operability And Automation

Questions:

- Can the feature run reliably without manual timing or hidden deployment knowledge?
- Are background tasks executable, observable, and recoverable?
- Do comments and docs still match the actual deployment/runtime model?

### 7. Testability And Traceability

Questions:

- Is there source-level evidence of tests for the behavior?
- Do Ground Control `TESTS` links exist for the requirement?
- Does the implementation expose clean seams that make testing likely to stay healthy?

## Repo-Specific Standard Used As The Benchmark

The reference pattern for "high quality" in this repo remains the CMS hydration to engine call path:

- domain logic is assembled in a service layer
- shared schema objects are used to cross boundaries
- the orchestration boundary is explicit
- logs and exceptions are centralized

The CTF subsystem was assessed against that standard rather than against a generic Django app bar.
