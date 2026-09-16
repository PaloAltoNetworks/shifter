#!/bin/bash
# Generate an SBOM from a candidate-image disk without executing candidate code.
#
# This script runs as root on a disposable, credentialless Ubuntu scanner VM.
# The workflow attaches the exact candidate-derived disk in GCE read-only mode,
# then supplies a source-pinned Syft binary from the trusted runner. The mount is
# read-only/noexec/nosuid/nodev and the SBOM is written to the scanner boot disk.
set -euo pipefail

DEVICE_LINK="${DEVICE_LINK:-/dev/disk/by-id/google-shifter-candidate}"
SYFT_PATH="${SYFT_PATH:-/tmp/syft}"
OUTPUT_PATH="${OUTPUT_PATH:-/tmp/guest-sbom.spdx.json}"
MOUNT_ROOT="${MOUNT_ROOT:-/mnt/shifter-candidate}"

[[ -x "${SYFT_PATH}" ]] || { echo "scanner: trusted Syft binary is unavailable" >&2; exit 1; }

for _ in $(seq 1 30); do
  [[ -e "${DEVICE_LINK}" ]] && break
  sleep 2
done
[[ -e "${DEVICE_LINK}" ]] || { echo "scanner: candidate disk did not appear" >&2; exit 1; }

device="$(readlink -f "${DEVICE_LINK}")"
[[ "$(blockdev --getro "${device}")" == "1" ]] \
  || { echo "scanner: candidate disk is not attached read-only" >&2; exit 1; }

mapfile -t selected < <(
  lsblk -b -J -o PATH,TYPE,SIZE,FSTYPE,RO "${device}" \
    | python3 -c '
import json
import sys

def walk(nodes):
    for node in nodes:
        yield node
        yield from walk(node.get("children", []))

document = json.load(sys.stdin)
supported = {"ext4", "xfs", "btrfs", "ntfs"}
candidates = [
    node
    for node in walk(document.get("blockdevices", []))
    if str(node.get("fstype", "")).lower() in supported
    and bool(node.get("ro"))
    and node.get("path")
]
if not candidates:
    raise SystemExit("scanner: no supported read-only filesystem found on candidate disk")
selected = max(candidates, key=lambda node: int(node.get("size") or 0))
print(selected["path"])
print(str(selected["fstype"]).lower())
'
)
[[ "${#selected[@]}" -eq 2 ]] \
  || { echo "scanner: candidate filesystem selection failed" >&2; exit 1; }
scan_device="${selected[0]}"
filesystem="${selected[1]}"
[[ "$(blockdev --getro "${scan_device}")" == "1" ]] \
  || { echo "scanner: selected candidate filesystem is not read-only" >&2; exit 1; }

install -d -m 0700 "${MOUNT_ROOT}"
cleanup() {
  mountpoint -q "${MOUNT_ROOT}" && umount "${MOUNT_ROOT}" || true
}
trap cleanup EXIT

mount_options="ro,nosuid,nodev,noexec"
if [[ "${filesystem}" == "ntfs" ]]; then
  modprobe ntfs3 2>/dev/null || true
  grep -qw ntfs3 /proc/filesystems \
    || { echo "scanner: trusted scanner kernel has no NTFS read-only support" >&2; exit 1; }
  mount -t ntfs3 -o "${mount_options}" "${scan_device}" "${MOUNT_ROOT}"
else
  mount -o "${mount_options}" "${scan_device}" "${MOUNT_ROOT}"
fi

actual_options=",$(findmnt -n -o OPTIONS --target "${MOUNT_ROOT}"),"
for required in ro nosuid nodev noexec; do
  [[ "${actual_options}" == *",${required},"* ]] \
    || { echo "scanner: candidate mount is missing ${required}" >&2; exit 1; }
done

rm -f "${OUTPUT_PATH}"
"${SYFT_PATH}" scan "dir:${MOUNT_ROOT}" -o "spdx-json=${OUTPUT_PATH}"
[[ -s "${OUTPUT_PATH}" ]] || { echo "scanner: Syft produced no SBOM" >&2; exit 1; }
chmod 0600 "${OUTPUT_PATH}"
if [[ -n "${SUDO_USER:-}" ]]; then
  chown "${SUDO_USER}" "${OUTPUT_PATH}"
fi
