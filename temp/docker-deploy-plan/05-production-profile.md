# Phase 5: Production-Mode Compose Profile

## Goal

A single `docker-compose.deploy.yml` (or compose profile) that runs Shifter in production mode with Cognito auth, real AWS, TLS, and all services. Operator provides AWS creds, domain, and Cognito config.

## Current State

- `docker-compose.yml` is dev-focused (DEBUG=true, LocalStack, dev_login)
- Prod config lives in Terraform tfvars and EC2 user_data/entrypoint
- Entrypoint already handles Secrets Manager fetching (but only when `DB_SECRET_ARN` is set)

## Approach

Create a `docker-compose.deploy.yml` override that:
- Sets `DEBUG=False`
- Drops LocalStack (uses real AWS)
- Passes real AWS and Cognito env vars
- Enables TLS via nginx
- Uses production-grade settings

## Changes

### 1. Create docker-compose.deploy.yml

```yaml
# Production deployment override
# Usage: docker compose -f docker-compose.yml -f docker-compose.deploy.yml up -d

services:
  # Remove LocalStack - use real AWS
  localstack:
    profiles: ["dev-only"]

  web:
    build:
      context: .
      dockerfile: Dockerfile.deploy
    environment:
      DJANGO_DEBUG: "false"
      DJANGO_ALLOWED_HOSTS: ${DOMAIN_NAME}
      CSRF_TRUSTED_ORIGINS: https://${DOMAIN_NAME}
      SITE_URL: https://${DOMAIN_NAME}

      # Database (local Postgres, not Secrets Manager)
      DB_HOST: db
      DB_PORT: 5432

      # Real AWS
      AWS_REGION: ${AWS_REGION:-us-east-2}
      AWS_ACCESS_KEY_ID: ${AWS_ACCESS_KEY_ID:-}
      AWS_SECRET_ACCESS_KEY: ${AWS_SECRET_ACCESS_KEY:-}
      AWS_SESSION_TOKEN: ${AWS_SESSION_TOKEN:-}
      AWS_ENDPOINT_URL: ""  # Override LocalStack

      # Cognito OIDC
      OIDC_RP_CLIENT_ID: ${OIDC_RP_CLIENT_ID}
      OIDC_RP_CLIENT_SECRET: ${OIDC_RP_CLIENT_SECRET}
      OIDC_ISSUER_URL: ${OIDC_ISSUER_URL}
      OIDC_AUTH_DOMAIN: ${OIDC_AUTH_DOMAIN}

      # Provisioner
      LOCAL_PROVISIONER: subprocess
      PROVISIONER_PATH: /engine/provisioner

      # Guacamole
      GUACAMOLE_JSON_AUTH_SECRET: ${GUACAMOLE_JSON_AUTH_SECRET}
      GUACAMOLE_BASE_URL: /guacamole
      GUACAMOLE_API_BASE_URL: http://guacamole:8080/guacamole

      # SNS/SQS (real AWS)
      SNS_TOPIC_ARN: ${SNS_TOPIC_ARN}
      SQS_CMS_URL: ${SQS_CMS_URL}
      SQS_ENGINE_URL: ${SQS_ENGINE_URL}
      SQS_MC_URL: ${SQS_MC_URL}

      # Field encryption
      FIELD_ENCRYPTION_KEY: ${FIELD_ENCRYPTION_KEY}

    volumes:
      - provisioner_code:/engine/provisioner:ro
      - staticfiles:/app/staticfiles

  # Workers use real SQS
  worker-cms:
    environment:
      AWS_ENDPOINT_URL: ""
      SQS_CMS_URL: ${SQS_CMS_URL}
      AWS_REGION: ${AWS_REGION:-us-east-2}
      AWS_ACCESS_KEY_ID: ${AWS_ACCESS_KEY_ID:-}
      AWS_SECRET_ACCESS_KEY: ${AWS_SECRET_ACCESS_KEY:-}

  worker-engine:
    environment:
      AWS_ENDPOINT_URL: ""
      SQS_ENGINE_URL: ${SQS_ENGINE_URL}
      AWS_REGION: ${AWS_REGION:-us-east-2}
      AWS_ACCESS_KEY_ID: ${AWS_ACCESS_KEY_ID:-}
      AWS_SECRET_ACCESS_KEY: ${AWS_SECRET_ACCESS_KEY:-}

  worker-mc:
    environment:
      AWS_ENDPOINT_URL: ""
      SQS_MC_URL: ${SQS_MC_URL}
      AWS_REGION: ${AWS_REGION:-us-east-2}
      AWS_ACCESS_KEY_ID: ${AWS_ACCESS_KEY_ID:-}
      AWS_SECRET_ACCESS_KEY: ${AWS_SECRET_ACCESS_KEY:-}

  nginx:
    # nginx config from Phase 4

volumes:
  staticfiles:
  provisioner_code:
```

### 2. Create .env.deploy.example

Template for operators to fill in:

```env
# Domain
DOMAIN_NAME=shifter.example.com

# AWS credentials
AWS_REGION=us-east-2
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=

# Database (local Postgres in the compose stack)
DB_NAME=shifter
DB_USER=postgres
DB_PASSWORD=<generate-strong-password>

# Django
DJANGO_SECRET_KEY=<generate: python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())">
FIELD_ENCRYPTION_KEY=<generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">

# Cognito (from existing Terraform outputs or AWS Console)
OIDC_RP_CLIENT_ID=
OIDC_RP_CLIENT_SECRET=
OIDC_ISSUER_URL=https://cognito-idp.us-east-2.amazonaws.com/<pool-id>
OIDC_AUTH_DOMAIN=https://shifter-portal.auth.us-east-2.amazoncognito.com

# Guacamole
GUACAMOLE_DB_NAME=guacamole
GUACAMOLE_DB_USER=guacamole_admin
GUACAMOLE_DB_PASSWORD=<generate-strong-password>
GUACAMOLE_JSON_AUTH_SECRET=<generate: python -c "import secrets; print(secrets.token_hex(16))">

# SNS/SQS (from existing Terraform outputs)
SNS_TOPIC_ARN=arn:aws:sns:us-east-2:<account>:shifter-range-events
SQS_CMS_URL=https://sqs.us-east-2.amazonaws.com/<account>/shifter-cms
SQS_ENGINE_URL=https://sqs.us-east-2.amazonaws.com/<account>/shifter-engine
SQS_MC_URL=https://sqs.us-east-2.amazonaws.com/<account>/shifter-mc

# TLS (path to cert directory containing cert.pem and key.pem)
TLS_CERT_DIR=./nginx/ssl
```

### 3. Deployment script

**File:** `scripts/deploy.sh`

Quick-start script that:
1. Validates `.env.deploy` exists and has required vars
2. Generates secrets for any blank values
3. Runs `docker compose -f docker-compose.yml -f docker-compose.deploy.yml up -d`
4. Waits for health check
5. Prints access URL

## Security Notes

- DB passwords generated at deploy time, never committed
- AWS creds via env vars (or EC2 instance profile if on EC2)
- Cognito handles auth - no passwords stored in Shifter
- TLS required (self-signed minimum)
- Guacamole JSON auth uses shared secret for token signing
- FIELD_ENCRYPTION_KEY encrypts sensitive DB fields (SCM creds, authcodes)

## Prerequisite AWS Resources

These must exist before deploying (created by existing Terraform or manually):

1. **Cognito User Pool** with app client configured for the deployment domain
2. **SNS Topic + SQS Queues** for range events
3. **VPC + subnets** for range infrastructure (provisioner creates ranges here)
4. **S3 bucket** for Terraform state
5. **SSM parameters** for AMI IDs

Most of this already exists from the current Terraform deployment. The Docker deployment replaces only the portal EC2/ALB/RDS/Redis layer - everything else in AWS stays the same.

## Verification

Full end-to-end:
1. `cp .env.deploy.example .env.deploy` and fill in values
2. `./scripts/deploy.sh`
3. Navigate to `https://<domain>` - Cognito login page appears
4. Log in - Dashboard loads
5. Launch a range - provisioner creates AWS resources
6. RDP into range instance via Guacamole
7. Tear down range
