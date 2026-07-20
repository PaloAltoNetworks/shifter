# base image: python:3.12-slim-trixie
FROM python@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf

# Image metadata. `maintainer` is the label SonarCloud docker:S7028 requires;
# the org.opencontainers.image.* labels are the modern OCI equivalents.
LABEL maintainer="Shifter maintainers" \
      org.opencontainers.image.title="shifter-provisioner" \
      org.opencontainers.image.description="Shifter engine provisioner (Terraform/Pulumi range provisioning)" \
      org.opencontainers.image.source="https://github.com/Brad-Edwards/shifter" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.authors="Shifter maintainers"

# Install Terraform and Pulumi CLI (pinned versions)
ARG TERRAFORM_VERSION=1.14.3
ARG PULUMI_VERSION=3.142.0

# Single root-stage RUN: install build tools, terraform, pulumi, create the
# non-root runtime user with its writable plugin-cache / pulumi dirs, and
# create the writable Terraform workspace mount point.
# Keeping these in one layer satisfies docker:S7031 (no consecutive RUNs).
# --create-home gives Terraform/Pulumi a writable HOME for plugin caches.
RUN apt-get update && apt-get install -y curl openssh-client unzip && \
    # Install Terraform, integrity-verified against HashiCorp's published
    # SHA256SUMS before extraction (ADR-037-R3). The archive is saved under the
    # exact name the checksum manifest references so `sha256sum -c` matches.
    curl --proto '=https' --retry 5 --retry-delay 3 --retry-all-errors --connect-timeout 20 -fsSL \
      -o "terraform_${TERRAFORM_VERSION}_linux_amd64.zip" \
      "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" && \
    curl --proto '=https' --retry 5 --retry-delay 3 --retry-all-errors --connect-timeout 20 -fsSL \
      -o terraform_SHA256SUMS \
      "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_SHA256SUMS" && \
    grep "terraform_${TERRAFORM_VERSION}_linux_amd64.zip" terraform_SHA256SUMS | sha256sum -c - && \
    unzip "terraform_${TERRAFORM_VERSION}_linux_amd64.zip" -d /usr/local/bin && \
    rm "terraform_${TERRAFORM_VERSION}_linux_amd64.zip" terraform_SHA256SUMS && \
    # Install Pulumi, integrity-verified against the published checksums file
    # before extraction (ADR-037-R3).
    curl --proto '=https' --retry 5 --retry-delay 3 --retry-all-errors --connect-timeout 20 -fsSL \
      -o "pulumi-v${PULUMI_VERSION}-linux-x64.tar.gz" \
      "https://github.com/pulumi/pulumi/releases/download/v${PULUMI_VERSION}/pulumi-v${PULUMI_VERSION}-linux-x64.tar.gz" && \
    curl --proto '=https' --retry 5 --retry-delay 3 --retry-all-errors --connect-timeout 20 -fsSL \
      -o pulumi_checksums.txt \
      "https://github.com/pulumi/pulumi/releases/download/v${PULUMI_VERSION}/pulumi-${PULUMI_VERSION}-checksums.txt" && \
    grep "pulumi-v${PULUMI_VERSION}-linux-x64.tar.gz" pulumi_checksums.txt | sha256sum -c - && \
    tar -xzf "pulumi-v${PULUMI_VERSION}-linux-x64.tar.gz" -C /usr/local/bin --strip-components=1 && \
    rm "pulumi-v${PULUMI_VERSION}-linux-x64.tar.gz" pulumi_checksums.txt && \
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    # Create non-root user matching shifter_platform's appuser:1000 / appgroup:1000.
    groupadd --gid 1000 appgroup && \
    useradd --uid 1000 --gid appgroup --create-home --shell /bin/bash appuser && \
    mkdir -p /home/appuser/.terraform.d/plugin-cache /home/appuser/.pulumi && \
    chown -R appuser:appgroup /home/appuser && \
    # Pre-create the Terraform workspace path. AWS ECS/Fargate runs this image
    # as UID 1000 on the task's ephemeral writable layer; GKE-style deployers
    # may also mount an emptyDir here. terraform_base stages module sources
    # under this path per request (issue #1103).
    mkdir -p /var/run/provisioner/workspace && \
    chown -R appuser:appgroup /var/run/provisioner

# Install Python dependencies from reviewed, hash-pinned locks (ADR-037-R4).
# requirements.lock is `uv export --frozen --no-dev` from uv.lock;
# requirements-gcp.lock is `uv pip compile --generate-hashes` of the GCP extras,
# constrained to the same resolved versions. `--require-hashes` makes pip refuse
# any artifact whose hash is not listed. Regenerate both per
# docs/architecture/rev1-build-deployment-provenance.md.
WORKDIR /app
COPY engine/provisioner/requirements.lock engine/provisioner/requirements-gcp.lock ./
RUN pip install --no-cache-dir --require-hashes --only-binary :all: -r requirements.lock && \
    pip install --no-cache-dir --require-hashes --only-binary :all: -r requirements-gcp.lock

# First-party shared packages on PYTHONPATH (cyberscript = wire-contract constants,
# installation = root installation config) — same pattern as shifter_platform/Dockerfile.
# `config.resolve_cloud_provider` validates CLOUD_PROVIDER against
# installation.registry (PLAT-2005), which needs pydantic; pydantic is a declared
# provisioner runtime dependency (requirements.lock), installed above. Range-cell
# consumers use only cyberscript's dependency-light envelope, exception, and digest
# paths; canonical Pydantic validation runs producer-side before persistence.
COPY cyberscript /opt/shifter-libs/cyberscript
COPY installation /opt/shifter-libs/installation

# Dependency-light platform contract modules used by the provisioner runtime.
# Copy the whole `shared` package (same whole-dir pattern as cyberscript and
# installation above) so imports like `shared.range_instantiation_policy`,
# `shared.range_escape`, and `shared.log_sanitize` (added by the #1348 refactor)
# resolve alongside `shared.range_cells`. `shared/__init__.py` re-exports only
# from cyberscript (already present), and the provisioner never imports the
# Django modules (models.py, admin.py, migrations, …), so copying the whole
# package does not pull Django into the provisioner runtime.
COPY shifter_platform/shared /opt/shifter-libs/shared

# Copy provisioner code as root-owned, immutable image content. The runtime
# user does NOT own /app — Terraform writes go to TERRAFORM_WORKSPACE_DIR
# (terraform_base._stage_workspace) so a process compromise cannot tamper
# with application code at runtime (issue #1103, follow-up to #950).
COPY engine/provisioner/ .

# Bake the Terraform provider packages needed by the runtime range/NGFW
# modules. Provisioner tasks run in private subnets without public Terraform
# Registry egress, so terraform init must use this filesystem mirror instead
# of resolving providers at runtime.
RUN mkdir -p /opt/terraform-providers && \
    terraform -chdir=terraform/modules/range providers mirror /opt/terraform-providers && \
    terraform -chdir=terraform/modules/ngfw providers mirror /opt/terraform-providers && \
    chown -R root:root /opt/terraform-providers

# Set HOME explicitly so Terraform/Pulumi find the writable cache/config
# directories created above (Docker's USER directive does not adjust HOME).
# TERRAFORM_WORKSPACE_DIR documents the writable workspace contract; deployers
# that add a mounted writable volume must mount it at this path so
# terraform_base can stage modules and write `.terraform/`,
# `.terraform.lock.hcl`, and `terraform.tfvars.json`.
ENV HOME=/home/appuser \
    PULUMI_HOME=/home/appuser/.pulumi \
    TF_PLUGIN_CACHE_DIR=/home/appuser/.terraform.d/plugin-cache \
    TF_CLI_CONFIG_FILE=/app/terraform.tfrc \
    TERRAFORM_WORKSPACE_DIR=/var/run/provisioner/workspace \
    PYTHONPATH=/opt/shifter-libs

# Drop privileges before invoking Terraform/Pulumi. Numeric UID:GID is used
# (instead of `USER appuser`) so Kubernetes admission controllers running with
# `runAsNonRoot: true` can verify the user is non-root without resolving names.
USER 1000:1000

# Entrypoint receives operation as argument
ENTRYPOINT ["python", "main.py"]
