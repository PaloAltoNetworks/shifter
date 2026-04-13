FROM python:3.12-slim-trixie

# Install Terraform and Pulumi CLI (pinned versions)
ARG TERRAFORM_VERSION=1.14.3
ARG PULUMI_VERSION=3.142.0

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
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home --shell /usr/sbin/nologin appuser

# Install Python dependencies
WORKDIR /app
COPY requirements.txt requirements-gcp.txt ./
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -r requirements-gcp.txt

# Copy Pulumi program
COPY . .
RUN chown -R appuser:appuser /app /home/appuser

ENV HOME=/home/appuser

# Entrypoint receives operation as argument
USER appuser
ENTRYPOINT ["python", "main.py"]
