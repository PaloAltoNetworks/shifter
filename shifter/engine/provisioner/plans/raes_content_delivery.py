"""Setup plans delivering source-backed RAES guest content bytes (#1564).

Post-boot delivery of a source-backed ``file``/``directory`` content item, over
the same authenticated guest transport ``plans.raes_active_directory`` uses for
directory realization.

The payload never travels inside a script. The deliver step streams the local,
already digest-verified payload file as raw bytes on the guest command's stdin
(``SetupStep.stdin_path``), with constant provisioner memory and no fixed size
cap (ADR-032-R9); the only bounds are the exact byte count and the destination's
free space, which the guest checks before writing.

- **Linux**: ``GuestSSHExecutor`` carries the script base64-encoded in argv to a
  privileged child shell, so stdin is a pure data channel. Runtime values
  (target, digest, size, mode) are rendered into the script text via ``{{ }}``
  substitution (shell-quoted where they are paths or identifiers), and the
  script copies stdin into a private staging file.
- **Windows**: the script travels via ``-EncodedCommand`` and every runtime
  value stays off argv (out of guest process listings / Event ID 4688): stdin
  carries four base64 header lines (target, digest, sensitivity, size) read
  byte-wise from the raw standard-input stream, then the raw payload, copied
  from that same stream into a private staging file.

A directory payload is the deterministic uncompressed tar
``shared.raes.content_delivery._materialize_directory`` produces; the guest
lists it before extracting and fails closed on any symlink, absolute path, or
``..`` traversal entry (defense in depth: the server-side materializer already
excludes symlinks and validates every input against a digest-bound inventory,
but the guest does not trust that invariant blindly).

Each install step performs its own pre-install digest check (fail closed
before any mutation beyond a private staging file) and prints a fixed marker
on success. The staging archive for a ``directory`` payload is written to a
per-invocation, exclusively-created random path (``mktemp`` / a fresh guid --
never a fixed, predictable sibling name) and removed immediately after
extraction, so an unprivileged process cannot pre-plant a symlink at a known
location and have this step's own write silently overwrite an unrelated file
through it (the tar dialects' ``file`` staging already had this property; the
``directory`` dialects previously did not).

The dedicated ``verify_step`` is a genuine second round trip that re-reads the
*realized artifact itself*, fresh from disk, and fails closed on a missing or
mismatched digest -- this is what
``raes_content_delivery.realize_raes_content_delivery`` treats as the
authoritative in-guest readback gating ``publish_ready``:

- for ``file``, the installed file's own bytes;
- for ``directory``, a deterministic digest of the *installed tree* -- every
  regular file under the destination, walked fresh and hashed by the guest,
  combined in sorted-relative-path order -- never the retained staging tar.
  Hashing the tar only proves the archive *received* was intact before
  extraction; it cannot detect an install that later dropped, altered, or
  misplaced a member, or a destination tampered with between the deliver and
  verify round trips. The expected installed-tree digest is computed
  server-side, once, from the same already downloaded-and-verified tar bytes
  (``raes_content_payload.installed_tree_sha256``), so no new wire/DB
  contract is needed -- it rides down to the guest as an ordinary runtime
  value alongside the existing tar-bytes ``sha256``.
"""

from __future__ import annotations

import base64
import re
import shlex
from dataclasses import dataclass
from typing import Any

from ._raes_content_delivery_scripts import (
    WINDOWS_DELIVER_DIRECTORY_SCRIPT,
    WINDOWS_DELIVER_FILE_SCRIPT,
    WINDOWS_VERIFY_DIRECTORY_SCRIPT,
    WINDOWS_VERIFY_FILE_SCRIPT,
)
from .base import SetupStep

_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DELIVER_TIMEOUT_FLOOR_SECONDS = 600
_LINUX_FILE_MODES = frozenset({"600", "644", "755"})

# ---------------------------------------------------------------------------
# Linux (bash) -- every value is rendered directly into the static script text
# via {{ }} substitution (shell-quoted where it is a path/identifier); the
# payload arrives as raw bytes on stdin. See the module docstring.
# ---------------------------------------------------------------------------

# Fails closed before writing when the destination filesystem cannot hold
# ``$2`` bytes (POSIX ``df -Pk``: available KiB is field 4 of line 2).
_LINUX_REQUIRE_FREE_SPACE = r"""
raes_require_free_space() {
    local avail_kib required_kib
    avail_kib=$(df -Pk -- "$1" | awk 'NR == 2 {print $4}')
    required_kib=$(( ($2 + 1023) / 1024 ))
    if [ -z "$avail_kib" ] || [ "$avail_kib" -lt "$required_kib" ]; then
        echo "FATAL: RAES content delivery destination lacks free space" >&2
        exit 1
    fi
}
"""

# Streams the raw payload from stdin into a private staging file and checks its
# exact size and digest before anything is published.
_LINUX_RECEIVE_PAYLOAD = r"""
cat > "$staging"
actual_bytes=$(stat -c %s -- "$staging")
if [ "$actual_bytes" != "$expected_bytes" ]; then
    echo "FATAL: RAES content delivery size mismatch" >&2
    exit 1
fi
actual_sha256=$(sha256sum -- "$staging" | awk '{print $1}')
if [ "$actual_sha256" != "$expected_sha256" ]; then
    echo "FATAL: RAES content delivery digest mismatch" >&2
    exit 1
fi
"""

LINUX_DELIVER_FILE_SCRIPT = (
    r"""#!/bin/bash
set -euo pipefail
target_path={{ raes_target_quoted }}
expected_sha256={{ raes_sha256_quoted }}
expected_bytes={{ raes_byte_count }}
file_mode={{ raes_mode_quoted }}
"""
    + _LINUX_REQUIRE_FREE_SPACE
    + r"""
parent_dir=$(dirname -- "$target_path")
mkdir -p -- "$parent_dir"
raes_require_free_space "$parent_dir" "$expected_bytes"
staging=$(mktemp -- "${parent_dir}/.raes-content.XXXXXX")
trap 'rm -f -- "$staging"' EXIT
"""
    + _LINUX_RECEIVE_PAYLOAD
    + r"""
chmod "$file_mode" -- "$staging"
mv -f -- "$staging" "$target_path"
trap - EXIT
echo "RAES_CONTENT_FILE_INSTALLED"
"""
)

LINUX_VERIFY_FILE_SCRIPT = r"""#!/bin/bash
set -euo pipefail
target_path={{ raes_target_quoted }}
expected_sha256={{ raes_sha256_quoted }}

if [ -L "$target_path" ] || [ ! -f "$target_path" ]; then
    echo "FATAL: RAES content delivery target is missing" >&2
    exit 1
fi
actual_sha256=$(sha256sum -- "$target_path" | awk '{print $1}')
if [ "$actual_sha256" != "$expected_sha256" ]; then
    echo "FATAL: RAES content delivery readback digest mismatch" >&2
    exit 1
fi
echo "RAES_CONTENT_FILE_VERIFIED"
"""

_LINUX_TAR_SAFETY_CHECK = r"""
# `-f` takes the very next token as its argument regardless of `--`, so `--`
# cannot precede the filename here (it would become tar's `-f` value, not a
# "no more options" marker) -- $tar_staging is always the deterministic,
# already-validated-absolute staging path, never author-controlled.
if tar -tvf "$tar_staging" 2>/dev/null | grep -Eq '^l'; then
    rm -f -- "$tar_staging"
    echo "FATAL: RAES content delivery archive contains a symlink entry" >&2
    exit 1
fi
if tar -tf "$tar_staging" | grep -Eq '(^/)|(^\.\./)|(/\.\./)|(/\.\.$)|(^\.\.$)'; then
    rm -f -- "$tar_staging"
    echo "FATAL: RAES content delivery archive contains an unsafe path" >&2
    exit 1
fi
"""

LINUX_DELIVER_DIRECTORY_SCRIPT = (
    r"""#!/bin/bash
set -euo pipefail
destination={{ raes_target_quoted }}
expected_sha256={{ raes_sha256_quoted }}
expected_bytes={{ raes_byte_count }}
destination="${destination%/}"
"""
    + _LINUX_REQUIRE_FREE_SPACE
    + r"""
parent_dir=$(dirname -- "$destination")
mkdir -p -- "$parent_dir"
# The staged archive and its extraction coexist until publish.
raes_require_free_space "$parent_dir" $(( expected_bytes * 2 ))
# An exclusively-created, unpredictable staging path (mktemp, like the file
# dialect) -- never a fixed sibling name an unprivileged process could pre-plant
# as a symlink ahead of this write. It is removed by this same step right after
# extraction; verify_step proves the *installed tree*, so it never needs to
# relocate this (or any) retained archive.
staging=$(mktemp -- "${parent_dir}/.raes-content-staging.XXXXXX")
tar_staging="$staging"
trap 'rm -f -- "$staging"' EXIT
"""
    + _LINUX_RECEIVE_PAYLOAD
    + _LINUX_TAR_SAFETY_CHECK
    + r"""
extract_dir=$(mktemp -d -- "${parent_dir}/.raes-content-extract.XXXXXX")
tar -xf "$tar_staging" -C "$extract_dir"
rm -rf -- "$destination"
mv -T -- "$extract_dir" "$destination"
echo "RAES_CONTENT_DIRECTORY_INSTALLED"
"""
)

LINUX_VERIFY_DIRECTORY_SCRIPT = r"""#!/bin/bash
set -euo pipefail
destination={{ raes_target_quoted }}
expected_tree_sha256={{ raes_tree_sha256_quoted }}
destination="${destination%/}"

if [ -L "$destination" ] || [ ! -d "$destination" ]; then
    echo "FATAL: RAES content delivery destination is missing" >&2
    exit 1
fi

# Deterministic installed-tree manifest: every regular file under $destination
# (symlinks are never followed and never counted as "type f"), sorted by
# byte-value path order (LC_ALL=C), each contributing one
# "<sha256>  <relpath>\n" line -- mirrors
# raes_content_payload.installed_tree_sha256 exactly, so the server-computed
# expected value and this fresh guest readback are directly comparable. Any
# extraction that dropped, altered, added, or misplaced a member changes this
# digest, unlike hashing a retained copy of the original archive.
manifest=""
while IFS= read -r -d '' rel; do
    file_sha256=$(sha256sum -- "$destination/$rel" | awk '{print $1}')
    manifest="${manifest}${file_sha256}  ${rel}
"
done < <(cd "$destination" && find . -type f -print0 | sed -z 's#^\./##' | LC_ALL=C sort -z)

actual_tree_sha256=$(printf '%s' "$manifest" | sha256sum | awk '{print $1}')
if [ "$actual_tree_sha256" != "$expected_tree_sha256" ]; then
    echo "FATAL: RAES content delivery readback digest mismatch" >&2
    exit 1
fi
echo "RAES_CONTENT_DIRECTORY_VERIFIED"
"""

_SCRIPTS: dict[tuple[str, str], dict[str, str]] = {
    ("linux", "file"): {"deliver": LINUX_DELIVER_FILE_SCRIPT, "verify": LINUX_VERIFY_FILE_SCRIPT},
    ("linux", "directory"): {"deliver": LINUX_DELIVER_DIRECTORY_SCRIPT, "verify": LINUX_VERIFY_DIRECTORY_SCRIPT},
    ("windows", "file"): {"deliver": WINDOWS_DELIVER_FILE_SCRIPT, "verify": WINDOWS_VERIFY_FILE_SCRIPT},
    ("windows", "directory"): {
        "deliver": WINDOWS_DELIVER_DIRECTORY_SCRIPT,
        "verify": WINDOWS_VERIFY_DIRECTORY_SCRIPT,
    },
}


def _b64(value: str) -> str:
    """Encode one UTF-8 runtime value for line-oriented Windows stdin delivery."""
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


@dataclass(frozen=True)
class RaesContentPayload:
    """A verified local payload file the deliver step streams, with its digests.

    ``sha256`` covers the payload bytes (the tar, for ``directory``);
    ``installed_tree_sha256`` (``directory`` only) is the digest the guest's
    fresh readback of the installed tree must reproduce.
    """

    path: str
    byte_count: int
    sha256: str
    installed_tree_sha256: str | None = None


@dataclass(frozen=True)
class RaesContentInstallOptions:
    """Guest-side permissions applied while publishing delivered content."""

    sensitive: bool = False
    file_mode: str | None = None


def _validate_delivery_identity(content_type: str, platform: str, target: str, sha256: str) -> None:
    """Validate the common delivery shape independent of payload kind."""
    if content_type not in ("file", "directory"):
        raise ValueError(f"Unsupported RAES content delivery content_type: {content_type!r}")
    if platform not in ("linux", "windows"):
        raise ValueError(f"Unknown platform for RaesContentDeliveryPlan: {platform!r}")
    if not target:
        raise ValueError("RaesContentDeliveryPlan requires a non-empty target")
    if not _HEX_SHA256.fullmatch(sha256 or ""):
        raise ValueError("RaesContentDeliveryPlan requires a lowercase hex sha256")


def _validate_payload(content_type: str, payload: RaesContentPayload) -> None:
    """Validate the streamed payload reference and directory-only invariants."""
    if not payload.path:
        raise ValueError("RaesContentDeliveryPlan requires a payload file")
    byte_count = payload.byte_count
    if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 0:
        raise ValueError("RaesContentDeliveryPlan requires a non-negative byte_count")
    if content_type != "directory":
        return
    if byte_count == 0:
        raise ValueError("RaesContentDeliveryPlan requires a non-empty payload for directory content")
    if not _HEX_SHA256.fullmatch(payload.installed_tree_sha256 or ""):
        raise ValueError("RaesContentDeliveryPlan requires a lowercase hex installed_tree_sha256 for directory content")


def _deliver_timeout_seconds(byte_count: int) -> int:
    """Deliver-step budget: a fixed floor plus time at a conservative 1 MB/s."""
    return _DELIVER_TIMEOUT_FLOOR_SECONDS + byte_count // 1_000_000


class RaesContentDeliveryPlan:
    """Deliver one source-backed content item's bytes to its guest.

    ``content_type`` is ``"file"`` or ``"directory"``; ``platform`` is
    ``"linux"`` or ``"windows"``; ``target`` is the content's ``path`` (file)
    or ``destination`` (directory). ``payload`` is the local, already
    digest-verified payload file with its exact size and digests; the deliver
    step streams the file to the guest's stdin with constant memory
    (ADR-032-R9), so no payload bytes are held in memory or rendered into a
    script (zero bytes is a legitimate ``file``). For ``directory``, the
    payload's ``installed_tree_sha256`` (``raes_content_payload.installed_tree_sha256``)
    is what ``verify_step`` independently reproduces from a fresh readback of
    the destination, distinct from ``sha256``, which only covers the transient
    tar transport. ``install_options`` requests guest-side permissions,
    including the least-permissive sensitive mode.
    """

    def __init__(
        self,
        *,
        content_type: str,
        platform: str,
        target: str,
        payload: RaesContentPayload,
        install_options: RaesContentInstallOptions | None = None,
    ) -> None:
        _validate_delivery_identity(content_type, platform, target, payload.sha256)
        _validate_payload(content_type, payload)
        self._content_type = content_type
        self._platform = platform
        self._scripts = _SCRIPTS[(platform, content_type)]
        self._target = target
        self._sha256 = payload.sha256
        self._payload_path = payload.path
        self._byte_count = payload.byte_count
        options = install_options or RaesContentInstallOptions()
        self._sensitive = options.sensitive
        self._file_mode = options.file_mode
        self._installed_tree_sha256 = payload.installed_tree_sha256

    @property
    def steps(self) -> list[SetupStep]:
        return [
            SetupStep(
                name=f"raes_deliver_content_{self._content_type}_{self._platform}",
                script=self._scripts["deliver"],
                stdin_input=self._deliver_stdin(),
                stdin_path=self._payload_path,
                timeout_seconds=_deliver_timeout_seconds(self._byte_count),
            )
        ]

    @property
    def verify_step(self) -> SetupStep:
        return SetupStep(
            name=f"raes_verify_content_{self._content_type}_{self._platform}",
            script=self._scripts["verify"],
            stdin_input=self._verify_stdin(),
            timeout_seconds=120,
            is_verification=True,
        )

    def _deliver_stdin(self) -> str:
        """Windows only: the header lines preceding the streamed payload on stdin.

        Every runtime value stays off argv. Sensitivity is always sent (both
        content types): the file dialect applies it as a restrictive file
        ACL/mode, the directory dialect applies it to the private extraction
        tree before publishing. The raw payload bytes follow the last line.
        """
        if self._platform != "windows":
            return ""
        lines = [
            _b64(self._target),
            _b64(self._sha256),
            _b64("1" if self._sensitive else "0"),
            _b64(str(self._byte_count)),
        ]
        return "\n".join(lines) + "\n"

    def _verify_stdin(self) -> str:
        """Windows only. Directory verify carries the installed-tree digest,
        never the tar-bytes ``sha256`` -- see the module/class docstrings."""
        if self._platform != "windows":
            return ""
        digest = self._installed_tree_sha256 if self._content_type == "directory" else self._sha256
        return "\n".join([_b64(self._target), _b64(digest or "")]) + "\n"

    def get_context(self, _instance: object) -> dict[str, Any]:
        """Linux: template variables substituted into the static script text.

        Windows carries no template variables (every value is on stdin, built
        by :meth:`_deliver_stdin` / :meth:`_verify_stdin`), so this returns an
        empty dict for that platform -- ``SetupOrchestrator._render_script``
        is a no-op when the script has no ``{{ }}`` placeholders. The same
        context dict is rendered against both the deliver and verify scripts
        (``SetupOrchestrator.orchestrate`` calls ``get_context`` once), so
        ``raes_tree_sha256_quoted`` (verify-only) and ``raes_sha256_quoted`` /
        ``raes_mode_quoted`` (deliver-only, for directory/file respectively)
        safely coexist -- each script's static text only references the keys
        it actually uses.
        """
        if self._platform != "linux":
            return {}
        mode_value = self._file_mode or ("600" if self._sensitive else "644")
        if self._content_type == "file" and mode_value not in _LINUX_FILE_MODES:
            raise ValueError(f"Unsupported RAES content delivery file mode: {mode_value!r}")
        return {
            "raes_target_quoted": shlex.quote(self._target),
            "raes_sha256_quoted": shlex.quote(self._sha256),
            "raes_tree_sha256_quoted": shlex.quote(self._installed_tree_sha256 or ""),
            "raes_mode_quoted": shlex.quote(mode_value),
            "raes_byte_count": str(self._byte_count),
        }
