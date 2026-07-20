"""Self-service participant profile updates (CTF-610).

The CTF layer keeps no separate profile store: display name and affiliation
live on the event-scoped ``CTFParticipant`` row, and the username belongs to
the platform account (see ``accounts.rename_own_participant_username``).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.db import transaction

from ctf.exceptions import CTFNotFoundError, CTFValidationError
from ctf.models import CTFParticipant

if TYPE_CHECKING:
    from uuid import UUID

    from django.contrib.auth.models import AnonymousUser, User

logger = logging.getLogger(__name__)

_NAME_MAX = 100
_AFFILIATION_MAX = 120


def update_own_profile(
    participant_id: UUID,
    *,
    actor: User | AnonymousUser,
    name: str | None = None,
    affiliation: str | None = None,
) -> CTFParticipant:
    """Update the actor's own display name and/or affiliation.

    ``None`` leaves a field unchanged; an empty affiliation clears it. The
    display name can never be cleared — it identifies the participant on
    every organizer surface.
    """
    with transaction.atomic():
        try:
            participant = CTFParticipant.objects.select_for_update(of=("self",)).get(
                pk=participant_id, deleted_at__isnull=True
            )
        except CTFParticipant.DoesNotExist:
            raise CTFNotFoundError("Participant not found", details={"participant_id": str(participant_id)}) from None
        if participant.user_id != actor.pk:
            raise CTFValidationError("You may only edit your own profile", code="CTF_PERMISSION_DENIED")

        update_fields: list[str] = []
        if name is not None:
            cleaned_name = name.strip()
            if not cleaned_name:
                raise CTFValidationError("Display name cannot be empty", code="CTF_INVALID_NAME")
            if len(cleaned_name) > _NAME_MAX:
                raise CTFValidationError(
                    "Display name is too long",
                    code="CTF_INVALID_NAME",
                    details={"max_length": _NAME_MAX},
                )
            participant.name = cleaned_name
            update_fields.append("name")
        if affiliation is not None:
            cleaned_affiliation = affiliation.strip()
            if len(cleaned_affiliation) > _AFFILIATION_MAX:
                raise CTFValidationError(
                    "Affiliation is too long",
                    code="CTF_INVALID_AFFILIATION",
                    details={"max_length": _AFFILIATION_MAX},
                )
            participant.affiliation = cleaned_affiliation
            update_fields.append("affiliation")
        if update_fields:
            participant.save(update_fields=[*update_fields, "updated_at"])
    logger.info("Participant %s updated own profile (%s)", participant_id, ", ".join(update_fields) or "no-op")
    return participant
