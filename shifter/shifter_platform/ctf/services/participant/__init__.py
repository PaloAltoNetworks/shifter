"""CTF Participant service.

Business logic for participant management, split across cohesive submodules
(issue #889, python:S104):

- ``lifecycle``: invite/resend/delete and profile helpers;
- ``profile``: self-service display name and affiliation updates (CTF-610);
- ``moderation``: ban/disqualify/role/hidden transitions (CTF-604/605/606/609);
- ``bulk_import``: CSV parsing and bulk import;
- ``queries``: eligibility predicates and participant lookups.

Public names are re-exported here so ``from ctf.services.participant import X``
keeps working unchanged.
"""

from __future__ import annotations

from .accounts import (
    create_participant_accounts,
    rename_own_participant_username,
    rename_participant_username,
)
from .auth import authenticate_ctf_participant
from .bulk_import import bulk_import_participants
from .credentials import (
    ParticipantPasswordIssuance,
    reset_participant_credentials,
    reset_participant_password,
)
from .lifecycle import (
    add_participant,
    delete_participant,
    resend_login_info,
)
from .moderation import (
    ban_participant,
    disqualify_participant,
    requalify_participant,
    set_participant_hidden,
    set_participant_role,
    unban_participant,
)
from .profile import update_own_profile
from .queries import (
    assert_participant_can_compete,
    eligible_participant_q,
    get_participant,
    get_participant_by_user,
    get_viewing_participant_by_user,
    is_active_participant,
    is_viewing_participant,
    list_participants_for_event,
    ranked_participant_q,
    viewing_participant_q,
)

__all__ = [
    "ParticipantPasswordIssuance",
    "add_participant",
    "assert_participant_can_compete",
    "authenticate_ctf_participant",
    "ban_participant",
    "bulk_import_participants",
    "create_participant_accounts",
    "delete_participant",
    "disqualify_participant",
    "eligible_participant_q",
    "get_participant",
    "get_participant_by_user",
    "get_viewing_participant_by_user",
    "is_active_participant",
    "is_viewing_participant",
    "list_participants_for_event",
    "ranked_participant_q",
    "rename_own_participant_username",
    "rename_participant_username",
    "requalify_participant",
    "resend_login_info",
    "reset_participant_credentials",
    "reset_participant_password",
    "set_participant_hidden",
    "set_participant_role",
    "unban_participant",
    "update_own_profile",
    "viewing_participant_q",
]
