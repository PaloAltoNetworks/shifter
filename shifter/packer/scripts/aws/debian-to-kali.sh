#!/bin/bash
# AWS-only: convert the official Debian 12 AMI into Kali Rolling, in place (#2459).
#
# The AWS Kali range image used to start from the AWS Marketplace Kali AMI. AWS
# cannot export an image derived from a Marketplace product, and such an AMI can
# never be made public, so it cannot be published for reuse like the GCE base
# images. Debian publishes its official AMIs directly (no product code), so this
# bake starts there and layers Kali on top through Kali's official apt
# repository -- the same approach as the GCE path
# (scripts/kali/gce-debian-to-kali.sh), kept separate because that script pins
# Google's guest environment and GCE Secure Boot chain, neither of which applies
# here. Kept in scripts/aws/ so GCP templates cannot consume it.
#
# Base facts this script relies on (debian-12-amd64 AMI, verified on EC2):
#   - networking: systemd-networkd + netplan rendered by cloud-init; the later
#     scripts/aws/kali-network-hardening.sh makes networkd the sole stack.
#   - resolver: systemd-resolved, but /etc/resolv.conf points at the NON-stub
#     file; scripts/aws/linux-resolved-dns.sh requires the 127.0.0.53 stub.
#   - boot: legacy BIOS on EC2, booting a GRUB core image written to the BIOS
#     boot partition when Debian built the image (grub-pc is not installed as a
#     package; grub-efi-amd64-signed + shim-signed are). Upgrading GRUB's modules
#     without reinstalling that core image breaks boot, so the installed GRUB/shim
#     packages are held. The kernel is allowed to move to Kali's cloud kernel.
#   - default cloud-init user: admin (scripts/kali/base.sh switches it to kali).
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
echo "deb [signed-by=/usr/share/keyrings/kali-archive-keyring.gpg] https://http.kali.org/kali kali-rolling main contrib non-free non-free-firmware" \
  > /etc/apt/sources.list.d/kali.list
# Track Kali Rolling as the system distro: drop the Debian suite lists (and the
# Debian CDN mirror lists they reference) so the upgrade moves the whole base.
rm -f /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources
rm -rf /etc/apt/mirrors

echo "=== Holding the installed boot loader so the BIOS core image stays consistent ==="
BOOT_CANDIDATES="shim-signed grub-efi-amd64-signed grub-efi-amd64-bin grub-efi-amd64 grub-pc grub-pc-bin grub-common grub2-common"
BOOT_HOLDS=""
for pkg in $BOOT_CANDIDATES; do
  # Hold only packages that are installed: apt-mark errors on unknown names.
  if dpkg-query -W -f='${Status}\n' "$pkg" 2>/dev/null | grep -q 'install ok installed'; then
    BOOT_HOLDS="$BOOT_HOLDS $pkg"
  fi
done
if [[ -z "$BOOT_HOLDS" ]]; then
  echo "FATAL: no installed GRUB package found on the Debian base" >&2
  exit 1
fi
# shellcheck disable=SC2086 # word splitting intended: one argument per package
apt-mark hold $BOOT_HOLDS

echo "=== Upgrading the base into Kali Rolling ==="
# The debian-12 (pre-t64) -> kali-rolling (post-t64) jump crosses the 64-bit
# time_t library transition, where new tNN library packages ship files still
# owned by the old ones. --force-overwrite is the documented way through it:
# upgrade forcing the overwrites, repair partial dpkg state, settle
# dependencies, then re-run the upgrade, which must now complete cleanly.
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

echo "=== Ensuring the AWS guest environment survived the conversion ==="
# cloud-init (instance bootstrap + per-range user data), the cloud kernel
# (ENA/NVMe drivers), sshd, and systemd-resolved are all required on a range
# guest; reinstall from Kali Rolling if the upgrade dropped any of them.
apt-get install -y cloud-init cloud-guest-utils linux-image-cloud-amd64 openssh-server systemd-resolved
# cloud-init's stage units changed across releases (24.3 split cloud-init.service
# into cloud-init-main/cloud-init-network), so enable whichever the installed
# version ships, then require the final stage that runs per-range user data.
for unit in cloud-init-local.service cloud-init-main.service cloud-init-network.service \
  cloud-init.service cloud-config.service cloud-final.service; do
  if [[ -n "$(systemctl list-unit-files --no-legend "$unit")" ]]; then
    systemctl enable "$unit"
  fi
done
if ! systemctl is-enabled --quiet cloud-final.service; then
  echo "FATAL: cloud-init final stage is not enabled after conversion" >&2
  exit 1
fi
systemctl enable ssh.service systemd-resolved.service

echo "=== Regenerating the GRUB config for the installed kernels ==="
# The held grub-common still owns update-grub; regenerate explicitly so the
# config lists the Kali cloud kernel regardless of hook ordering.
update-grub

echo "=== Pointing /etc/resolv.conf at the systemd-resolved stub ==="
# The Debian AMI links the non-stub file; the AWS resolver fallback
# (scripts/aws/linux-resolved-dns.sh) verifies the 127.0.0.53 stub.
ln -sf ../run/systemd/resolve/stub-resolv.conf /etc/resolv.conf

echo "=== Creating the kali user (Kali scripts and xrdp expect it) ==="
# No password is baked into the image (#762): the account stays without a usable
# password until per-range user data sets one.
if ! id kali >/dev/null 2>&1; then
  useradd -m -s /bin/bash kali
fi
usermod -aG sudo kali

echo "=== Verifying the converted base ==="
. /etc/os-release
if [[ "${ID:-}" != "kali" ]]; then
  echo "FATAL: /etc/os-release reports ID=${ID:-unset}, not kali" >&2
  exit 1
fi
for pkg in $BOOT_HOLDS; do
  # Held packages report "hold ok installed"; accept both states.
  dpkg-query -W -f='${Status}\n' "$pkg" 2>/dev/null | grep -q "ok installed" \
    || { echo "FATAL: boot package $pkg missing after conversion" >&2; exit 1; }
done
dpkg-query -W -f='${Package}\n' 'linux-image-*-cloud-amd64' 2>/dev/null | grep -qE 'linux-image-[0-9].*-cloud-amd64' \
  || { echo "FATAL: no concrete cloud kernel installed after conversion" >&2; exit 1; }
[[ -f /boot/grub/grub.cfg ]] || { echo "FATAL: /boot/grub/grub.cfg missing" >&2; exit 1; }

echo "=== Debian -> Kali Rolling conversion complete ==="
