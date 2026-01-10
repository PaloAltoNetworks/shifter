# Guacamole Client with Authentication Extensions
# This image extends the official guacamole/guacamole image to include:
# - SSO extension for Cognito/OIDC authentication
# - JSON auth extension for on-the-fly RDP connections from Portal

ARG GUACAMOLE_VERSION=1.5.5
FROM guacamole/guacamole:${GUACAMOLE_VERSION}

# Re-declare ARG after FROM with default (ARGs before FROM are out of scope)
ARG GUACAMOLE_VERSION=1.5.5

# Use /tmp as working directory for downloads (ensures write permissions)
WORKDIR /tmp

# Download and install authentication extensions:
# 1. SSO/OIDC extension for Cognito authentication
# 2. JSON auth extension for on-the-fly RDP connections from Portal
RUN set -ex \
    && wget -q "https://archive.apache.org/dist/guacamole/${GUACAMOLE_VERSION}/binary/guacamole-auth-sso-${GUACAMOLE_VERSION}.tar.gz" \
    && tar -xzf "guacamole-auth-sso-${GUACAMOLE_VERSION}.tar.gz" \
    && cp "guacamole-auth-sso-${GUACAMOLE_VERSION}/openid/guacamole-auth-sso-openid-${GUACAMOLE_VERSION}.jar" /opt/guacamole/extensions/ \
    && rm -rf "guacamole-auth-sso-${GUACAMOLE_VERSION}" "guacamole-auth-sso-${GUACAMOLE_VERSION}.tar.gz" \
    && wget -q "https://archive.apache.org/dist/guacamole/${GUACAMOLE_VERSION}/binary/guacamole-auth-json-${GUACAMOLE_VERSION}.tar.gz" \
    && tar -xzf "guacamole-auth-json-${GUACAMOLE_VERSION}.tar.gz" \
    && cp "guacamole-auth-json-${GUACAMOLE_VERSION}/guacamole-auth-json-${GUACAMOLE_VERSION}.jar" /opt/guacamole/extensions/ \
    && rm -rf "guacamole-auth-json-${GUACAMOLE_VERSION}" "guacamole-auth-json-${GUACAMOLE_VERSION}.tar.gz"

# Run as non-root user (security best practice)
# The base guacamole/guacamole image creates this user
USER guacamole

# The following environment variables configure OIDC authentication:
# - OPENID_AUTHORIZATION_ENDPOINT: Cognito OAuth2 authorization URL
# - OPENID_JWKS_ENDPOINT: Cognito JWKS endpoint for token validation
# - OPENID_ISSUER: Cognito issuer URL
# - OPENID_CLIENT_ID: Cognito app client ID
# - OPENID_REDIRECT_URI: Guacamole callback URL
# - OPENID_SCOPE: OAuth scopes (default: "openid profile email")
# - OPENID_USERNAME_CLAIM_TYPE: Claim to use as username (default: "email")
#
# The following environment variable configures JSON authentication:
# - JSON_SECRET_KEY: 128-bit hex key for signing/encrypting JSON auth payloads
#
# These are set via ECS task definition environment variables.
