#!/bin/bash
set -euo pipefail

# LibreChat EC2 User Data
# Installs Docker, Docker Compose, and starts LibreChat with MongoDB

exec > >(tee /var/log/user-data.log | logger -t user-data -s 2>/dev/console) 2>&1

echo "Starting LibreChat setup..."

# ------------------------------------------------------------------------------
# Install Docker and Docker Compose
# ------------------------------------------------------------------------------

dnf install -y docker jq
systemctl enable docker
systemctl start docker

# Install Docker Compose plugin
mkdir -p /usr/local/lib/docker/cli-plugins
curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# Add ec2-user to docker group
usermod -aG docker ec2-user

# ------------------------------------------------------------------------------
# Mount Data Volume
# ------------------------------------------------------------------------------

DATA_DEVICE="${data_volume_device}"
DATA_MOUNT="/opt/librechat/data"

# Wait for device to be attached
while [ ! -e "$DATA_DEVICE" ]; do
  echo "Waiting for data volume to attach..."
  sleep 5
done

# Format if not already formatted
if ! blkid "$DATA_DEVICE"; then
  echo "Formatting data volume..."
  mkfs.xfs "$DATA_DEVICE"
fi

# Mount the volume
mkdir -p "$DATA_MOUNT"
if ! grep -q "$DATA_MOUNT" /etc/fstab; then
  echo "$DATA_DEVICE $DATA_MOUNT xfs defaults,nofail 0 2" >> /etc/fstab
fi
mount -a

# Set permissions
chown -R 1000:1000 "$DATA_MOUNT"

# ------------------------------------------------------------------------------
# Fetch Secrets
# ------------------------------------------------------------------------------

echo "Fetching secrets from Secrets Manager..."

SECRET_JSON=$(aws secretsmanager get-secret-value \
  --secret-id "${secret_arn}" \
  --region "${aws_region}" \
  --query 'SecretString' \
  --output text)

JWT_SECRET=$(echo "$SECRET_JSON" | jq -r '.jwt_secret')
JWT_REFRESH_SECRET=$(echo "$SECRET_JSON" | jq -r '.jwt_refresh_secret')
CREDS_KEY=$(echo "$SECRET_JSON" | jq -r '.creds_key')
CREDS_IV=$(echo "$SECRET_JSON" | jq -r '.creds_iv')
ALLOW_REGISTRATION=$(echo "$SECRET_JSON" | jq -r '.allow_registration')
APP_TITLE=$(echo "$SECRET_JSON" | jq -r '.app_title')

# ------------------------------------------------------------------------------
# Create LibreChat Directory Structure
# ------------------------------------------------------------------------------

mkdir -p /opt/librechat/{images,logs}
chown -R 1000:1000 /opt/librechat

# ------------------------------------------------------------------------------
# Create Docker Compose File
# ------------------------------------------------------------------------------

cat > /opt/librechat/docker-compose.yml << 'COMPOSE_EOF'
services:
  api:
    container_name: librechat
    image: ghcr.io/danny-avila/librechat:latest
    ports:
      - "3080:3080"
    depends_on:
      - mongodb
    env_file:
      - .env
    volumes:
      - ./images:/app/client/public/images
      - ./logs:/app/logs
      - ./librechat.yaml:/app/librechat.yaml:ro
    extra_hosts:
      - "host.docker.internal:host-gateway"
    restart: unless-stopped

  mongodb:
    container_name: librechat-mongodb
    image: mongo:7
    volumes:
      - ./data/mongodb:/data/db
    command: mongod --noauth
    restart: unless-stopped
COMPOSE_EOF

# ------------------------------------------------------------------------------
# Create Secrets Refresh Script (for deploy workflow)
# ------------------------------------------------------------------------------

cat > /opt/librechat/refresh-secrets.sh << 'REFRESH_EOF'
#!/bin/bash
set -euo pipefail

# Fetch latest secrets from Secrets Manager
SECRET_JSON=$(aws secretsmanager get-secret-value \
  --secret-id "${secret_arn}" \
  --region "${aws_region}" \
  --query 'SecretString' \
  --output text)

JWT_SECRET=$(echo "$SECRET_JSON" | jq -r '.jwt_secret')
JWT_REFRESH_SECRET=$(echo "$SECRET_JSON" | jq -r '.jwt_refresh_secret')
CREDS_KEY=$(echo "$SECRET_JSON" | jq -r '.creds_key')
CREDS_IV=$(echo "$SECRET_JSON" | jq -r '.creds_iv')
ALLOW_REGISTRATION=$(echo "$SECRET_JSON" | jq -r '.allow_registration')
APP_TITLE=$(echo "$SECRET_JSON" | jq -r '.app_title')

# Update .env file
cat > /opt/librechat/.env << ENV_EOF
# Server Configuration
HOST=0.0.0.0
PORT=3080
MONGO_URI=mongodb://mongodb:27017/LibreChat

# Authentication
ALLOW_EMAIL_LOGIN=true
ALLOW_REGISTRATION=$ALLOW_REGISTRATION
ALLOW_SOCIAL_LOGIN=false
ALLOW_SOCIAL_REGISTRATION=false
ALLOW_PASSWORD_RESET=false
ALLOW_UNVERIFIED_EMAIL_LOGIN=true

# Session Configuration
SESSION_EXPIRY=900000
REFRESH_TOKEN_EXPIRY=604800000

# Security Secrets
JWT_SECRET=$JWT_SECRET
JWT_REFRESH_SECRET=$JWT_REFRESH_SECRET
CREDS_KEY=$CREDS_KEY
CREDS_IV=$CREDS_IV

# UI Configuration
APP_TITLE=$APP_TITLE
NO_INDEX=true

# Disable features not needed initially
SEARCH=false

# Debug (disable in production after testing)
DEBUG_LOGGING=false
DEBUG_CONSOLE=false
CONSOLE_JSON=true

# AWS Bedrock (uses EC2 instance role - no static creds)
BEDROCK_AWS_DEFAULT_REGION=${aws_region}
BEDROCK_AWS_MODELS=us.anthropic.claude-sonnet-4-5-20250929-v1:0,us.anthropic.claude-3-7-sonnet-20250219-v1:0,us.anthropic.claude-3-5-sonnet-20240620-v1:0,us.anthropic.claude-3-5-haiku-20241022-v1:0,us.anthropic.claude-3-haiku-20240307-v1:0
ENV_EOF

chmod 600 /opt/librechat/.env

# Recreate containers to pick up new env vars
cd /opt/librechat
docker compose up -d --force-recreate

echo "Secrets refreshed and containers recreated"
REFRESH_EOF

chmod +x /opt/librechat/refresh-secrets.sh

# ------------------------------------------------------------------------------
# Create Environment File
# ------------------------------------------------------------------------------

cat > /opt/librechat/.env << ENV_EOF
# Server Configuration
HOST=0.0.0.0
PORT=3080
MONGO_URI=mongodb://mongodb:27017/LibreChat

# Authentication
ALLOW_EMAIL_LOGIN=true
ALLOW_REGISTRATION=$ALLOW_REGISTRATION
ALLOW_SOCIAL_LOGIN=false
ALLOW_SOCIAL_REGISTRATION=false
ALLOW_PASSWORD_RESET=false
ALLOW_UNVERIFIED_EMAIL_LOGIN=true

# Session Configuration
SESSION_EXPIRY=900000
REFRESH_TOKEN_EXPIRY=604800000

# Security Secrets
JWT_SECRET=$JWT_SECRET
JWT_REFRESH_SECRET=$JWT_REFRESH_SECRET
CREDS_KEY=$CREDS_KEY
CREDS_IV=$CREDS_IV

# UI Configuration
APP_TITLE=$APP_TITLE
NO_INDEX=true

# Disable features not needed initially
SEARCH=false

# Debug (disable in production after testing)
DEBUG_LOGGING=false
DEBUG_CONSOLE=false
CONSOLE_JSON=true

# AWS Bedrock (uses EC2 instance role - no static creds)
# Uses inference profile IDs (us. prefix) required for on-demand invocation
BEDROCK_AWS_DEFAULT_REGION=${aws_region}
BEDROCK_AWS_MODELS=us.anthropic.claude-sonnet-4-5-20250929-v1:0,us.anthropic.claude-3-7-sonnet-20250219-v1:0,us.anthropic.claude-3-5-sonnet-20240620-v1:0,us.anthropic.claude-3-5-haiku-20241022-v1:0,us.anthropic.claude-3-haiku-20240307-v1:0
ENV_EOF

chmod 600 /opt/librechat/.env

# ------------------------------------------------------------------------------
# Create LibreChat YAML Configuration
# ------------------------------------------------------------------------------

cat > /opt/librechat/librechat.yaml << YAML_EOF
version: 1.2.1

endpoints:
  bedrock:
    availableRegions:
      - ${aws_region}
    titleModel: us.anthropic.claude-3-haiku-20240307-v1:0
  agents:
    disableBuilder: true

modelSpecs:
  enforce: false
  prioritize: true
  list:
    - name: "Claude Sonnet 4.5"
      label: "Claude Sonnet 4.5"
      default: true
      preset:
        endpoint: "bedrock"
        model: "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
YAML_EOF

# ------------------------------------------------------------------------------
# Start LibreChat
# ------------------------------------------------------------------------------

cd /opt/librechat
docker compose pull
docker compose up -d

echo "LibreChat setup complete!"
echo "Access via SSM port forwarding on port 3080"

