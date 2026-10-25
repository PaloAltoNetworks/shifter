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

# Base image pinned by digest for reproducibility.
#
# This digest is the guacamole/guacamole:latest rebuild re-pointed 2026-10-03:
# the Guacamole 1.6.0 web application on a patched Apache Tomcat 9.0.x and
# Ubuntu 24.04. It is pinned by digest (not by the mutable :latest tag) so
# builds stay reproducible.
#
# Why :latest-by-digest and not the versioned :1.6.0 tag: the released :1.6.0
# tag bundles an older Tomcat/Ubuntu that still carry fixable HIGH/CRITICAL
# Tomcat + OS CVEs. The latest rebuild carries the patched Tomcat and Ubuntu
# base. This 2026-10-03 re-point clears the Ubuntu openssl finding
# CVE-2026-84782 (libssl3t64/openssl -> 3.0.13-0ubuntu3.16). Re-point this
# digest when a newer rebuild ships further OS/Tomcat fixes.
ARG GUACAMOLE_VERSION=1.6.0
# base image: guacamole 1.6.0 webapp on Tomcat 9.0.x / Ubuntu 24.04 (keep in sync with the digest below)
FROM guacamole/guacamole@sha256:1880e60e0b768294537a7071bc023fffbc8f4917b4f7caf0b72d8938ee4f238f

# Install PostgreSQL client for schema initialization
USER root
# Shifter authenticates with JSON auth and stores sessions in PostgreSQL.
# These unused upstream extensions bundle vulnerable providers: Bouncy Castle
# (CVE-2026-8763, CVE-2026-13505, CVE-2026-13506, CVE-2026-8798) in the SSO/vault
# extensions, and jackson (CVE-2026-68494/68497/89407/89425/91776/91777) in the
# duo and ldap extensions. Remove the unused extensions and their activation
# links instead of shipping dormant vulnerable providers. The jackson copies in
# the core webapp and the in-use JSON-auth extension have no Guacamole-level fix
# and are tracked, time-boxed, in .trivyignore.yaml (issue #2237).
RUN rm -rf /opt/guacamole/extensions/guacamole-auth-sso/cas \
    /opt/guacamole/extensions/guacamole-auth-sso/ssl \
    /opt/guacamole/extensions/guacamole-vault/ksm \
    /opt/guacamole/extensions/guacamole-auth-duo \
    /opt/guacamole/extensions/guacamole-auth-ldap \
    /opt/guacamole/environment/CAS_ \
    /opt/guacamole/environment/SSL_AUTH_ \
    /opt/guacamole/environment/KSM_ \
    /opt/guacamole/environment/DUO_ \
    /opt/guacamole/environment/LDAP_

RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Add custom entrypoint for idempotent schema initialization
COPY entrypoint.sh /opt/guacamole/bin/custom-entrypoint.sh
RUN chmod +x /opt/guacamole/bin/custom-entrypoint.sh

USER guacamole

# custom-entrypoint.sh runs idempotent schema init then `exec "$@"` to hand off
# to the base image's start command. Guacamole 1.6.0's image starts via
# /opt/guacamole/bin/entrypoint.sh (the base image's own CMD); older images used
# start.sh, which the pinned 1.6.0 rebuild no longer ships. Keep this in sync
# with the base image's CMD (`docker inspect ... .Config.Cmd`).
ENTRYPOINT ["/opt/guacamole/bin/custom-entrypoint.sh"]
CMD ["/opt/guacamole/bin/entrypoint.sh"]
