FROM python:3.12-slim-trixie

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    unzip \
    openssh-client \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Pulumi CLI (pinned version) - for legacy Pulumi-provisioned NGFWs
ARG PULUMI_VERSION=3.142.0
RUN curl -fsSL -o pulumi.tar.gz \
      "https://github.com/pulumi/pulumi/releases/download/v${PULUMI_VERSION}/pulumi-v${PULUMI_VERSION}-linux-x64.tar.gz" && \
    tar -xzf pulumi.tar.gz -C /usr/local/bin --strip-components=1 && \
    rm pulumi.tar.gz

# Install Terraform CLI (pinned version)
ARG TERRAFORM_VERSION=1.9.8
RUN curl -fsSL -o terraform.zip \
      "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" && \
    unzip terraform.zip -d /usr/local/bin && \
    rm terraform.zip && \
    chmod +x /usr/local/bin/terraform

# Install Python dependencies (includes Ansible)
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Pulumi program
COPY . .

# Entrypoint receives operation as argument
ENTRYPOINT ["python", "main.py"]
