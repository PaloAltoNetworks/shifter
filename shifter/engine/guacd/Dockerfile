# guacd with RDP file transfer support
#
# The official guacd image runs as non-root user 'guacd' which cannot create
# the drive directory needed for RDP file transfer (drag & drop, clipboard files).
# This image pre-creates /var/lib/guacamole/drive with proper permissions.
#
# Reference: https://guacamole.apache.org/doc/gug/configuring-guacamole.html

ARG GUACAMOLE_VERSION=1.5.5
FROM guacamole/guacd:${GUACAMOLE_VERSION}

# Create drive directory for RDP file transfer
# Must be owned by guacd user for proper read/write access
USER root
RUN mkdir -p /var/lib/guacamole/drive && \
    chown guacd:guacd /var/lib/guacamole/drive && \
    chmod 750 /var/lib/guacamole/drive
USER guacd
