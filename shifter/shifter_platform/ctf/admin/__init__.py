"""Django admin configuration for CTF models.

Provides admin interfaces for managing CTF events, challenges,
participants, teams, and related entities.

The implementation is split by domain across private submodules
(``_base``, ``_inlines``, ``_event``, ``_participant``, ``_misc``) and
re-exported here so ``ctf.admin.<Name>`` keeps resolving as it did before
the split, and so importing ``ctf.admin`` still fires every
``@admin.register`` side effect exactly once.
"""

from __future__ import annotations

from ._base import SoftDeleteAdminMixin
from ._event import CTFBracketAdmin, CTFChallengeAdmin, CTFEventAdmin
from ._inlines import (
    CTFAwardInline,
    CTFChallengeFileInline,
    CTFChallengeInline,
    CTFChallengePrerequisiteInline,
    CTFParticipantInline,
    CTFScheduledTaskInline,
    CTFSubmissionInline,
    CTFTeamInline,
)
from ._misc import (
    CTFChallengeFileAdmin,
    CTFChallengePrerequisiteAdmin,
    CTFEmailTemplateAdmin,
    CTFNotificationAdmin,
    CTFScheduledTaskAdmin,
)
from ._participant import CTFAwardAdmin, CTFParticipantAdmin, CTFSubmissionAdmin, CTFTeamAdmin

__all__ = (
    "CTFAwardAdmin",
    "CTFAwardInline",
    "CTFBracketAdmin",
    "CTFChallengeAdmin",
    "CTFChallengeFileAdmin",
    "CTFChallengeFileInline",
    "CTFChallengeInline",
    "CTFChallengePrerequisiteAdmin",
    "CTFChallengePrerequisiteInline",
    "CTFEmailTemplateAdmin",
    "CTFEventAdmin",
    "CTFNotificationAdmin",
    "CTFParticipantAdmin",
    "CTFParticipantInline",
    "CTFScheduledTaskAdmin",
    "CTFScheduledTaskInline",
    "CTFSubmissionAdmin",
    "CTFSubmissionInline",
    "CTFTeamAdmin",
    "CTFTeamInline",
    "SoftDeleteAdminMixin",
)
