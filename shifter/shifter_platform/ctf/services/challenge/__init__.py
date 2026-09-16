"""CTF Challenge service.

Provides business logic for challenge management and flag operations. The
implementation is split across private submodules (``_resolve``,
``_flag_verify``, ``_flag_crud``, ``_challenge_write``, ``_challenge_release``,
``_challenge_read``, ``_access``, ``_prerequisites``) and re-exported here so
callers continue to use ``from ctf.services.challenge import X`` /
``from ctf.services import challenge``.

The re-exports also cover names that tests or sibling services historically
import or patch at ``ctf.services.challenge.<name>``
(``_CHALLENGE_MUTABLE_FIELDS``, ``_flag_hash_for_payload``,
``_sync_release_task``, ``_verify_regex_flag``, ``_verify_static_flag``, plus
every public CRUD/verification/prerequisite function) so existing import and
``unittest.mock.patch`` targets still work.

PATCH LOCALITY: ``add_flag``, ``remove_flag``, and ``add_prerequisite`` are
patched directly by tests at ``ctf.services.challenge.<name>``.
``_challenge_write.py`` never binds ``add_flag`` into its own module
namespace at import time -- its two internal call sites
(``_apply_challenge_m2m`` / ``_apply_optional_challenge_associations``,
which run during ``create_challenge`` / ``update_challenge``) instead
resolve it through this package at call time
(``from ctf.services import challenge as _c``, then ``_c.add_flag(...)``),
so a ``patch("ctf.services.challenge.add_flag")`` mutates the single
attribute those call sites actually look up when they run. ``remove_flag``
and ``add_prerequisite`` have no internal callers in this package, so no
such indirection is needed for them today.

All other cross-submodule calls (e.g. ``_challenge_write`` -> ``_resolve`` /
``_flag_crud`` / ``_flag_verify`` / ``_challenge_release``, ``_access`` ->
``_prerequisites``) are plain direct imports: none of those names are
patched at the package path, so no call-time indirection is required.
"""

from __future__ import annotations

from ._access import (
    assert_challenge_available_for_participant,
    assert_challenge_readable_for_participant,
)
from ._challenge_read import get_available_challenges, get_challenge, list_challenges_for_event
from ._challenge_release import _sync_release_task, release_challenge
from ._challenge_write import _CHALLENGE_MUTABLE_FIELDS, create_challenge, delete_challenge, update_challenge
from ._flag_crud import _flag_hash_for_payload, add_flag, remove_flag, update_flag
from ._flag_verify import (
    _verify_regex_flag,
    _verify_static_flag,
    hash_flag,
    validate_http_flag_config,
    verify_flag,
    verify_single_flag,
)
from ._prerequisites import (
    add_prerequisite,
    check_prerequisites_met,
    get_dependents,
    get_prerequisites,
    remove_prerequisite,
)

__all__ = (
    "_CHALLENGE_MUTABLE_FIELDS",
    "_flag_hash_for_payload",
    "_sync_release_task",
    "_verify_regex_flag",
    "_verify_static_flag",
    "add_flag",
    "add_prerequisite",
    "assert_challenge_available_for_participant",
    "assert_challenge_readable_for_participant",
    "check_prerequisites_met",
    "create_challenge",
    "delete_challenge",
    "get_available_challenges",
    "get_challenge",
    "get_dependents",
    "get_prerequisites",
    "hash_flag",
    "list_challenges_for_event",
    "release_challenge",
    "remove_flag",
    "remove_prerequisite",
    "update_challenge",
    "update_flag",
    "validate_http_flag_config",
    "verify_flag",
    "verify_single_flag",
)
