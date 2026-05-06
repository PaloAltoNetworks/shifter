#!/bin/sh
# POLARIS dns container entrypoint.
#
# Substitutes the __DC01_IP__ placeholder in the boreas.local zone file
# with the value of the DC01_IP environment variable (set by
# docker-compose.override.yml on the host). Without this the zone file
# would hard-code the single-range .11 address and every range would
# resolve dc01.boreas.local to range 0's DC — same domain name in every
# range forest is fine because AD is isolated, but the IN-A record
# must be per-range.
set -eu

if [ -z "${DC01_IP:-}" ]; then
    echo "dns entrypoint: DC01_IP env var is required" >&2
    exit 1
fi

ZONE=/etc/bind/db.boreas.local
if grep -q "__DC01_IP__" "$ZONE"; then
    sed -i "s|__DC01_IP__|${DC01_IP}|g" "$ZONE"
    echo "dns entrypoint: dc01.boreas.local -> ${DC01_IP}"
fi

exec named -g -c /etc/bind/named.conf
