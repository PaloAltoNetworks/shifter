"""CTF forms - Form classes for CTF management.

This module provides Django forms for:
- Event creation and editing
- Challenge creation and editing
- Participant management
- Notification creation

The implementation is split by domain across private submodules
(``_common``, ``_event``, ``_challenge``, ``_participant``, ``_misc``) and
re-exported here so callers continue to use ``from ctf.forms import X`` /
``from ctf import forms``.
"""

from __future__ import annotations

import logging

from ._challenge import CTFChallengeForm
from ._event import CTFEventForm, EventStatusForm
from ._misc import CTFBracketForm, CTFNotificationForm
from ._participant import (
    CTFParticipantBatchForm,
    CTFParticipantEmailForm,
    CTFParticipantForm,
    CTFParticipantImportForm,
    CTFParticipantRenameForm,
)

logger = logging.getLogger(__name__)

__all__ = (
    "CTFBracketForm",
    "CTFChallengeForm",
    "CTFEventForm",
    "CTFNotificationForm",
    "CTFParticipantBatchForm",
    "CTFParticipantEmailForm",
    "CTFParticipantForm",
    "CTFParticipantImportForm",
    "CTFParticipantRenameForm",
    "EventStatusForm",
    "logger",
)
