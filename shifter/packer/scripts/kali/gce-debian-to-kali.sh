#!/bin/bash
# Convert a Google debian-12 GCE base image into Kali Rolling, in place.
#
# GCP publishes no Kali image, and the official Kali genericcloud disk is not
# GCE-bootable: it lacks Google's guest environment (no google-guest-agent, so
# no metadata-based SSH-key injection, and no GCE network setup), which means
# packer can never connect. Building on Google's debian-12 base keeps that guest
# environment intact and layers Kali on top via Kali's official apt repository,
# so the IAP/SSH build path behaves exactly like the ubuntu builder.
#
# The Kali repos do NOT carry google-guest-agent, so a naive full-upgrade would
# strip it and reproduce the no-SSH failure in the published image. This script
# re-asserts Google's guest-environment apt repo and reinstalls the agents after
# the conversion so the captured image stays GCE-native.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

echo "=== Prerequisites ==="
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl gnupg

echo "=== Adding Kali official apt repository + keyring ==="
# --proto =https restricts the transfer to HTTPS; no -L (the keyring is served
# directly, so following redirects -- and risking an HTTPS->HTTP downgrade -- is
# neither needed nor wanted).
curl -fsS --proto =https https://archive.kali.org/archive-keyring.gpg \
  -o /usr/share/keyrings/kali-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/kali-archive-keyring.gpg] http://http.kali.org/kali kali-rolling main contrib non-free non-free-firmware" \
  > /etc/apt/sources.list.d/kali.list
# Track Kali Rolling as the system distro: drop the Debian suite lists so the
# full-upgrade below moves the whole base onto Kali.
rm -f /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources

echo "=== Pinning the Google guest environment so the conversion keeps it ==="
curl -fsS --proto =https https://packages.cloud.google.com/apt/doc/apt-key.gpg \
  | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg
echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt google-compute-engine-bookworm-stable main" \
  > /etc/apt/sources.list.d/google-compute-engine.list

echo "=== Pinning the Debian signed boot chain so GCE Secure Boot keeps working ==="
# GCE range guests boot as Shielded VMs with Secure Boot ON. The debian-12 base
# ships an MS-signed shim + signed GRUB + signed kernel; a naive full-upgrade to
# kali-rolling swaps in Kali's unsigned boot chain and the guest then fails at
# firmware ("BdsDxe: failed to load ... Security Violation"). Keep the signed
# Debian boot packages held so Kali *userland* layers on top while the signed
# EFI shim/GRUB and a signed kernel stay Debian's -- the same reason polaris-vm
# (also a debian-12 base that never rewrites its boot chain) boots clean.
apt-get install -y --no-install-recommends shim-signed grub-efi-amd64-signed
# The GCE debian-12 base ships a *cloud* kernel (linux-image-cloud-amd64 plus a
# concrete linux-image-<ver>-cloud-amd64), not linux-image-amd64, so hold only
# packages that are actually installed -- apt-mark errors (and set -e aborts the
# bake) on a package name that does not exist on this base.
BOOT_CANDIDATES="shim-signed grub-efi-amd64-signed grub-efi-amd64-bin grub-common grub2-common"
BOOT_CANDIDATES="$BOOT_CANDIDATES $(dpkg-query -W -f='${Package}\n' 'linux-image-*' 'linux-headers-*' 2>/dev/null | grep -E 'linux-(image|headers)-(cloud-amd64|[0-9])' || true)"
BOOT_HOLDS=""
for pkg in $BOOT_CANDIDATES; do
  if dpkg-query -W -f='${Status}\n' "$pkg" 2>/dev/null | grep -q 'install ok installed'; then
    BOOT_HOLDS="$BOOT_HOLDS $pkg"
  fi
done
apt-mark hold $BOOT_HOLDS

echo "=== Upgrading the base into Kali Rolling ==="
# The debian-12 (pre-t64) -> kali-rolling (post-t64) jump crosses the 64-bit
# time_t library transition, where the new tNN library packages ship files that
# still belong to the old pre-transition packages ("trying to overwrite
# .../libcurl-gnutls.so.4.8.0, which is also in package libcurl3-gnutls").
# --force-overwrite is the documented way through that transition: run the
# upgrade forcing the overwrites, repair any partial dpkg state, settle
# dependencies, then re-run the upgrade which must now complete cleanly.
apt-get update
apt-get -y \
  -o Dpkg::Options::="--force-confnew" \
  -o Dpkg::Options::="--force-confdef" \
  -o Dpkg::Options::="--force-overwrite" \
  full-upgrade || true
dpkg --configure -a --force-overwrite || true
apt-get -y -o Dpkg::Options::="--force-overwrite" --fix-broken install
apt-get -y \
  -o Dpkg::Options::="--force-confnew" \
  -o Dpkg::Options::="--force-confdef" \
  -o Dpkg::Options::="--force-overwrite" \
  full-upgrade

echo "=== Reinstalling the Google guest environment (Kali repos omit it) ==="
# google-compute-engine pulls google-guest-configs, which owns the GCE
# systemd-networkd interface config + udev rules; without it the guest has no
# working network manager once ifupdown is out of the way.
apt-get install -y google-guest-agent google-osconfig-agent google-compute-engine \
  || apt-get install -y google-guest-agent google-osconfig-agent
systemctl enable google-guest-agent.service || true
systemctl enable google-osconfig-agent.service || true

echo "=== GCE-native networking: single systemd-networkd stack for Kali guests ==="
# The debian-12 base uses systemd-networkd, but the Kali metapackages
# (kali-linux-headless via tools.sh, kali-desktop-xfce via base.sh, installed
# later in this bake) pull in ifupdown AND NetworkManager -- giving the image
# THREE competing network stacks. On a GCE guest that breaks boot two ways:
#   1. ifupdown's networking.service blocks boot for its ~5-minute timeout
#      raising interfaces systemd-networkd already owns; and
#   2. NetworkManager races systemd-networkd for the primary NIC, and neither
#      brings the link up quickly enough for google-guest-agent. The 2.x agent's
#      instance_setup reaches the metadata server (169.254.169.254) within a
#      ~10-second retry window at boot; when the NIC is not up in time the agent
#      fails, DESTRUCTIVELY "rolls back" the network config (tearing the link
#      down), and restart-loops forever. Because the agent provides the oslogin
#      NSS module it is ordered Before nss-user-lookup.target, so its loop blocks
#      nss-user-lookup.target and therefore ssh.service -- the range guest never
#      binds :22 and the provisioner's management SSH times out (300s).
# Fix: make systemd-networkd the SOLE stack and give it a static DHCP config for
# the primary NIC, so the link -- and the DHCP option-121 route to the metadata
# server -- comes up in ~2s, well inside the guest-agent's window, exactly like
# the stock GCE debian image. Mask ifupdown + NetworkManager so they cannot
# contend or be selected as the guest-agent's network backend. Kali names the
# NIC eth0 (not ens4), so match e* to cover both. Masking (not purging) leaves
# the desktop metapackage's NetworkManager dependency satisfied for the xrdp GUI;
# NetworkManager simply never runs as a boot service.
systemctl mask networking.service || true
systemctl mask NetworkManager.service NetworkManager-wait-online.service || true
systemctl enable systemd-networkd.service || true
systemctl enable ssh.service || true

mkdir -p /etc/systemd/network
cat > /etc/systemd/network/20-gce-primary.network <<'NET'
# GCE primary NIC. DHCP supplies the address, MTU (1460) and -- via option 121 --
# the route to the metadata server 169.254.169.254, so google-guest-agent reaches
# the MDS on its first attempt. Kali names the primary NIC eth0; match e* so this
# also covers predictable names (ens4/enp*) if a future base changes it.
[Match]
Name=e*

[Network]
DHCP=yes

[DHCPv4]
UseMTU=true
UseRoutes=true
NET

echo "=== Bounding systemd-networkd-wait-online so a range LAN cannot hang boot ==="
# Range guests sit on switched, sometimes-isolated range LANs whose gateway may
# not be a real router, so the link can come up with an address yet never reach
# the full "routable" state systemd-networkd-wait-online waits for. Cap the wait
# at 30s so a failed/incomplete online check fails the oneshot instead of hanging
# boot; multi-user.target (and ssh.service) then always proceeds. sshd orders only
# after network.target, and the guest-agent needs only the DHCP-provided MDS route
# (present regardless of "routable" state), so bounded network-online is safe.
mkdir -p /etc/systemd/system/systemd-networkd-wait-online.service.d
cat > /etc/systemd/system/systemd-networkd-wait-online.service.d/10-range-guest.conf <<'UNIT'
[Service]
TimeoutStartSec=30
UNIT

echo "=== Ensuring SSH host keys are regenerated on first boot ==="
# common/cleanup.sh strips /etc/ssh/ssh_host_* so images never ship shared host
# keys. The Ubuntu image regenerates them on first boot; Kali does not, so
# ssh.service cannot start (no host keys) and never binds :22 — the range guest
# looks unreachable and the provisioner's SSH-wait times out (#1745). Install a
# oneshot that runs `ssh-keygen -A` before sshd on any boot missing host keys,
# so a freshly provisioned Kali guest generates per-instance keys and sshd comes
# up on :22.
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

echo "=== Creating the kali user (Kali scripts and xrdp expect it) ==="
if ! id kali >/dev/null 2>&1; then
  useradd -m -s /bin/bash kali
  echo 'kali:kali' | chpasswd
  usermod -aG sudo kali
fi

echo "=== Verifying the signed boot chain survived the conversion ==="
# Fail the bake loudly rather than publish an image that cannot boot under
# Secure Boot. shim-signed + grub-efi-amd64-signed own the MS-signed EFI
# binaries; a signed Debian kernel must remain installed for GRUB to load it.
for pkg in shim-signed grub-efi-amd64-signed; do
  # Held packages report "hold ok installed" (not "install ok installed"), so
  # match the trailing "ok installed" to accept both states.
  dpkg-query -W -f='${Status}\n' "$pkg" 2>/dev/null | grep -q "ok installed" \
    || { echo "FATAL: $pkg missing after conversion; image would fail Secure Boot" >&2; exit 1; }
done
dpkg-query -W -f='${Package}\n' 'linux-image-*-amd64' 2>/dev/null | grep -qE 'linux-image-[0-9].*-amd64' \
  || { echo "FATAL: no concrete signed Debian kernel remains after conversion" >&2; exit 1; }

echo "=== Debian -> Kali Rolling conversion complete ==="
