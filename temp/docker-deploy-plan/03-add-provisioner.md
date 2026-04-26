# Phase 3: Add Provisioner to Docker Compose

## Current State

- `shifter/engine/provisioner/Dockerfile` exists (Python + Terraform + Pulumi)
- Django already supports `LOCAL_PROVISIONER=subprocess` mode via `engine/ecs.py`
- In prod, provisioner runs as ECS Fargate task triggered by Django
- Local dev can run provisioner as a subprocess if `PROVISIONER_PATH` is set
- The compose file already mounts `../engine/provisioner:/engine/provisioner` into the web container

## Decision: Subprocess vs Sidecar Container

The provisioner is **not a long-running service**. It's invoked per-operation (provision range, teardown range). Two options:

**Option A: Keep subprocess mode (recommended)**
- Django already supports this via `LOCAL_PROVISIONER=subprocess`
- Provisioner code is already volume-mounted into the web container
- Needs Terraform/Pulumi CLI in the web container (or a shared volume)
- Simpler - no inter-container orchestration needed

**Option B: Sidecar container with API**
- Run provisioner as a container with an HTTP API
- Django calls the API instead of ECS
- More isolation but more complexity

**Recommendation: Option A** - subprocess mode is already implemented and tested. The only gap is that the web container's Dockerfile doesn't include Terraform/Pulumi CLIs.

## Changes

### 1. Create a docker-compose production profile

Add a `docker-compose.prod.yml` override that builds a web image with Terraform/Pulumi:

```yaml
services:
  web:
    build:
      context: .
      dockerfile: Dockerfile.deploy
    environment:
      LOCAL_PROVISIONER: subprocess
      PROVISIONER_PATH: /engine/provisioner
```

### 2. Create Dockerfile.deploy

Extends the base Dockerfile to add Terraform CLI:

```dockerfile
FROM shifter-web:latest AS base

USER root
ARG TERRAFORM_VERSION=1.14.3
RUN apt-get update && apt-get install -y --no-install-recommends curl unzip && \
    curl -fsSL -o terraform.zip \
      "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" && \
    unzip terraform.zip -d /usr/local/bin && \
    rm terraform.zip && \
    apt-get purge -y curl unzip && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Install provisioner Python dependencies
COPY ../engine/provisioner/requirements.txt /tmp/prov-requirements.txt
RUN pip install --no-cache-dir -r /tmp/prov-requirements.txt && rm /tmp/prov-requirements.txt

USER appuser
```

Or simpler: multi-stage build that copies Terraform binary from the provisioner image.

### 3. AWS credentials

The web container needs AWS credentials for the provisioner. Options:

- **EC2 instance profile** (if running on EC2) - automatic via IMDSv2
- **Environment variables** - `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`
- **Mounted credentials file** - `~/.aws/credentials` mounted as volume

Add to docker-compose:

```yaml
web:
  environment:
    AWS_REGION: ${AWS_REGION:-us-east-2}
    AWS_ACCESS_KEY_ID: ${AWS_ACCESS_KEY_ID:-}
    AWS_SECRET_ACCESS_KEY: ${AWS_SECRET_ACCESS_KEY:-}
    AWS_SESSION_TOKEN: ${AWS_SESSION_TOKEN:-}
```

### 4. Provisioner state backend

The provisioner uses S3 + DynamoDB for Terraform state. These must exist in the target AWS account. Two options:

- **Use existing state backend** if deploying against the same account
- **Bootstrap new state backend** via a one-time setup script

Add env vars:

```env
# Terraform state (required for provisioner)
TF_STATE_BUCKET=shifter-terraform-state
TF_STATE_REGION=us-east-2
TF_LOCK_TABLE=shifter-terraform-locks
```

## Verification

- `docker compose -f docker-compose.yml -f docker-compose.prod.yml up web`
- Trigger a range provision from the UI
- Provisioner runs as subprocess, creates AWS resources via Terraform
- Range status updates flow through SNS/SQS workers
