# Local Development Setup

Run the Shifter portal locally for development.

## Quick Start

```bash
cd portal
source .venv/bin/activate
TESTING=1 python manage.py runserver
```

Portal runs at `http://localhost:8000`

## Full Setup (First Time)

### 1. Create Python Virtual Environment

```bash
cd portal
python3.12 -m venv .venv
source .venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Run Development Server

```bash
TESTING=1 python manage.py runserver
```

The `TESTING=1` flag uses an in-memory SQLite database, so no database setup is required. Migrations run automatically.

## Running Tests

```bash
# All tests
TESTING=1 python -m pytest

# With coverage
TESTING=1 python -m pytest --cov=mission_control --cov-report=html

# Specific test file
TESTING=1 python -m pytest tests/test_views.py -v
```

## Code Quality

```bash
# Linting
ruff check .

# Formatting
ruff format .
```

## Notes

- `TESTING=1` uses SQLite in-memory, so data doesn't persist between restarts
- Authentication is bypassed in test mode - you can access pages directly
- The `.env` file contains settings for connecting to deployed environments, not local dev

## Troubleshooting

### Missing Dependencies
- Ensure virtual environment is activated: `which python` should show `.venv/bin/python`
- Reinstall: `pip install -r requirements.txt`

### Port Already in Use
- Check what's using port 8000: `lsof -i :8000`
- Use a different port: `TESTING=1 python manage.py runserver 8001`
