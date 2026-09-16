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

# kubectl is always installed. The KubeVirt `virt` plugin (virtctl, installed as
# `kubectl-virt`) drives GDC VM Runtime guest start/stop for range pause/resume
# (issue #614, gdc_vmruntime_assets.run_power_operation). virtctl is installed
# ONLY when INSTALL_KUBEVIRT=true (GDC deployments); the default GCE range backend
# never invokes it (GCE pause/resume uses the Compute API), so the default image
# omits it — no GDC tooling on the default path (ADR: GDC not selected by default).
# KubeVirt publishes no release checksums file, so virtctl integrity is verified
# against the pinned VIRTCTL_SHA256 digest (of virtctl-${KUBEVIRT_VERSION}-linux-amd64)
# rather than a non-existent upstream CHECKSUMS asset. KUBEVIRT_VERSION tracks the
# deployed GDC VM Runtime version; bump VIRTCTL_SHA256 in lockstep.
ARG KUBECTL_VERSION=v1.31.4
ARG KUBEVIRT_VERSION=v1.4.0
ARG INSTALL_KUBEVIRT=false
ARG VIRTCTL_SHA256=ebc167273e40a295721c61d04c4458fa8f037c5a00b347dbb4f5456a02ce4e7a

# Single root-stage RUN: install build tools, terraform, pulumi, create the
# non-root runtime user with its writable plugin-cache / pulumi dirs, and
# create the writable Terraform workspace mount point.
# Keeping these in one layer satisfies docker:S7031 (no consecutive RUNs).
# --create-home gives Terraform/Pulumi a writable HOME for plugin caches.
# --no-install-recommends keeps the image lean (docker:S6500); ca-certificates is
# listed explicitly because it is only a curl "recommends", and the HTTPS
# downloads below need the trust store.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl openssh-client unzip && \
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
    # Install kubectl, integrity-verified against dl.k8s.io's published hash.
    curl --proto '=https' --retry 5 --retry-delay 3 --retry-all-errors --connect-timeout 20 -fsSL \
      -o kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" && \
    curl --proto '=https' --retry 5 --retry-delay 3 --retry-all-errors --connect-timeout 20 -fsSL \
      -o kubectl.sha256 "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl.sha256" && \
    echo "$(cat kubectl.sha256)  kubectl" | sha256sum -c - && \
    install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl && \
    rm kubectl kubectl.sha256 && \
    # Exercise kubectl offline (it resolves kubectl-* plugins from PATH).
    kubectl version --client >/dev/null && \
    # Install the KubeVirt virt plugin (virtctl) as kubectl-virt ONLY for GDC VM
    # Runtime deployments (INSTALL_KUBEVIRT=true). KubeVirt publishes no release
    # checksums file, so integrity is verified against the pinned VIRTCTL_SHA256
    # digest. The default GCE backend skips this entirely.
    if [ "${INSTALL_KUBEVIRT}" = "true" ]; then \
      curl --proto '=https' --retry 5 --retry-delay 3 --retry-all-errors --connect-timeout 20 -fsSL \
        -o "virtctl-${KUBEVIRT_VERSION}-linux-amd64" \
        "https://github.com/kubevirt/kubevirt/releases/download/${KUBEVIRT_VERSION}/virtctl-${KUBEVIRT_VERSION}-linux-amd64" && \
      echo "${VIRTCTL_SHA256}  virtctl-${KUBEVIRT_VERSION}-linux-amd64" | sha256sum -c - && \
      install -o root -g root -m 0755 "virtctl-${KUBEVIRT_VERSION}-linux-amd64" /usr/local/bin/kubectl-virt && \
      rm "virtctl-${KUBEVIRT_VERSION}-linux-amd64" && \
      kubectl-virt help >/dev/null; \
    fi && \
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

# First-party installation config on PYTHONPATH — the same pattern as
# shifter_platform/Dockerfile.
# `config.resolve_cloud_provider` validates CLOUD_PROVIDER against
# installation.registry (PLAT-2005), which needs pydantic; pydantic is a declared
# provisioner runtime dependency (requirements.lock), installed above.
COPY installation /opt/shifter-libs/installation

# Dependency-light platform contract modules used by the provisioner runtime.
# Copy the whole `shared` package so imports like `shared.range_instantiation_policy`,
# `shared.range_escape`, and `shared.log_sanitize` (added by the #1348 refactor)
# resolve alongside `shared.range_cells`. The provisioner never imports the
# Django modules (models.py, admin.py, migrations, …), so copying the whole
# package does not pull Django into the provisioner runtime.
COPY shifter_platform/shared /opt/shifter-libs/shared

# Copy provisioner code as root-owned, immutable image content. The runtime
# user does NOT own /app — Terraform writes go to TERRAFORM_WORKSPACE_DIR
# (terraform_base._stage_workspace) so a process compromise cannot tamper
# with application code at runtime (issue #1103, follow-up to #950).
COPY engine/provisioner/ .
COPY packer/files/polaris_splice_credential.py /app/assets/polaris-splice-credential.py

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
# KUBECACHEDIR points kubectl's discovery cache at the writable /tmp mount so
# the GDC VM Runtime `kubectl virt` power op works under a read-only root
# filesystem (issue #614); kubectl creates the directory on first use.
ENV HOME=/home/appuser \
    PULUMI_HOME=/home/appuser/.pulumi \
    TF_PLUGIN_CACHE_DIR=/home/appuser/.terraform.d/plugin-cache \
    TF_CLI_CONFIG_FILE=/app/terraform.tfrc \
    TERRAFORM_WORKSPACE_DIR=/var/run/provisioner/workspace \
    KUBECACHEDIR=/tmp/.kube-cache \
    PYTHONPATH=/opt/shifter-libs

# Drop privileges before invoking Terraform/Pulumi. Numeric UID:GID is used
# (instead of `USER appuser`) so Kubernetes admission controllers running with
# `runAsNonRoot: true` can verify the user is non-root without resolving names.
USER 1000:1000

# Entrypoint receives operation as argument
ENTRYPOINT ["python", "main.py"]
