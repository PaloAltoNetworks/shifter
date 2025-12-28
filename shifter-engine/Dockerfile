FROM python:3.12-slim

# Install Pulumi CLI (pinned version)
ARG PULUMI_VERSION=3.142.0
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL -o pulumi.tar.gz \
      "https://github.com/pulumi/pulumi/releases/download/v${PULUMI_VERSION}/pulumi-v${PULUMI_VERSION}-linux-x64.tar.gz" && \
    tar -xzf pulumi.tar.gz -C /usr/local/bin --strip-components=1 && \
    rm pulumi.tar.gz && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Pulumi program
COPY . .

# Entrypoint receives operation as argument
ENTRYPOINT ["python", "main.py"]
