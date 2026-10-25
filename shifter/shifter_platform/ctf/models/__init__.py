"""CTF models package — split from monolithic models.py in PR #856.

This ``__init__`` re-exports every public symbol from the submodules so
``from ctf.models import X`` and ``patch("ctf.models.X")`` keep working
exactly as they did when this was a single-file module. The
``timezone`` re-export preserves the ``patch("ctf.models.timezone")``
test surface used by test_scoring.py.

Submodule layout:

* ``_base``        — ``SoftDeleteManager``, ``CTFBaseModel`` (abstract).
* ``event``        — ``CTFEvent``, ``CTFEventStaff``.
* ``challenge``    — ``CTFChallenge``.
* ``taxonomy``     — ``CTFTopic``, ``CTFChallengeTag``, ``CTFChallengeFile``,
  ``CTFChallengePrerequisite``.
* ``flag``         — ``CTFFlag``.
* ``team``         — ``CTFBracket``, ``CTFTeam``, ``CTFParticipant``.
* ``submission``   — ``CTFSubmission``, ``CTFAward``.
* ``rating``       — ``CTFChallengeRating``.
* ``hint``         — ``CTFHint``, ``CTFHintUsage``.
* ``notification`` — ``CTFNotification``, ``CTFEmailTemplate``, ``CTFScheduledTask``.
* ``communication``— ``CommunicationCampaign``, ``CommunicationTargetEvent``,
  ``MessageRevision``, ``CommunicationIntent``, ``RecipientSnapshot``,
  ``DeliveryAttempt``, ``ParticipantReceipt`` (ADR-051, #2048).
* ``recovery``     — ``CTFRangeRecovery``.
* ``spare_range``  — ``CTFSpareRange``.
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
from .cohort import CTFCohort
from .communication import (
    CommunicationCampaign,
    CommunicationIntent,
    CommunicationTargetEvent,
    MessageRevision,
    RecipientSnapshot,
)
from .communication_cutover import CommunicationCutover, LegacyCommunication
from .communication_delivery import DeliveryAttempt, ParticipantReceipt
from .content_hydration import CTFContentHydrationReceipt
from .event import CTFEvent
from .event_page import CTFEventPage
from .event_staff import CTFEventStaff
from .flag import CTFFlag
from .hint import CTFHint, CTFHintUsage
from .notification import CTFEmailTemplate, CTFNotification, CTFWebhook
from .public_registration import CTFPublicRegistrationRequest
from .rating import CTFChallengeRating
from .recovery import CTFRangeRecovery
from .scheduled_task import CTFScheduledTask
from .spare_range import CTFSpareRange
from .submission import CTFAward, CTFReceiptConsumption, CTFSubmission
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
    "CTFCohort",
    "CTFContentHydrationReceipt",
    "CTFEmailTemplate",
    "CTFEvent",
    "CTFEventPage",
    "CTFEventStaff",
    "CTFFlag",
    "CTFHint",
    "CTFHintUsage",
    "CTFNotification",
    "CTFParticipant",
    "CTFPublicRegistrationRequest",
    "CTFRangeRecovery",
    "CTFReceiptConsumption",
    "CTFScheduledTask",
    "CTFSpareRange",
    "CTFSubmission",
    "CTFTeam",
    "CTFTopic",
    "CTFWebhook",
    "CommunicationCampaign",
    "CommunicationCutover",
    "CommunicationIntent",
    "CommunicationTargetEvent",
    "DeliveryAttempt",
    "LegacyCommunication",
    "MessageRevision",
    "ParticipantReceipt",
    "RecipientSnapshot",
    "SoftDeleteManager",
    "timezone",
]
