#!/usr/bin/env bash
# Configure cloud-init for GDC VM Runtime (GCP guest images only).
#
# GDC VM Runtime delivers each guest's cloud-init userData via the NoCloud
# datasource (a "cidata" seed built from the VirtualMachine
# cloudInit.noCloud.secretRef userData). The GCE base images
# (ubuntu-os-cloud / GCE Debian -> Kali) ship cloud-init locked to the GCE
# datasource, whose metadata server (169.254.169.254) does not exist on the
# isolated range L2 segment. The guest therefore logs "No instance datasource
# found!" and applies none of the range userData (the Ed25519 host key,
# authorized_keys, or the first-boot setup script), which breaks guest setup.
#
# Force NoCloud first so GDC guests consume the range userData. This is
# GCP-only and is intentionally NOT added to the shared cleanup script, because
# AWS images must keep their Ec2 datasource.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

# cloud-init is what applies the GDC NoCloud userData (host key, authorized_keys,
# first-boot setup script). The shared cleanup step runs `apt-get autoremove`,
# which strips cloud-init from the GCE Debian->Kali image (it is an orphanable
# dependency there, though not on ubuntu-os-cloud) -- so the Kali guest would
# otherwise never run cloud-init at all. Ensure it is present and pinned as a
# manually-installed package so a later autoremove cannot take it out again.
if ! command -v cloud-init >/dev/null 2>&1; then
  apt-get update
  apt-get install -y cloud-init
  apt-get clean
  rm -rf /var/lib/apt/lists/*
fi
apt-mark manual cloud-init >/dev/null 2>&1 || true

cat > /etc/cloud/cloud.cfg.d/99-shifter-gdc-datasource.cfg <<'CFG'
# Shifter GDC VM Runtime guests boot from a NoCloud seed (cidata) built from
# the VirtualMachine cloudInit.noCloud.secretRef userData. Probe NoCloud first;
# keep GCE/None as fallbacks so the image still boots cleanly off GDC.
datasource_list: [ NoCloud, ConfigDrive, GCE, None ]
CFG

# Re-arm cloud-init so the range VM performs a full first-boot run (datasource
# detection + module application, including the injected ssh_keys host key)
# instead of treating the baked image's cached instance-id as already
# provisioned. Run last so no cloud-init state is recreated before capture.
cloud-init clean --logs --seed
