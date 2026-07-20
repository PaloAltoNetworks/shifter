"""Profiles + route catalog are the extensibility seam.

Adding the 200->500 variant, a new route class, or the deferred CTF profiles
should be a registry change, not a rewrite. Integrity rules keep a profile from
selecting a route the harness cannot actually drive yet.
"""

import pytest

from event_load_harness.profiles import (
    ROUTE_CATALOG,
    Profile,
    UnknownProfile,
    get_profile,
    list_profiles,
    validate_profile,
)


def test_portal_core_profile_exists_and_is_runnable():
    cfg = get_profile("portal-core")
    assert cfg.route_weights
    # Every route the default profile drives must be an ACTIVE catalog route.
    for route_class in cfg.route_weights:
        assert route_class in ROUTE_CATALOG
        assert ROUTE_CATALOG[route_class].status == "active"


def test_portal_core_covers_the_may_failure_path():
    weights = get_profile("portal-core").route_weights
    kinds = {ROUTE_CATALOG[r].kind for r in weights}
    # exercises both http page/api traffic and websocket traffic
    assert "http" in kinds
    assert "ws" in kinds
    # the specific surfaces the issue names
    assert "ws:terminal" in weights
    assert "guacamole:bootstrap" in weights


def test_catalog_carries_deferred_seam_entries():
    # The CTFd + native-CTF route classes are catalogued (documented seam) but
    # marked deferred until their executors land.
    deferred = {name for name, spec in ROUTE_CATALOG.items() if spec.status == "deferred"}
    assert "ctf:submit" in deferred
    assert "ctf:scoreboard" in deferred


def test_unknown_profile_raises():
    with pytest.raises(UnknownProfile):
        get_profile("does-not-exist")


def test_list_profiles_returns_registered_names():
    names = list_profiles()
    assert "portal-core" in names


def test_validate_profile_rejects_unknown_route():
    bad = Profile(name="bad", description="x", route_weights={"page:nope": 1})
    with pytest.raises(ValueError, match="unknown route"):
        validate_profile(bad)


def test_validate_profile_rejects_deferred_route():
    bad = Profile(name="bad", description="x", route_weights={"ctf:submit": 1})
    with pytest.raises(ValueError, match="deferred"):
        validate_profile(bad)


def test_validate_profile_rejects_nonpositive_weight():
    bad = Profile(name="bad", description="x", route_weights={"page:dashboard": 0})
    with pytest.raises(ValueError, match="weight"):
        validate_profile(bad)
