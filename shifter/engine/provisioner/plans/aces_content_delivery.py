"""Setup plans delivering source-backed ACES guest content bytes (#1564).

Post-boot delivery of a source-backed ``file``/``directory`` content item, over
the same authenticated guest transport ``plans.aces_active_directory`` uses for
directory realization.

Linux and Windows use genuinely different mechanisms here, and that asymmetry
is deliberate, not an oversight:

- **Windows**: every runtime value (target, digest, sensitivity, payload)
  travels over the real, separate PowerShell stdin channel
  (``executors.guest_ssh_executor.GuestSSHExecutor.run_command`` base64-encodes
  the *script* straight into ``-EncodedCommand`` argv and pipes ``stdin_input``
  as the process's actual stdin), read line-by-line via ``[Console]::In.
  ReadLine()`` -- the same pattern ``plans.aces_active_directory`` uses for
  AD realization. This keeps every authored/derived value off Windows argv and
  out of guest process listings / Event ID 4688.
- **Linux**: ``GuestSSHExecutor`` runs ``sudo -n bash -se``, concatenating
  ``script`` + ``stdin_input`` into ONE literal stream fed to bash's own
  script parser -- there is no independent runtime "read the next line from
  stdin" channel here. bash reads a piped ``-s`` script source with internal
  read-ahead buffering, so a `read` builtin placed mid-script does **not**
  reliably consume the intended data line (confirmed empirically: bash treats
  already-buffered-ahead data as further script source and fails with
  "command not found"). So every runtime value is instead rendered directly
  into the script text via ``{{ }}`` template substitution (shell-quoted for
  paths; the payload via a quoted-delimiter heredoc) -- the same mechanism
  ``aces_gcp_composition._linux_content`` already uses for inline file bytes.
  This is still transport-safe: the whole rendered script travels over the
  SSH client's real OS-level stdin (never argv, env, or GCE instance
  metadata) exactly like the Windows path -- only the *in-guest* delivery
  mechanism (interpolated script vs. a runtime read) differs.

Payload bytes are always base64 text on the wire (arbitrary binary is unsafe in
a bash variable / a single PowerShell console line otherwise), decoded straight
to a private staging file -- never held as a decoded bytes blob in a shell
variable. A directory payload is the deterministic uncompressed tar
``shared.aces.content_delivery._materialize_directory`` produces; the guest
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
``aces_content_delivery.realize_aces_content_delivery`` treats as the
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
  (``aces_content_delivery._installed_tree_sha256``), so no new wire/DB
  contract is needed -- it rides down to the guest as an ordinary runtime
  value alongside the existing tar-bytes ``sha256``.
"""

from __future__ import annotations

import base64
import re
import shlex
from typing import Any

from ._aces_content_delivery_scripts import (
    WINDOWS_DELIVER_DIRECTORY_SCRIPT,
    WINDOWS_DELIVER_FILE_SCRIPT,
    WINDOWS_VERIFY_DIRECTORY_SCRIPT,
    WINDOWS_VERIFY_FILE_SCRIPT,
)
from .base import SetupStep

_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LINUX_FILE_MODES = frozenset({"600", "644"})

# ---------------------------------------------------------------------------
# Linux (bash) -- every value is rendered directly into the static script text
# via {{ }} substitution (shell-quoted where it is a path/identifier; the
# payload via a quoted heredoc so it is never shell-expanded). See the module
# docstring for why this differs from the Windows dialect.
# ---------------------------------------------------------------------------

LINUX_DELIVER_FILE_SCRIPT = r"""#!/bin/bash
set -euo pipefail
target_path={{ aces_target_quoted }}
expected_sha256={{ aces_sha256_quoted }}
file_mode={{ aces_mode_quoted }}

parent_dir=$(dirname -- "$target_path")
mkdir -p -- "$parent_dir"
staging=$(mktemp -- "${parent_dir}/.aces-content.XXXXXX")
trap 'rm -f -- "$staging"' EXIT

base64 -d > "$staging" <<'ACES_CONTENT_B64_EOF'
{{ aces_payload_b64 }}
ACES_CONTENT_B64_EOF

actual_sha256=$(sha256sum -- "$staging" | awk '{print $1}')
if [ "$actual_sha256" != "$expected_sha256" ]; then
    echo "FATAL: ACES content delivery digest mismatch" >&2
    exit 1
fi

chmod "$file_mode" -- "$staging"
mv -f -- "$staging" "$target_path"
trap - EXIT
echo "ACES_CONTENT_FILE_INSTALLED"
"""

LINUX_VERIFY_FILE_SCRIPT = r"""#!/bin/bash
set -euo pipefail
target_path={{ aces_target_quoted }}
expected_sha256={{ aces_sha256_quoted }}

if [ -L "$target_path" ] || [ ! -f "$target_path" ]; then
    echo "FATAL: ACES content delivery target is missing" >&2
    exit 1
fi
actual_sha256=$(sha256sum -- "$target_path" | awk '{print $1}')
if [ "$actual_sha256" != "$expected_sha256" ]; then
    echo "FATAL: ACES content delivery readback digest mismatch" >&2
    exit 1
fi
echo "ACES_CONTENT_FILE_VERIFIED"
"""

_LINUX_TAR_SAFETY_CHECK = r"""
# `-f` takes the very next token as its argument regardless of `--`, so `--`
# cannot precede the filename here (it would become tar's `-f` value, not a
# "no more options" marker) -- $tar_staging is always the deterministic,
# already-validated-absolute staging path, never author-controlled.
if tar -tvf "$tar_staging" 2>/dev/null | grep -Eq '^l'; then
    rm -f -- "$tar_staging"
    echo "FATAL: ACES content delivery archive contains a symlink entry" >&2
    exit 1
fi
if tar -tf "$tar_staging" | grep -Eq '(^/)|(^\.\./)|(/\.\./)|(/\.\.$)|(^\.\.$)'; then
    rm -f -- "$tar_staging"
    echo "FATAL: ACES content delivery archive contains an unsafe path" >&2
    exit 1
fi
"""

LINUX_DELIVER_DIRECTORY_SCRIPT = (
    r"""#!/bin/bash
set -euo pipefail
destination={{ aces_target_quoted }}
expected_sha256={{ aces_sha256_quoted }}
destination="${destination%/}"

parent_dir=$(dirname -- "$destination")
mkdir -p -- "$parent_dir"
# An exclusively-created, unpredictable staging path (mktemp, like the file
# dialect) -- never a fixed sibling name an unprivileged process could pre-plant
# as a symlink ahead of this write. It is removed by this same step right after
# extraction; verify_step proves the *installed tree*, so it never needs to
# relocate this (or any) retained archive.
tar_staging=$(mktemp -- "${parent_dir}/.aces-content-staging.XXXXXX")
trap 'rm -f -- "$tar_staging"' EXIT

base64 -d > "$tar_staging" <<'ACES_CONTENT_B64_EOF'
{{ aces_payload_b64 }}
ACES_CONTENT_B64_EOF

actual_sha256=$(sha256sum -- "$tar_staging" | awk '{print $1}')
if [ "$actual_sha256" != "$expected_sha256" ]; then
    echo "FATAL: ACES content delivery digest mismatch" >&2
    exit 1
fi
"""
    + _LINUX_TAR_SAFETY_CHECK
    + r"""
extract_dir=$(mktemp -d -- "${parent_dir}/.aces-content-extract.XXXXXX")
tar -xf "$tar_staging" -C "$extract_dir"
rm -rf -- "$destination"
mv -T -- "$extract_dir" "$destination"
echo "ACES_CONTENT_DIRECTORY_INSTALLED"
"""
)

LINUX_VERIFY_DIRECTORY_SCRIPT = r"""#!/bin/bash
set -euo pipefail
destination={{ aces_target_quoted }}
expected_tree_sha256={{ aces_tree_sha256_quoted }}
destination="${destination%/}"

if [ -L "$destination" ] || [ ! -d "$destination" ]; then
    echo "FATAL: ACES content delivery destination is missing" >&2
    exit 1
fi

# Deterministic installed-tree manifest: every regular file under $destination
# (symlinks are never followed and never counted as "type f"), sorted by
# byte-value path order (LC_ALL=C), each contributing one
# "<sha256>  <relpath>\n" line -- mirrors
# aces_content_delivery._installed_tree_sha256 exactly, so the server-computed
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
    echo "FATAL: ACES content delivery readback digest mismatch" >&2
    exit 1
fi
echo "ACES_CONTENT_DIRECTORY_VERIFIED"
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


class AcesContentDeliveryPlan:
    """Deliver one source-backed content item's bytes to its guest.

    ``content_type`` is ``"file"`` or ``"directory"``; ``platform`` is
    ``"linux"`` or ``"windows"``; ``target`` is the content's ``path`` (file)
    or ``destination`` (directory); ``sha256`` is the expected lowercase-hex
    digest of the delivered payload bytes (the tar, for ``directory``);
    ``payload_b64`` is the already base64-encoded payload (one text line, no
    embedded newlines -- the caller, never this plan, holds the decoded
    bytes; empty is a valid encoding of a legitimate zero-byte ``file``).
    ``sensitive`` requests least-permissive guest-side permissions for either
    content type. ``installed_tree_sha256`` is required for ``directory``
    only: the expected digest of the *installed tree*
    (``aces_content_delivery._installed_tree_sha256``) that ``verify_step``
    independently reproduces from a fresh readback of the destination --
    distinct from ``sha256``, which only covers the transient tar transport.
    """

    def __init__(
        self,
        *,
        content_type: str,
        platform: str,
        target: str,
        sha256: str,
        payload_b64: str,
        sensitive: bool = False,
        installed_tree_sha256: str | None = None,
    ) -> None:
        if content_type not in ("file", "directory"):
            raise ValueError(f"Unsupported ACES content delivery content_type: {content_type!r}")
        if platform not in ("linux", "windows"):
            raise ValueError(f"Unknown platform for AcesContentDeliveryPlan: {platform!r}")
        if not target:
            raise ValueError("AcesContentDeliveryPlan requires a non-empty target")
        if not _HEX_SHA256.fullmatch(sha256 or ""):
            raise ValueError("AcesContentDeliveryPlan requires a lowercase hex sha256")
        if content_type == "directory":
            # A directory's tar payload is never legitimately empty (even a
            # zero-entry tar carries non-zero trailer bytes) -- unlike `file`,
            # where an empty string is the correct base64 encoding of a
            # genuine zero-byte source file.
            if not payload_b64:
                raise ValueError("AcesContentDeliveryPlan requires a non-empty payload for directory content")
            if not _HEX_SHA256.fullmatch(installed_tree_sha256 or ""):
                raise ValueError(
                    "AcesContentDeliveryPlan requires a lowercase hex installed_tree_sha256 for directory content"
                )
        self._content_type = content_type
        self._platform = platform
        self._scripts = _SCRIPTS[(platform, content_type)]
        self._target = target
        self._sha256 = sha256
        self._payload_b64 = payload_b64
        self._sensitive = sensitive
        self._installed_tree_sha256 = installed_tree_sha256

    @property
    def steps(self) -> list[SetupStep]:
        return [
            SetupStep(
                name=f"aces_deliver_content_{self._content_type}_{self._platform}",
                script=self._scripts["deliver"],
                stdin_input=self._deliver_stdin(),
                timeout_seconds=600,
            )
        ]

    @property
    def verify_step(self) -> SetupStep:
        return SetupStep(
            name=f"aces_verify_content_{self._content_type}_{self._platform}",
            script=self._scripts["verify"],
            stdin_input=self._verify_stdin(),
            timeout_seconds=120,
            is_verification=True,
        )

    def _deliver_stdin(self) -> str:
        """Windows only: the genuine stdin channel carrying every runtime value.

        Sensitivity is always sent (both content types): the file dialect
        applies it as a restrictive file ACL/mode, the directory dialect
        applies it to the private extraction tree before publishing.
        """
        if self._platform != "windows":
            return ""
        lines = [
            _b64(self._target),
            _b64(self._sha256),
            _b64("1" if self._sensitive else "0"),
            self._payload_b64,
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
        ``aces_tree_sha256_quoted`` (verify-only) and ``aces_sha256_quoted`` /
        ``aces_mode_quoted`` (deliver-only, for directory/file respectively)
        safely coexist -- each script's static text only references the keys
        it actually uses.
        """
        if self._platform != "linux":
            return {}
        mode_value = "600" if self._sensitive else "644"
        if self._content_type == "file" and mode_value not in _LINUX_FILE_MODES:
            raise ValueError(f"Unsupported ACES content delivery file mode: {mode_value!r}")
        return {
            "aces_target_quoted": shlex.quote(self._target),
            "aces_sha256_quoted": shlex.quote(self._sha256),
            "aces_tree_sha256_quoted": shlex.quote(self._installed_tree_sha256 or ""),
            "aces_mode_quoted": shlex.quote(mode_value),
            "aces_payload_b64": self._payload_b64,
        }
