"""SPA cutover rollout flags for the Shifter platform (issues #1302 / #1369 /
#1370 / #1371 / #1372, ADR-013 / ADR-029).

Split out of ``config.settings`` to keep that module under Sonar S104's
500-line cap. Star-imported back into ``config.settings`` so
``from config.settings import PLATFORM_SPA_ENABLED`` (and the sibling flags)
resolves exactly as before.
"""

from __future__ import annotations

import os

__all__ = [
    "ADMINISTER_SPA_ENABLED",
    "CTF_WORKSPACE_SPA_ENABLED",
    "MISSION_CONTROL_SPA_ENABLED",
    "PLATFORM_SPA_ENABLED",
    "RISK_REGISTER_SPA_ENABLED",
    "SCENARIO_EDITOR_SPA_ENABLED",
]


def _env_bool(name: str, default: bool = False) -> bool:
    """Parse boolean environment variables using explicit true/false strings.

    Redefined here rather than imported from ``config.settings`` because
    ``settings`` imports this module -- importing back would be circular.
    Mirrors ``config.settings._env_bool``.
    """
    return os.environ.get(name, str(default)).lower() == "true"


# SPA cutover rollout flag (issue #1302, ADR-029). When enabled, the Risk
# Register GET page paths under /risk-register/ are served by the React SPA
# host view instead of the Django templates; the legacy POST action URLs stay
# Django-handled for old tabs and rollback. When disabled (the default), the
# portal renders the existing Django Risk Register templates unchanged.
# Non-secret boolean; absent env means disabled. Flipping it is reversible.
RISK_REGISTER_SPA_ENABLED = _env_bool("RISK_REGISTER_SPA_ENABLED", False)

# Platform SPA cutover rollout flag (issue #1369, ADR-013 / ADR-029). When
# enabled, the platform-wide React shell (home/dashboard, global navigation, and
# the Risk Register routes rehomed under the unified router) is served by the
# SPA host view instead of the legacy Django pages; the legacy routes/templates
# stay in place for rollback. When disabled (the default), the portal renders
# the existing Django pages unchanged. Non-secret boolean; flipping it is
# reversible. This is the single control for the SPA shell; the older
# RISK_REGISTER_SPA_ENABLED flag is still honoured for the Risk Register paths
# so an in-flight deploy toggled on it keeps working during the transition.
PLATFORM_SPA_ENABLED = _env_bool("PLATFORM_SPA_ENABLED", False)

# Mission Control SPA cutover rollout flag (issue #1370, ADR-013 / ADR-029).
# When enabled (together with PLATFORM_SPA_ENABLED), the Mission Control GET
# page paths under /mission-control/ (dashboard, agents, terminal, settings,
# help, walkthrough, NGFW, credentials) are served by the React SPA host view
# instead of the legacy Django templates; the legacy POST action URLs and JSON
# API endpoints under /mission-control/api/ stay Django-handled unchanged, and
# the canonical /api/v1/mission-control/ DRF routes are unaffected either way.
# Non-secret boolean; absent env means disabled. Flipping it is reversible.
MISSION_CONTROL_SPA_ENABLED = _env_bool("MISSION_CONTROL_SPA_ENABLED", False)

# Scenario Editor SPA cutover rollout flag (issue #1371, ADR-013 / ADR-029).
# When enabled (together with PLATFORM_SPA_ENABLED), the Scenario Editor GET page
# paths under /scenario-editor/ (list, create, YAML create, detail, edit, YAML
# editor) are served by the React SPA host view instead of the legacy Django
# templates; the legacy POST action URLs and the legacy validate-yaml endpoint
# stay Django-handled unchanged, and the canonical /api/v1/cms/ DRF routes the
# SPA uses are unaffected either way. Non-secret boolean; absent env means
# disabled. Flipping it is reversible.
SCENARIO_EDITOR_SPA_ENABLED = _env_bool("SCENARIO_EDITOR_SPA_ENABLED", False)

# CTF workspace SPA cutover rollout flag (issue #1372, ADR-013 / ADR-029).
# When enabled (together with PLATFORM_SPA_ENABLED), the CTF participant GET page
# paths under /ctf/ (dashboard, event, challenges, challenge detail, range,
# scoreboard, solve history, team, help) are served by the React SPA host view
# instead of the legacy Django templates; the participant login / change-password
# / team-join Django views, the legacy scoreboard JSON endpoint, and ALL organizer
# (/ctf/admin/) pages stay Django-handled unchanged, and the canonical
# /api/v1/ctf/ DRF routes the SPA uses are unaffected either way. Non-secret
# boolean; absent env means disabled. Flipping it is reversible.
CTF_WORKSPACE_SPA_ENABLED = _env_bool("CTF_WORKSPACE_SPA_ENABLED", False)

# Administer workspace SPA rollout flag (issue #1373, ADR-013 / ADR-029). When
# enabled (together with PLATFORM_SPA_ENABLED), the Administer GET page paths
# under /administer/ (Users, Cost, Platform Settings) are served by the React SPA
# host view; the canonical /api/v1/administer/ DRF routes are unaffected either
# way. Django admin at /admin/ stays mapped to admin.site.urls in every rollout
# state and is never wrapped by the SPA. Non-secret boolean; absent env means
# disabled. Flipping it is reversible.
ADMINISTER_SPA_ENABLED = _env_bool("ADMINISTER_SPA_ENABLED", False)
