#!/bin/bash
# AWS-only: bake a deterministic systemd-resolved upstream fallback into the
# range-guest AMIs so guest DNS is race-free from first boot (issue #1633).
#
# Root cause: the range-guest AMIs run systemd-resolved as the stub resolver
# (/etc/resolv.conf -> 127.0.0.53). On some boots systemd-resolved comes up with
# no upstream DNS (the DHCP-provided VPC resolver is not registered), so the
# system resolver SERVFAILs, the SSM agent loops on "server misbehaving," never
# registers, and range provisioning fails. Issue #1632 mitigates this at range
# boot via user_data (defense in depth, kept); this bakes the fix into the image
# so it does not depend on cloud-init timing.
#
# Fix: register the link-local AmazonProvidedDNS (169.254.169.253 - reachable in
# every VPC regardless of CIDR, and the same Route 53 Resolver as the VPC+2
# address, so DNS Firewall and query logging still apply) as systemd-resolved's
# FallbackDNS. FallbackDNS (not a hard DNS= pin) preserves the DHCP-provided
# per-link DNS as the primary when it registers and only takes over when no
# per-link upstream is available - exactly the failing case.
#
# AWS-only: referenced solely by the top-level AWS kali.pkr.hcl and
# ubuntu.pkr.hcl. It must never be added to the shared scripts/{kali,ubuntu,
# common} trees, which the GCP templates consume via ../scripts/...
set -euo pipefail

FALLBACK_DNS="169.254.169.253"
DROPIN_DIR="/etc/systemd/resolved.conf.d"
DROPIN_FILE="${DROPIN_DIR}/20-amazon-vpc-dns.conf"
# All Shifter AWS resources live in us-east-2; resolve the regional SSM endpoint
# as the bake-time proof that the system resolver works.
PROBE_HOST="ssm.us-east-2.amazonaws.com"

echo "=== Baking AmazonProvidedDNS fallback for systemd-resolved (#1633) ==="

# Fail closed on an unsupported resolver stack: this fix only makes sense when
# systemd-resolved owns DNS. A build that cannot bake the fix must fail so it is
# caught before publication, not silently no-op.
if [[ ! -d /run/systemd/system ]] || ! systemctl cat systemd-resolved.service >/dev/null 2>&1; then
    echo "ERROR: systemd-resolved is not present; unsupported resolver stack for an AWS range guest" >&2
    exit 1
fi

mkdir -p "$DROPIN_DIR"
printf '[Resolve]\nFallbackDNS=%s\n' "$FALLBACK_DNS" >"$DROPIN_FILE"
echo "Wrote ${DROPIN_FILE}:"
cat "$DROPIN_FILE"

# Enable resolved at boot and pick up the drop-in now.
systemctl enable systemd-resolved
systemctl restart systemd-resolved

# Assert /etc/resolv.conf is the systemd-resolved stub (127.0.0.53). If the
# image is not using the stub resolver the FallbackDNS drop-in is inert and the
# durable fix would silently not apply.
resolv_target="$(readlink -f /etc/resolv.conf || true)"
if ! printf '%s' "$resolv_target" | grep -qE 'stub-resolv\.conf|systemd/resolve' &&
    ! grep -q '127.0.0.53' /etc/resolv.conf; then
    echo "ERROR: /etc/resolv.conf is not the systemd-resolved stub (127.0.0.53)" >&2
    cat /etc/resolv.conf >&2 || true
    exit 1
fi

# Assert the fallback is registered in the running resolver. Capture the status
# once and match with a here-string: `resolvectl status | grep -q` lets grep
# close the pipe on its first match, so resolvectl takes SIGPIPE writing its
# remaining sections and, under `set -o pipefail`, the pipeline fails even though
# the fallback IS registered (#1782).
if command -v resolvectl >/dev/null 2>&1; then
    resolved_status="$(resolvectl status)"
    if ! grep -q "$FALLBACK_DNS" <<<"$resolved_status"; then
        echo "ERROR: FallbackDNS ${FALLBACK_DNS} not registered with systemd-resolved" >&2
        printf '%s\n' "$resolved_status" >&2 || true
        exit 1
    fi
fi

# Prove real resolution works through the system resolver during the bake.
if ! getent ahosts "$PROBE_HOST" >/dev/null; then
    echo "ERROR: system resolver could not resolve ${PROBE_HOST} during bake" >&2
    exit 1
fi

echo "=== systemd-resolved AmazonProvidedDNS fallback baked and verified ==="
