"""Neutral owner-to-Engine authority invalidation port."""

from __future__ import annotations

from uuid import UUID

import pytest

from shared.model_access import AuthorityInvalidation, AuthorityState
from shared.model_access.authority_port import (
    AuthorityInvalidatorBindingError,
    bind_authority_invalidator,
    invalidate_authority,
    reset_authority_invalidator,
)


@pytest.fixture(autouse=True)
def _restore_runtime_binding():
    yield
    from engine.services import invalidate_sharing_authority

    reset_authority_invalidator()
    bind_authority_invalidator(invalidate_sharing_authority)


def test_authority_invalidator_binding_is_single_and_fail_closed():
    seen = []

    def writer(command):
        seen.append(command)
        return len(command.authority_refs)

    reset_authority_invalidator()
    bind_authority_invalidator(writer)
    bind_authority_invalidator(writer)
    command = AuthorityInvalidation(
        deployment_id=UUID("11111111-1111-4111-8111-111111111111"),
        authority_refs=({"owner": "ctf", "reference": "event:e-1"},),
        state=AuthorityState.UNKNOWN,
        reason="membership-changed",
    )
    assert invalidate_authority(command) == 1
    assert seen == [command]

    with pytest.raises(AuthorityInvalidatorBindingError):
        bind_authority_invalidator(lambda _command: 0)
    reset_authority_invalidator()


def test_authority_invalidator_missing_binding_denies():
    reset_authority_invalidator()
    command = AuthorityInvalidation(
        deployment_id=None,
        authority_refs=({"owner": "management", "reference": "user:1"},),
        state="revoked",
        reason="user-disabled",
    )
    with pytest.raises(AuthorityInvalidatorBindingError):
        invalidate_authority(command)
