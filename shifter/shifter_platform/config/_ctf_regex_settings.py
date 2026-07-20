"""CTF regex-flag safety settings (issue #1183).

Extracted from ``config/settings.py`` (mirroring ``config/_capacity_settings.py``)
to keep that module under the 500-line cap and to single-source the tunables the
CTF regex-flag safety policy reads.

Organizer-authored regex flags are evaluated on request workers against
participant-submitted values (``ctf.services.regex_policy``). Standard-library
``re`` has no execution bound, so a crafted pattern/input pair can pin a worker
(ReDoS, CWE-1333). These knobs bound that cost:

- ``CTF_REGEX_FLAG_MAX_PATTERN_LENGTH`` — creation-time cap on the stored regex
  pattern. Defaults to 255 to match the ``CTFFlag.flag_hash`` column; the column
  is only a persistence backstop, this is the policy limit.
- ``CTF_REGEX_FLAG_MAX_SUBMISSION_LENGTH`` — participant submissions longer than
  this are treated as a non-match *before* the engine runs. Defaults to 500 to
  match the ``CTFSubmission.submitted_flag`` column; the policy is additionally
  clamped to that storage limit at evaluation time so a verifiable submission is
  always persistable (a higher configured value cannot exceed the column).
- ``CTF_REGEX_FLAG_MATCH_TIMEOUT_SECONDS`` — per-match wall-clock budget; a match
  that exceeds it fails closed (incorrect submission).

Env bindings use literal ``os.environ.get`` so ``config/_env_manifest.py``'s AST
extractor captures them; the conversions wrap those calls. Importing this module
only binds the module-level constants re-exported by ``config.settings``.
"""

from __future__ import annotations

import os

__all__ = [
    "CTF_REGEX_FLAG_MATCH_TIMEOUT_SECONDS",
    "CTF_REGEX_FLAG_MAX_PATTERN_LENGTH",
    "CTF_REGEX_FLAG_MAX_SUBMISSION_LENGTH",
]


CTF_REGEX_FLAG_MAX_PATTERN_LENGTH = int(os.environ.get("CTF_REGEX_FLAG_MAX_PATTERN_LENGTH", "255"))
CTF_REGEX_FLAG_MAX_SUBMISSION_LENGTH = int(os.environ.get("CTF_REGEX_FLAG_MAX_SUBMISSION_LENGTH", "500"))
CTF_REGEX_FLAG_MATCH_TIMEOUT_SECONDS = float(os.environ.get("CTF_REGEX_FLAG_MATCH_TIMEOUT_SECONDS", "0.1"))
