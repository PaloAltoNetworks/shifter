"""The credential boundary never substitutes a creator for a service."""

from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from shared.authorization import CredentialCeiling, TargetRef
from shared.identity_scope import PrincipalRef


def test_service_credential_keeps_its_independent_principal_and_immutable_ceiling():
    from shared.credentials import CredentialContext

    principal = PrincipalRef(uuid4(), "service")
    context = CredentialContext(
        principal=principal,
        kind="service",
        credential_uuid=uuid4(),
        ceiling=CredentialCeiling(frozenset({"event.read"})),
        scopes=frozenset({"ctf:event:read"}),
    )
    assert context.principal == principal
    assert context.ceiling.permits("event.read")
    assert not context.ceiling.permits("installation.manage_principals")
    with pytest.raises(FrozenInstanceError):
        context.principal = PrincipalRef(uuid4(), "human")


@pytest.mark.parametrize("kind", ["session", "personal", "temporary"])
def test_service_cannot_be_relabelled_as_a_human_credential(kind):
    from shared.credentials import CredentialContext

    with pytest.raises(ValueError):
        CredentialContext(
            principal=PrincipalRef(uuid4(), "service"),
            kind=kind,
            credential_uuid=uuid4(),
            ceiling=CredentialCeiling(frozenset({"event.read"})),
            scopes=frozenset(),
        )


@pytest.mark.parametrize("event,actions", [(None, {"event.read"}), (uuid4(), {"installation.manage_principals"})])
def test_temporary_context_requires_an_event_and_rejects_platform_authority(event, actions):
    from shared.credentials import CredentialContext

    with pytest.raises(ValueError):
        CredentialContext(
            PrincipalRef(uuid4(), "human"),
            "temporary",
            uuid4(),
            CredentialCeiling(frozenset(actions)),
            frozenset(),
            event,
        )


@pytest.mark.parametrize("target", [None, TargetRef("event", uuid4()), TargetRef("workspace", uuid4())])
def test_temporary_context_rejects_missing_or_inconsistent_ceiling_target(target):
    from shared.credentials import CredentialContext

    with pytest.raises(ValueError, match="event"):
        CredentialContext(
            PrincipalRef(uuid4(), "human"),
            "temporary",
            uuid4(),
            CredentialCeiling(frozenset({"event.read"}), target),
            frozenset(),
            uuid4(),
        )
