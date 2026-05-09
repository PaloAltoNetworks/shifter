FROM python:3.12-slim-trixie

# Install Terraform and Pulumi CLI (pinned versions)
ARG TERRAFORM_VERSION=1.14.3
ARG PULUMI_VERSION=3.142.0

# Single root-stage RUN: install build tools, terraform, pulumi, create the
# non-root runtime user with its writable plugin-cache / pulumi dirs, and
# create the writable Terraform workspace mount point.
# Keeping these in one layer satisfies docker:S7031 (no consecutive RUNs).
# --create-home gives Terraform/Pulumi a writable HOME for plugin caches.
RUN apt-get update && apt-get install -y curl openssh-client unzip && \
    # Install Terraform
    curl -fsSL -o terraform.zip \
      "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" && \
    unzip terraform.zip -d /usr/local/bin && \
    rm terraform.zip && \
    # Install Pulumi (keeping for backward compatibility)
    curl -fsSL -o pulumi.tar.gz \
      "https://github.com/pulumi/pulumi/releases/download/v${PULUMI_VERSION}/pulumi-v${PULUMI_VERSION}-linux-x64.tar.gz" && \
    tar -xzf pulumi.tar.gz -C /usr/local/bin --strip-components=1 && \
    rm pulumi.tar.gz && \
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    # Create non-root user matching shifter_platform's appuser:1000 / appgroup:1000.
    groupadd --gid 1000 appgroup && \
    useradd --uid 1000 --gid appgroup --create-home --shell /bin/bash appuser && \
    mkdir -p /home/appuser/.terraform.d/plugin-cache /home/appuser/.pulumi && \
    chown -R appuser:appgroup /home/appuser && \
    # Pre-create the Terraform workspace mount point. The runtime mounts an
    # emptyDir / Fargate ephemeral volume here; chowning the parent means the
    # mount inherits appuser ownership without needing fsGroup. terraform_base
    # stages module sources under this path per request (issue #1103).
    mkdir -p /var/run/provisioner/workspace && \
    chown -R appuser:appgroup /var/run/provisioner

# Install Python dependencies
WORKDIR /app
COPY requirements.txt requirements-gcp.txt ./
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -r requirements-gcp.txt

# Copy provisioner code as root-owned, immutable image content. The runtime
# user does NOT own /app — Terraform writes go to TERRAFORM_WORKSPACE_DIR
# (terraform_base._stage_workspace) so a process compromise cannot tamper
# with application code at runtime (issue #1103, follow-up to #950).
COPY . .

# Set HOME explicitly so Terraform/Pulumi find the writable cache/config
# directories created above (Docker's USER directive does not adjust HOME).
# TERRAFORM_WORKSPACE_DIR documents the writable workspace mount contract;
# any deployer mounting an emptyDir / Fargate ephemeral volume must mount it
# at this path so terraform_base can stage modules and write
# `.terraform/`, `.terraform.lock.hcl`, and `terraform.tfvars.json`.
ENV HOME=/home/appuser \
    PULUMI_HOME=/home/appuser/.pulumi \
    TF_PLUGIN_CACHE_DIR=/home/appuser/.terraform.d/plugin-cache \
    TERRAFORM_WORKSPACE_DIR=/var/run/provisioner/workspace

# Drop privileges before invoking Terraform/Pulumi. Numeric UID:GID is used
# (instead of `USER appuser`) so Kubernetes admission controllers running with
# `runAsNonRoot: true` can verify the user is non-root without resolving names.
USER 1000:1000

# Entrypoint receives operation as argument
ENTRYPOINT ["python", "main.py"]
