---
name: django-testing
description: Run Django tests for the Shifter portal. Use when the user asks to run tests, check if tests pass, test a specific module, or verify code changes with tests.
---

# Django Testing

Run tests for the Shifter Django portal.

## Prerequisites

Always activate the virtual environment and set the TESTING flag:

```bash
cd /home/atomik/src/shifter/portal
source .venv/bin/activate
export TESTING=1
```

## Running Tests

### All Tests
```bash
cd /home/atomik/src/shifter/portal
source .venv/bin/activate
TESTING=1 python -m pytest
```

### Specific Test File
```bash
cd /home/atomik/src/shifter/portal
source .venv/bin/activate
TESTING=1 python -m pytest tests/test_views.py -v
```

### Specific Test Class or Function
```bash
cd /home/atomik/src/shifter/portal
source .venv/bin/activate
TESTING=1 python -m pytest tests/test_views.py::TestDashboard -v
TESTING=1 python -m pytest tests/test_views.py::TestDashboard::test_dashboard_requires_login -v
```

### Run with Coverage
```bash
cd /home/atomik/src/shifter/portal
source .venv/bin/activate
TESTING=1 python -m pytest --cov=mission_control --cov-report=term-missing
```

## Important Notes

- **TESTING=1** is required - it configures Django to use test settings (SQLite, disabled external services)
- **Always activate .venv** - dependencies are installed there
- Tests are in `portal/tests/` directory
- Use `-v` for verbose output
- Use `-x` to stop on first failure
- Use `--tb=short` for shorter tracebacks
- If the venv does not exist in your worktree create it with uv
