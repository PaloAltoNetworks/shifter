# Guacamole Client
#
# Uses the official guacamole/guacamole image with extensions enabled via env vars.
# The base image handles everything:
# - DB schema init (via POSTGRESQL_AUTO_CREATE_ACCOUNTS=true)
# - Extension loading (via JSON_ENABLED=true, OPENID_ENABLED=false)
#
# Required environment variables:
# - JSON_SECRET_KEY: 128-bit hex key for signing/encrypting JSON auth payloads
#
# Reference: https://guacamole.apache.org/doc/gug/guacamole-docker.html

ARG GUACAMOLE_VERSION=1.5.5
FROM guacamole/guacamole:${GUACAMOLE_VERSION}

# No customizations needed - base image handles everything
