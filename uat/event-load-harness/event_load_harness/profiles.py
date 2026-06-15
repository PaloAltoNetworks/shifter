"""Traffic-mix profiles and the route catalog.

The route catalog names every route class the harness knows about and whether it
is ``active`` (an executor exists) or ``deferred`` (catalogued as a seam, no
executor yet). A profile is a named weighting over active route classes.

This is the durable extensibility seam from the preflight: a 200->500
participant change, a new route class, or enabling the deferred CTF surfaces is
a registry edit here plus an executor in ``routes.py`` - not a rewrite of auth,
metrics, or reporting.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RouteSpec:
    """Catalog metadata for a route class."""

    kind: str  # "http" | "ws"
    status: str  # "active" | "deferred"
    description: str


# The full route catalog. Active routes have executors in routes.py; deferred
# routes document the seam for follow-up work (CTFd load, native-CTF scoring for
# issue #850) and cannot be selected by a runnable profile.
ROUTE_CATALOG: dict[str, RouteSpec] = {
    # --- active: the core portal event path (#846 baseline) ---
    "page:dashboard": RouteSpec("http", "active", "Authenticated portal dashboard page load."),
    "page:ctf-event": RouteSpec("http", "active", "CTF participant event/landing page load."),
    "page:scoreboard": RouteSpec("http", "active", "CTF scoreboard page load (read traffic)."),
    "range:status-poll": RouteSpec("http", "active", "Range-status polling over the JSON API."),
    "ws:range-status": RouteSpec("ws", "active", "Range-status websocket subscription."),
    "ws:terminal": RouteSpec("ws", "active", "Browser SSH terminal websocket session."),
    "guacamole:bootstrap": RouteSpec("http", "active", "Guacamole RDP URL bootstrap request."),
    # --- deferred: seam for follow-up issues ---
    "ctfd:submit": RouteSpec("http", "deferred", "Standalone CTFd flag submission (separate system)."),
    "ctfd:scoreboard": RouteSpec("http", "deferred", "Standalone CTFd scoreboard polling."),
    "ctf:submit": RouteSpec("http", "deferred", "Native CTF flag submission flood (feeds #850)."),
    "ctf:scoreboard": RouteSpec("http", "deferred", "Native CTF scoreboard polling (feeds #850)."),
}


@dataclass(frozen=True)
class Profile:
    name: str
    description: str
    route_weights: dict[str, int] = field(default_factory=dict)
    includes_native_ctf: bool = False


class UnknownProfile(KeyError):
    """Raised when a profile name is not registered."""


_PROFILES: dict[str, Profile] = {
    "portal-core": Profile(
        name="portal-core",
        description=(
            "Core portal event path that failed/under-measured in the May event: "
            "authenticated page traffic, range-status polling + websocket, browser "
            "terminal websockets, and Guacamole RDP bootstrap."
        ),
        route_weights={
            "page:dashboard": 5,
            "page:ctf-event": 3,
            "page:scoreboard": 2,
            "range:status-poll": 4,
            "ws:range-status": 3,
            "ws:terminal": 3,
            "guacamole:bootstrap": 1,
        },
    ),
}


def validate_profile(profile: Profile) -> None:
    """Raise ``ValueError`` if ``profile`` references unknown/deferred routes or bad weights."""
    if not profile.route_weights:
        raise ValueError(f"profile {profile.name!r} has no route weights")
    for route_class, weight in profile.route_weights.items():
        spec = ROUTE_CATALOG.get(route_class)
        if spec is None:
            raise ValueError(f"profile {profile.name!r} references unknown route {route_class!r}")
        if spec.status != "active":
            raise ValueError(
                f"profile {profile.name!r} references deferred route {route_class!r}; no executor exists for it yet"
            )
        if weight <= 0:
            raise ValueError(f"profile {profile.name!r} route {route_class!r} weight must be > 0")


def get_profile(name: str) -> Profile:
    try:
        profile = _PROFILES[name]
    except KeyError as exc:
        raise UnknownProfile(name) from exc
    validate_profile(profile)
    return profile


def list_profiles() -> list[str]:
    return sorted(_PROFILES)
