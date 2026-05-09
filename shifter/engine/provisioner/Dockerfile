FROM python:3.12-slim-trixie

# Install Terraform and Pulumi CLI (pinned versions)
ARG TERRAFORM_VERSION=1.14.3
ARG PULUMI_VERSION=3.142.0

# Single root-stage RUN: install build tools, terraform, pulumi, then create
# the non-root runtime user with its writable plugin-cache / pulumi dirs.
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
    chown -R appuser:appgroup /home/appuser

# Install Python dependencies
WORKDIR /app
RUN chown appuser:appgroup /app
COPY requirements.txt requirements-gcp.txt ./
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -r requirements-gcp.txt

# Copy provisioner code, owned by the non-root runtime user so Terraform can
# write .terraform/ and terraform.tfvars.json inside module working directories
# (see terraform_base.apply / destroy in this package).
COPY --chown=appuser:appgroup . .

# Set HOME explicitly so Terraform/Pulumi find the writable cache/config
# directories created above (Docker's USER directive does not adjust HOME).
ENV HOME=/home/appuser \
    PULUMI_HOME=/home/appuser/.pulumi \
    TF_PLUGIN_CACHE_DIR=/home/appuser/.terraform.d/plugin-cache

# Drop privileges before invoking Terraform/Pulumi. Numeric UID:GID is used
# (instead of `USER appuser`) so Kubernetes admission controllers running with
# `runAsNonRoot: true` can verify the user is non-root without resolving names.
USER 1000:1000

# Entrypoint receives operation as argument
ENTRYPOINT ["python", "main.py"]
