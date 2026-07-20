"""Admin registrations for the ``shared`` app.

Django autodiscovers ``shared/admin.py``; the cohesive token-admin code lives in
the ``shared.api_tokens`` package, so import it here to register ``ApiToken``.
"""

from __future__ import annotations

from shared.api_tokens import admin as _api_tokens_admin

# Side-effect import: importing the module runs its ``@admin.register`` calls.
# Re-export the name so both ruff (F401) and Sonar (S1128) treat it as used
# rather than flagging the registration import as dead.
__all__ = ["_api_tokens_admin"]
