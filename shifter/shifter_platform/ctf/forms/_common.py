"""Shared constants for the CTF forms submodules.

Extracted once here so the SonarCloud S1192 duplicated-string-literal fix
made in the original ``ctf/forms.py`` continues to apply across the split
submodules (``_event``, ``_challenge``, ``_misc``).
"""

from __future__ import annotations

# SonarCloud S1192: extracted duplicated string literals.
DATETIME_SECONDS_FORMAT = "%Y-%m-%dT%H:%M:%S"
DATETIME_LOCAL_FORMAT = "%Y-%m-%dT%H:%M"
CANCEL_EVENT_LABEL = "Cancel Event"
