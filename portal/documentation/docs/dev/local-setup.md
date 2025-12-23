# Local Development Setup

Run the Shifter portal locally for development.

## Clone the Repository

```bash
git clone git@github.com:Brad-Edwards/shifter.git
cd shifter
```

## Portal Setup

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

### 3. Local Database

The portal requires PostgreSQL. Use Docker:

```bash
docker run -d \
  --name shifter-postgres \
  -e POSTGRES_USER=shifter \
  -e POSTGRES_PASSWORD=shifter \
  -e POSTGRES_DB=shifter \
  -p 5432:5432 \
  postgres:16
```

### 4. Environment Variables

Create `.env` in the portal directory:

```bash
# Database
DATABASE_URL=postgres://shifter:shifter@localhost:5432/shifter

# Django
DEBUG=True
SECRET_KEY=local-dev-key-not-for-production
ALLOWED_HOSTS=localhost,127.0.0.1

# AWS (for S3, Secrets Manager access)
AWS_REGION=us-east-2
AWS_PROFILE=your-dev-profile  # or use PANW_SHIFTER_DEV_PROFILE

# Cognito (optional for local - use Django admin auth instead)
# COGNITO_DOMAIN=...
# COGNITO_CLIENT_ID=...
# COGNITO_CLIENT_SECRET=...
```

### 5. Run Migrations

```bash
python manage.py migrate
```

### 6. Create Superuser

```bash
python manage.py createsuperuser
```

### 7. Run Development Server

```bash
python manage.py runserver
```

Portal runs at `http://localhost:8000`

## Running Tests

```bash
# All tests
pytest

# With coverage
pytest --cov=mission_control --cov-report=html

# Specific test file
pytest tests/test_views.py -v
```

## Code Quality

```bash
# Linting
ruff check .

# Formatting
ruff format .

# Type checking (if configured)
mypy .
```

## Frontend Assets

The portal uses minimal JavaScript. For any frontend changes:

```bash
# From repo root
npm install
npm run build  # If applicable
```

## Dev Box

The Windows dev-box in `terraform/global/dev-box/` is currently used by Brad Edwards for development. Not part of the standard dev workflow.

## Troubleshooting

### Database Connection Failed
- Ensure PostgreSQL container is running: `docker ps`
- Check port 5432 isn't in use: `lsof -i :5432`

### AWS Credentials
- Verify profile exists: `aws sts get-caller-identity --profile $PANW_SHIFTER_DEV_PROFILE`
- Refresh SSO if needed: `aws sso login --profile $PANW_SHIFTER_DEV_PROFILE`

### Missing Dependencies
- Ensure virtual environment is activated: `which python` should show `.venv/bin/python`
- Reinstall: `pip install -r requirements.txt`
