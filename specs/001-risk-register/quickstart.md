# Quickstart: Risk Register

**Feature**: 001-risk-register
**Date**: 2025-12-13

## Prerequisites

- Python 3.12+
- PostgreSQL database (existing Shifter DB)
- Existing portal environment configured

## Setup

### 1. Add Dependencies

```bash
cd portal
uv add djangorestframework
```

### 2. Configure Django Settings

Add to `config/settings.py`:

```python
INSTALLED_APPS = [
    # ... existing apps ...
    "rest_framework",
    "risk_register.apps.RiskRegisterConfig",
]

# Django REST Framework settings
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'risk_register.api.authentication.APIKeyAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
}
```

### 3. Add URL Routes

Update `config/urls.py`:

```python
urlpatterns = [
    # ... existing paths ...
    path("risk-register/", include("risk_register.urls")),
    path("api/v1/", include("risk_register.api.urls")),
]
```

### 4. Run Migrations

```bash
cd portal
uv run python manage.py makemigrations risk_register
uv run python manage.py migrate
```

## Verification

### Check API Endpoints

```bash
# List risks (requires authentication)
curl -H "X-API-Key: rr_live_yourkey" http://localhost:8000/api/v1/risks/

# Create a risk
curl -X POST \
  -H "X-API-Key: rr_live_yourkey" \
  -H "Content-Type: application/json" \
  -d '{"title": "Test Risk", "description": "Test", "severity": "medium"}' \
  http://localhost:8000/api/v1/risks/
```

### Access Web UI

1. Log in to portal at http://localhost:8000/
2. Navigate to /risk-register/
3. Verify risk list displays

### Run Tests

```bash
cd portal
uv run pytest tests/risk_register/ -v
```

## Creating an API Key

### Via Django Admin

1. Log in to Django admin at /admin/
2. Navigate to Risk Register > API Keys
3. Click "Add API Key"
4. Enter a name and click Save
5. Copy the displayed key (shown only once)

### Via Python Shell

```bash
cd portal
uv run python manage.py shell
```

```python
from django.contrib.auth import get_user_model
from risk_register.models import APIKey

User = get_user_model()
user = User.objects.get(email='admin@example.com')

key, raw_key = APIKey.create_key(name='AI Agent Key', created_by=user)
print(f"API Key: {raw_key}")  # Save this - shown only once
```

## Common Operations

### Create a Risk (API)

```bash
curl -X POST \
  -H "X-API-Key: rr_live_yourkey" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "SQL Injection in Login Form",
    "description": "User input not sanitized in login endpoint",
    "severity": "critical",
    "stride_categories": ["T", "I"],
    "likelihood_score": 4,
    "impact_score": 5,
    "attack_vector": "POST /api/login with malicious SQL in username field",
    "affected_assets": "Authentication service, User database"
  }' \
  http://localhost:8000/api/v1/risks/
```

### Add a Comment

```bash
curl -X POST \
  -H "X-API-Key: rr_live_yourkey" \
  -H "Content-Type: application/json" \
  -d '{"content": "Mitigation in progress - parameterized queries being implemented"}' \
  http://localhost:8000/api/v1/risks/1/comments/
```

### Update Risk Status

```bash
curl -X PATCH \
  -H "X-API-Key: rr_live_yourkey" \
  -H "Content-Type: application/json" \
  -d '{"status": "mitigating", "mitigation_status": "PR #123 in review"}' \
  http://localhost:8000/api/v1/risks/1/
```

### Close a Risk

```bash
curl -X PATCH \
  -H "X-API-Key: rr_live_yourkey" \
  -H "Content-Type: application/json" \
  -d '{"status": "closed", "resolution_reason": "Fixed in release v2.1.0"}' \
  http://localhost:8000/api/v1/risks/1/
```

## Troubleshooting

### API returns 401 Unauthorized

- Verify API key is active (not revoked or expired)
- Check header name is exactly `X-API-Key`
- Verify key format starts with `rr_live_`

### Migrations fail

- Ensure PostgreSQL ArrayField extension is available
- Check database connection settings in `.env`

### UI templates not found

- Verify `risk_register` is in INSTALLED_APPS
- Run `collectstatic` if in production mode
