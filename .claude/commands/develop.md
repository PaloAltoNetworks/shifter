---
description: Plan work using TDD structure with RED/GREEN/VERIFY for every change
argument-hint: [task description]
---
## Your Task

$ARGUMENTS

First, analyze the scope and dependencies. Carefully analyse the large picture; how does this change fit into the overall architecture? What will it impact up and downstream? What existing pattern are there in the code and data? No code is developed in isolation; all changes must be made in the  context of the overall architecture and dependencies.

When you write unit tests:
- Test the logic, not the implementation
- The most important function of the test is to catch regressions or bugs when they break later
- Write unit tests, not integration tests (unless the user specifically requests integration tests)

The following are important to the user:
- Type hints for all functions
- Unit tests for all functions
- Docstrings
- Extensive debug and other logging
- Defensive programming patterns
- Exception handling
- No gigantic files or functions; keep them small and focused. Use modules, classes, and helper functions to keep code organized.

Common mistakes to avoid:
- Forgetting db grants for new tables, columns, or db consumers
- Function signatures that are not compatible with the existing codebase
- Not checked the django shared/ library for existing patterns and conventions
