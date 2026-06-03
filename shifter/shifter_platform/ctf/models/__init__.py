"""CTF models package — split from monolithic models.py in PR #856.

This ``__init__`` re-exports every public symbol from the submodules so
``from ctf.models import X`` and ``patch("ctf.models.X")`` keep working
exactly as they did when this was a single-file module. The
``timezone`` re-export preserves the ``patch("ctf.models.timezone")``
test surface used by test_scoring.py.

Submodule layout:

* ``_base``        — ``SoftDeleteManager``, ``CTFBaseModel`` (abstract).
* ``event``        — ``CTFEvent``.
* ``challenge``    — ``CTFChallenge``.
* ``taxonomy``     — ``CTFTopic``, ``CTFChallengeTag``, ``CTFChallengeFile``,
  ``CTFChallengePrerequisite``.
* ``flag``         — ``CTFFlag``.
* ``team``         — ``CTFBracket``, ``CTFTeam``, ``CTFParticipant``.
* ``submission``   — ``CTFSubmission``, ``CTFAward``.
* ``rating``       — ``CTFChallengeRating``.
* ``hint``         — ``CTFHint``, ``CTFHintUsage``.
* ``notification`` — ``CTFNotification``, ``CTFEmailTemplate``, ``CTFScheduledTask``.
"""

from __future__ import annotations

# Re-export ``timezone`` because tests patch ``ctf.models.timezone`` directly
# (e.g. test_scoring.py::test_is_scoreboard_frozen). Submodules use
# ``from django.utils import timezone`` independently; both references point at
# the same object so a patch on ``ctf.models.timezone`` is visible to callers
# that go through this package surface.
from django.utils import timezone

from ._base import CTFBaseModel, SoftDeleteManager
from .challenge import CTFChallenge
from .event import CTFEvent
from .flag import CTFFlag
from .hint import CTFHint, CTFHintUsage
from .notification import CTFEmailTemplate, CTFNotification, CTFScheduledTask
from .rating import CTFChallengeRating
from .submission import CTFAward, CTFSubmission
from .taxonomy import (
    CTFChallengeFile,
    CTFChallengePrerequisite,
    CTFChallengeTag,
    CTFTopic,
)
from .team import CTFBracket, CTFParticipant, CTFTeam

__all__ = [
    "CTFAward",
    "CTFBaseModel",
    "CTFBracket",
    "CTFChallenge",
    "CTFChallengeFile",
    "CTFChallengePrerequisite",
    "CTFChallengeRating",
    "CTFChallengeTag",
    "CTFEmailTemplate",
    "CTFEvent",
    "CTFFlag",
    "CTFHint",
    "CTFHintUsage",
    "CTFNotification",
    "CTFParticipant",
    "CTFScheduledTask",
    "CTFSubmission",
    "CTFTeam",
    "CTFTopic",
    "SoftDeleteManager",
    "timezone",
]
