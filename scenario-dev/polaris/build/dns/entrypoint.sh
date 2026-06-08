#!/bin/sh
# POLARIS dns container entrypoint.
#
# Substitutes the __DC01_IP__ placeholder in DNS zone files with the value of
# the DC01_IP environment variable set by docker-compose.override.yml on the
# host. The domain name is intentionally the same in every range forest because
# AD is isolated, but the IN-A records must be per-range.
set -eu

if [ -z "${DC01_IP:-}" ]; then
    echo "dns entrypoint: DC01_IP env var is required" >&2
    exit 1
fi

for ZONE in /etc/bind/db.boreas.local /etc/bind/db.boreas-systems.ctf; do
    if grep -q "__DC01_IP__" "$ZONE"; then
        sed -i "s|__DC01_IP__|${DC01_IP}|g" "$ZONE"
        echo "dns entrypoint: ${ZONE} dc01 -> ${DC01_IP}"
    fi
done

exec named -g -c /etc/bind/named.conf
