# Guacamole Client with Authentication Extensions
#
# Extends the official guacamole/guacamole image to add:
# - SSO/OIDC extension for Cognito authentication
# - JSON auth extension for on-the-fly RDP connections from Portal
#
# Reference: https://guacamole.apache.org/doc/gug/guacamole-docker.html

ARG GUACAMOLE_VERSION=1.5.5
FROM guacamole/guacamole:${GUACAMOLE_VERSION}

# Re-declare ARG after FROM (Docker scoping requires this)
ARG GUACAMOLE_VERSION=1.5.5

# GUACAMOLE_HOME is /etc/guacamole in the official image
# Extensions go in $GUACAMOLE_HOME/extensions
ENV GUACAMOLE_HOME=/etc/guacamole

USER root

# Download and install authentication extensions
RUN set -eux; \
    # Create extensions directory
    mkdir -p "${GUACAMOLE_HOME}/extensions"; \
    \
    # Download SSO/OIDC extension
    wget -q -O /tmp/guacamole-auth-sso.tar.gz \
        "https://archive.apache.org/dist/guacamole/${GUACAMOLE_VERSION}/binary/guacamole-auth-sso-${GUACAMOLE_VERSION}.tar.gz"; \
    tar -xzf /tmp/guacamole-auth-sso.tar.gz -C /tmp; \
    cp "/tmp/guacamole-auth-sso-${GUACAMOLE_VERSION}/openid/guacamole-auth-sso-openid-${GUACAMOLE_VERSION}.jar" \
        "${GUACAMOLE_HOME}/extensions/"; \
    \
    # Download JSON auth extension
    wget -q -O /tmp/guacamole-auth-json.tar.gz \
        "https://archive.apache.org/dist/guacamole/${GUACAMOLE_VERSION}/binary/guacamole-auth-json-${GUACAMOLE_VERSION}.tar.gz"; \
    tar -xzf /tmp/guacamole-auth-json.tar.gz -C /tmp; \
    cp "/tmp/guacamole-auth-json-${GUACAMOLE_VERSION}/guacamole-auth-json-${GUACAMOLE_VERSION}.jar" \
        "${GUACAMOLE_HOME}/extensions/"; \
    \
    # Cleanup
    rm -rf /tmp/guacamole-auth-*; \
    \
    # Verify extensions installed
    ls -la "${GUACAMOLE_HOME}/extensions/"

# Drop back to non-root (guacamole user created by base image)
USER guacamole

# Environment variables for OIDC authentication (set via ECS task definition):
# - OPENID_AUTHORIZATION_ENDPOINT: Cognito OAuth2 authorization URL
# - OPENID_JWKS_ENDPOINT: Cognito JWKS endpoint for token validation
# - OPENID_ISSUER: Cognito issuer URL
# - OPENID_CLIENT_ID: Cognito app client ID
# - OPENID_REDIRECT_URI: Guacamole callback URL
# - OPENID_SCOPE: OAuth scopes (default: "openid profile email")
# - OPENID_USERNAME_CLAIM_TYPE: Claim to use as username (default: "email")
#
# Environment variable for JSON authentication:
# - JSON_SECRET_KEY: 128-bit hex key for signing/encrypting JSON auth payloads
