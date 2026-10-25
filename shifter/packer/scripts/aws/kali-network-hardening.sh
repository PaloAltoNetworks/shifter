#!/bin/bash
# AWS-only: make the Kali range-guest AMI boot a single, name-matched network
# stack and always have SSH host keys, so a freshly provisioned guest brings up
# its NIC and binds :22 well inside the provisioner's management-SSH window
# (#1826). Mirrors the GCE Kali fix (scripts/kali/gce-debian-to-kali.sh); kept in
# scripts/aws/ because the GCP templates must not consume it (same rule as
# scripts/aws/linux-resolved-dns.sh).
#
# Root causes this fixes on a fresh AWS launch of the baked Kali image:
#   1. cloud-init bakes /etc/netplan/50-cloud-init.yaml pinned to the BAKE-TIME
#      NIC MAC. On any new instance the MAC differs, so netplan never configures
#      the primary NIC, and NetworkManager + systemd-networkd then race for it --
#      DNS/SSM are flaky and the link is unreliable.
#   2. common/cleanup.sh strips /etc/ssh/ssh_host_* so images never ship shared
#      host keys, but Kali (unlike Ubuntu) does not regenerate them on first boot,
#      so ssh.service cannot start and the guest never binds :22.
#
# Fix: systemd-networkd as the SOLE stack with a static DHCP config matched by
# interface NAME (not MAC), cloud-init network config disabled so it cannot
# re-render a MAC-pinned netplan, a oneshot that regenerates missing host keys
# before sshd, and a bounded networkd-wait-online so an isolated range LAN cannot
# hang boot.
set -euo pipefail

echo "=== AWS Kali: single systemd-networkd stack, name-matched (not MAC) ==="
# Mask the competing stacks so neither contends for the primary NIC nor gets
# selected as a network backend. Masking (not purging) leaves the desktop
# metapackage's NetworkManager dependency satisfied; it simply never runs at boot.
systemctl mask networking.service || true
systemctl mask NetworkManager.service NetworkManager-wait-online.service || true
systemctl enable systemd-networkd.service || true
systemctl enable ssh.service || true

mkdir -p /etc/systemd/network
cat > /etc/systemd/network/20-primary.network <<'NET'
# Primary NIC. DHCP supplies the address, MTU and routes. Match by interface NAME
# (Kali names it eth0; e* also covers predictable names ens5/enp* if a future
# base changes it) so this applies on every instance regardless of MAC.
[Match]
Name=e*

[Network]
DHCP=yes

[DHCPv4]
UseMTU=true
UseRoutes=true
NET

echo "=== Disabling cloud-init network rendering (it pins the NIC by bake MAC) ==="
# Stop cloud-init from writing /etc/netplan/50-cloud-init.yaml on boot; the static
# networkd config above owns the NIC. Remove the stale bake-time netplan so it
# cannot be applied by any renderer.
mkdir -p /etc/cloud/cloud.cfg.d
printf 'network: {config: disabled}\n' > /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg
rm -f /etc/netplan/50-cloud-init.yaml

echo "=== Regenerating SSH host keys on first boot (cleanup.sh strips them) ==="
cat > /etc/systemd/system/regenerate-ssh-host-keys.service <<'UNIT'
[Unit]
Description=Regenerate missing SSH host keys before sshd starts
Before=ssh.service ssh.socket
ConditionPathExists=!/etc/ssh/ssh_host_ed25519_key

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/ssh-keygen -A

[Install]
WantedBy=multi-user.target
UNIT
systemctl enable regenerate-ssh-host-keys.service || true

echo "=== Bounding systemd-networkd-wait-online so an isolated range LAN cannot hang boot ==="
mkdir -p /etc/systemd/system/systemd-networkd-wait-online.service.d
cat > /etc/systemd/system/systemd-networkd-wait-online.service.d/10-range-guest.conf <<'UNIT'
[Service]
TimeoutStartSec=30
UNIT

echo "=== AWS Kali network hardening complete ==="
