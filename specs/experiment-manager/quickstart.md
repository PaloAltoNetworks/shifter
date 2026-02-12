# Quickstart: Experiment Manager

**Feature**: Experiment Manager
**Date**: 2026-02-08

## Prerequisites

- Shifter development environment running (Django, PostgreSQL, Redis)
- At least one scenario template available (e.g., `basic`)
- Staff user account

## Development Setup

### 1. Create the Django App

```bash
cd shifter/shifter_platform
python manage.py startapp experiments
```

### 2. Register in Settings

Add `experiments` to `INSTALLED_APPS` in `config/settings.py`, after `cms` (depends on cms models).

Add SQS queue configuration:
```python
SQS_QUEUE_CONFIG = {
    # ... existing queues ...
    "experiments": {
        "url": os.environ.get("SQS_EXPERIMENTS_URL", ""),
        "handler": "experiments.handlers.process_event",
    },
}
```

### 3. Create and Run Migrations

```bash
python manage.py makemigrations experiments
python manage.py migrate
```

### 4. Register Admin

Register models in `experiments/admin.py` for Django admin visibility.

### 5. Wire URL Routes

Add to `config/urls.py`:
```python
path("mission-control/experiments/", include("experiments.urls")),
```

### 6. Add Sidebar Entry

Edit `templates/partials/icon_sidebar.html` — add staff-only experiment link between Risk Register and Docs.

## File Structure

```
shifter/shifter_platform/experiments/
├── __init__.py
├── admin.py              # Django admin registration
├── apps.py               # App config
├── handlers.py           # SQS event handler
├── models.py             # ScriptAsset, Experiment, ExperimentScript,
│                         #   ExperimentRun, RunArtifact, ExperimentArtifact
├── services.py           # Business logic (service layer)
├── orchestrator.py       # ExperimentOrchestrator (execution logic)
├── urls.py               # URL routing
├── views.py              # Staff-only views
├── template_vars.py      # Template variable resolution
├── s3.py                 # S3 operations for scripts and artifacts
├── migrations/
│   └── 0001_initial.py
└── templates/
    └── experiments/
        ├── experiment_list.html
        ├── experiment_create.html
        ├── experiment_detail.html
        ├── script_list.html
        └── script_upload.html
```

## Key Patterns to Follow

### Service Layer
All business logic in `services.py`. Views call services, services call models. Same pattern as `cms/services.py`.

### Staff-Only Access
Use `@staff_member_required` decorator on all views. Same pattern as `risk_register/views.py`.

### File Upload
Follow `cms/assets/` pattern: presigned S3 URL → browser upload → HMAC token verification → create model.

### Event Handling
Follow `cms/handlers.py` pattern: parse SNS envelope, route by event_type, update models, broadcast to WebSocket.

### WebSocket Updates
Follow `mission_control/handlers.py` pattern: use `channel_layer.group_send()` to broadcast to experiment channel group.

## Testing

```bash
# Run experiment app tests
python manage.py test experiments

# Run specific test module
python manage.py test experiments.tests.test_models
python manage.py test experiments.tests.test_services
```

## Verification Checklist

- [ ] `python manage.py migrate` succeeds
- [ ] `python manage.py test experiments` passes
- [ ] Staff user can see Experiments in sidebar
- [ ] Non-staff user cannot see Experiments in sidebar
- [ ] Staff user can upload a Python script
- [ ] Staff user can create an experiment (draft)
- [ ] Experiment detail page loads with run status grid
