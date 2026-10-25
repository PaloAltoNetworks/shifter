from uuid import UUID

import pytest

from shared.authorization import AuthorizationDescendantResolutionError, TargetRef, inventory
from shared.identity_scope import ResourceScope


@pytest.fixture(autouse=True)
def isolated_resolvers(monkeypatch):
    monkeypatch.setattr(inventory, "_resolvers", {})
    monkeypatch.setattr(inventory, "_event_scope_resolver", None)
    monkeypatch.setattr(inventory, "_nonworkspace_event_resolver", None)


def test_inventory_combines_owning_domain_results_with_one_bound() -> None:
    event = TargetRef("event", UUID("11111111-1111-1111-1111-111111111111"))
    range_ = TargetRef("range", UUID("22222222-2222-2222-2222-222222222222"))
    calls = []

    def events(workspace_ids, limit):
        calls.append(("events", workspace_ids, limit))
        return (event,)

    def ranges(workspace_ids, limit):
        calls.append(("ranges", workspace_ids, limit))
        return (range_,)

    inventory.bind_authorization_descendant_resolver("ctf.events", events)
    inventory.bind_authorization_descendant_resolver("engine.ranges", ranges)

    assert inventory.resolve_authorization_descendants((7, 9), 2) == (event, range_)
    assert calls == [("events", (7, 9), 3), ("ranges", (7, 9), 2)]


def test_inventory_rejects_results_beyond_shared_bound() -> None:
    events = tuple(TargetRef("event", UUID(int=value)) for value in range(1, 3))
    inventory.bind_authorization_descendant_resolver("ctf.events", lambda workspace_ids, limit: events)
    inventory.bind_authorization_descendant_resolver("engine.ranges", lambda workspace_ids, limit: ())

    with pytest.raises(AuthorizationDescendantResolutionError, match="invalid"):
        inventory.resolve_authorization_descendants((7,), 1)


def test_inventory_fails_closed_when_an_owner_is_unbound() -> None:
    inventory.bind_authorization_descendant_resolver("ctf.events", lambda workspace_ids, limit: ())

    with pytest.raises(AuthorizationDescendantResolutionError, match="unavailable"):
        inventory.resolve_authorization_descendants((7,), 1)


def test_inventory_rejects_a_target_owned_by_another_domain() -> None:
    range_ = TargetRef("range", UUID("22222222-2222-2222-2222-222222222222"))
    inventory.bind_authorization_descendant_resolver("ctf.events", lambda workspace_ids, limit: (range_,))
    inventory.bind_authorization_descendant_resolver("engine.ranges", lambda workspace_ids, limit: ())

    with pytest.raises(AuthorizationDescendantResolutionError, match="invalid"):
        inventory.resolve_authorization_descendants((7,), 1)


def test_account_event_inventory_rejects_sibling_scope_and_incomplete_page() -> None:
    account = ResourceScope("account", UUID("11111111-1111-1111-1111-111111111111"))
    sibling = ResourceScope("account", UUID("22222222-2222-2222-2222-222222222222"))
    event = TargetRef("event", UUID("33333333-3333-3333-3333-333333333333"))
    inventory.bind_authorization_event_inventory(lambda _uuid: sibling, lambda _parent, _limit: ((event, sibling),))

    with pytest.raises(AuthorizationDescendantResolutionError, match="invalid"):
        inventory.resolve_authorization_nonworkspace_events(account, 1)
    with pytest.raises(AuthorizationDescendantResolutionError, match="invalid"):
        inventory.resolve_authorization_nonworkspace_events(ResourceScope("installation"), 0)
