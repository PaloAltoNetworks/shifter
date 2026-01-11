# Guacamole Client with Authentication Extensions
#
# Uses the official guacamole/guacamole image with extensions enabled via env vars.
# The base image includes extensions in /opt/guacamole/extensions-available/
# and the entrypoint symlinks them to $GUACAMOLE_HOME/extensions/ when enabled.
#
# Required environment variables for OIDC:
# - OPENID_AUTHORIZATION_ENDPOINT, OPENID_JWKS_ENDPOINT, OPENID_ISSUER
# - OPENID_CLIENT_ID, OPENID_REDIRECT_URI
#
# Required environment variables for JSON auth:
# - JSON_SECRET_KEY: 128-bit hex key for signing/encrypting JSON auth payloads
#
# Reference: https://guacamole.apache.org/doc/gug/guacamole-docker.html

ARG GUACAMOLE_VERSION=1.5.5
FROM guacamole/guacamole:${GUACAMOLE_VERSION}

# Extensions are enabled via environment variables in ECS task definition:
# - OPENID_ENABLED=true (auto-detected when OPENID_* vars are set)
# - JSON_ENABLED=true
#
# The base entrypoint handles symlinking extensions from /opt/guacamole/extensions-available/

# Install PostgreSQL client for database initialization
USER root
RUN apt-get update && \
    apt-get install -y --no-install-recommends postgresql-client && \
    rm -rf /var/lib/apt/lists/*
USER guacamole

# Custom entrypoint wrapper that initializes the database schema if needed
# This is idempotent - checks if schema exists before running initdb.sh
COPY entrypoint.sh /opt/guacamole/bin/entrypoint-wrapper.sh
USER root
RUN chmod +x /opt/guacamole/bin/entrypoint-wrapper.sh
USER guacamole

ENTRYPOINT ["/opt/guacamole/bin/entrypoint-wrapper.sh"]
