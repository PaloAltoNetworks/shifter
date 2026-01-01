---
description: Plan work using TDD structure with RED/GREEN/VERIFY for every change
argument-hint: [task description]
---

# Structured Work Planning with TDD

You MUST plan ALL work using this exact structure. Every code change requires the full TDD cycle.

## How to Create Your Plan

If you have concerns during planning, discuss with the user and ask for clarification. Do not make assumptions, clarify.

Before writing your TODO list:

1. **What is the context?** - How does this work fit into the overall system? Ask the user for context if needed.
1. **Understand the scope and blast radius** - What files/functions need to change? What other files will this impact?
3. **Consider expert perspective** - What would a principal engineer say about how to approach this task?
4. **Consider best practices** - Is the concept and task consistent with Martin Fowler's guidance, being pythonic? 
5. **Identify dependencies** - What order must changes happen in?
6. **Break into functions** - One function = one phase with full TDD cycle
7. **Consider skills** - Which skills apply to each phase?
8. **Make verification explicit** - What exact command confirms success?
9. **Plan quality gates** - After each major phase, verify all tests and linting pass

## Required Structure

For EVERY file/function you will modify, you MUST follow this pattern:
```
☐ Phase X.Y PREP: Read [relevant-skill].md to refresh protocol
☐ Phase X.Y RED: Write failing tests for [specific function]
☐ Phase X.Y VERIFY RED: Run [exact pytest command], confirm NotImplementedError
☐ Phase X.Y GREEN: Implement [specific function]
☐ Phase X.Y VERIFY GREEN: Run [exact pytest command], confirm all pass
```

After completing a major phase (all X.Y subphases), you MUST add:
```
☐ Phase X.FINAL VERIFY: Run pre-commit run --all-files, confirm no failures
☐ Phase X.FINAL VERIFY: Run full test suite, confirm no regressions
```

If verification fails, you MUST create fix phases:
```
☐ Phase X.Y+1 PREP: Read tdd-plan.md to refresh protocol
☐ Phase X.Y+1 RED: Write tests for [regression/linter error]
☐ Phase X.Y+1 VERIFY RED: Run [exact test command], confirm failure
☐ Phase X.Y+1 GREEN: Fix [specific issue]
☐ Phase X.Y+1 VERIFY GREEN: Run [exact test command], confirm pass
```

## Planning Rules

1. **PREP before every phase** - Read relevant skill to refresh protocol
2. **RED before GREEN** - Write failing tests first, always
3. **VERIFY after RED** - Confirm tests fail for the right reason (NotImplementedError)
4. **GREEN only after RED** - Implement code to make tests pass
5. **VERIFY after GREEN** - Confirm all tests pass
6. **One function per phase** - Use X.Y numbering (1.1, 1.2, 1.3...)
7. **Explicit test commands** - pytest path::ClassName, not vague "run tests"
8. **Quality gate after major phases** - pre-commit + full test suite
9. **Fix regressions immediately** - Any test failure = new fix phase
10. **Fix all linter errors** - No exceptions, all errors must be resolved
11. **Mark completion** - Change ☐ to ☒ after verification passes and stop to wait for user review.

## Example: Service Layer Implementation
```
☐ Phase 1.1 PREP: Read tdd-plan.md to refresh TDD protocol
☐ Phase 1.1 RED: Write failing tests for list_agents() service
☐ Phase 1.1 VERIFY RED: Run pytest tests/test_services.py::TestListAgents, confirm NotImplementedError
☐ Phase 1.1 GREEN: Implement list_agents() in cms/services.py
☐ Phase 1.1 VERIFY GREEN: Run pytest tests/test_services.py::TestListAgents, confirm all pass

☐ Phase 1.2 PREP: Read tdd-plan.md to refresh TDD protocol
☐ Phase 1.2 RED: Write failing tests for get_agent() service
☐ Phase 1.2 VERIFY RED: Run pytest tests/test_services.py::TestGetAgent, confirm NotImplementedError
☐ Phase 1.2 GREEN: Implement get_agent() in cms/services.py
☐ Phase 1.2 VERIFY GREEN: Run pytest tests/test_services.py::TestGetAgent, confirm all pass

☐ Phase 1.3 PREP: Read tdd-plan.md to refresh TDD protocol
☐ Phase 1.3 RED: Write failing tests for create_agent() service
☐ Phase 1.3 VERIFY RED: Run pytest tests/test_services.py::TestCreateAgent, confirm NotImplementedError
☐ Phase 1.3 GREEN: Implement create_agent() in cms/services.py
☐ Phase 1.3 VERIFY GREEN: Run pytest tests/test_services.py::TestCreateAgent, confirm all pass

☐ Phase 1.FINAL VERIFY: Run pre-commit run --all-files, confirm no failures
☐ Phase 1.FINAL VERIFY: Run pytest tests/test_services.py, confirm no regressions

# If Phase 1.FINAL finds issues:
☐ Phase 1.4 PREP: Read tdd-plan.md to refresh protocol
☐ Phase 1.4 RED: Write test for [specific linter error or regression]
☐ Phase 1.4 VERIFY RED: Run pytest tests/test_services.py::[SpecificTest], confirm failure
☐ Phase 1.4 GREEN: Fix [specific issue]
☐ Phase 1.4 VERIFY GREEN: Run pytest tests/test_services.py::[SpecificTest], confirm pass
☐ Phase 1.4 FINAL VERIFY: Run pytest [entire test suite], confirm no regressions
☐ Phase 1.4 VERIFY: Run pre-commit run --all-files, confirm fixed


```

## Your Task

$ARGUMENTS

First, analyze the scope and dependencies. Then create a TODO list with:
- PREP/RED/VERIFY/GREEN/VERIFY for EVERY function
- Quality gates (pre-commit + full tests) after each major phase
- Plan to fix any regressions or linter errors with new phases