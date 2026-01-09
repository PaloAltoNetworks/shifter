# Guacamole Client with OpenID Connect Extension
# This image extends the official guacamole/guacamole image to include
# the SSO extension for Cognito/OIDC authentication.

ARG GUACAMOLE_VERSION=1.5.5
FROM guacamole/guacamole:${GUACAMOLE_VERSION}

ARG GUACAMOLE_VERSION

# Download and install the OpenID Connect extension
# The SSO extension package contains OIDC, SAML, and CAS - we only need OIDC
RUN set -ex \
    && wget -q "https://archive.apache.org/dist/guacamole/${GUACAMOLE_VERSION}/binary/guacamole-auth-sso-${GUACAMOLE_VERSION}.tar.gz" \
    && tar -xzf "guacamole-auth-sso-${GUACAMOLE_VERSION}.tar.gz" \
    && cp "guacamole-auth-sso-${GUACAMOLE_VERSION}/openid/guacamole-auth-sso-openid-${GUACAMOLE_VERSION}.jar" /opt/guacamole/extensions/ \
    && rm -rf "guacamole-auth-sso-${GUACAMOLE_VERSION}" "guacamole-auth-sso-${GUACAMOLE_VERSION}.tar.gz"

# The following environment variables configure OIDC authentication:
# - OPENID_AUTHORIZATION_ENDPOINT: Cognito OAuth2 authorization URL
# - OPENID_JWKS_ENDPOINT: Cognito JWKS endpoint for token validation
# - OPENID_ISSUER: Cognito issuer URL
# - OPENID_CLIENT_ID: Cognito app client ID
# - OPENID_REDIRECT_URI: Guacamole callback URL
# - OPENID_SCOPE: OAuth scopes (default: "openid profile email")
# - OPENID_USERNAME_CLAIM_TYPE: Claim to use as username (default: "email")
#
# These are set via ECS task definition environment variables.
