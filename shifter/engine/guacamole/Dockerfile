# Guacamole Client
#
# Uses the official guacamole/guacamole image with a custom entrypoint that
# handles idempotent database schema initialization.
#
# The base image handles:
# - Extension loading (via JSON_ENABLED=true, OPENID_ENABLED=false)
#
# Our entrypoint adds:
# - Automatic schema creation on first startup (idempotent)
#
# Required environment variables:
# - JSON_SECRET_KEY: 128-bit hex key for signing/encrypting JSON auth payloads
# - POSTGRESQL_HOSTNAME, POSTGRESQL_DATABASE, POSTGRESQL_USER, POSTGRESQL_PASSWORD
#
# Reference: https://guacamole.apache.org/doc/gug/guacamole-docker.html

ARG GUACAMOLE_VERSION=1.5.5
FROM guacamole/guacamole:${GUACAMOLE_VERSION}

# Install PostgreSQL client for schema initialization
USER root
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Add custom entrypoint for idempotent schema initialization
COPY entrypoint.sh /opt/guacamole/bin/custom-entrypoint.sh
RUN chmod +x /opt/guacamole/bin/custom-entrypoint.sh

USER guacamole

ENTRYPOINT ["/opt/guacamole/bin/custom-entrypoint.sh"]
CMD ["/opt/guacamole/bin/start.sh"]
