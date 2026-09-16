# API-surface inventory (#1328)

Status: active

Issue: [#1328](https://github.com/Brad-Edwards/shifter/issues/1328) (part of the Workspaces and Platform API Program, [#1321](https://github.com/Brad-Edwards/shifter/issues/1321))

Companion: the versioned surface is published as a committed contract by
[#1329](https://github.com/Brad-Edwards/shifter/issues/1329)
(`shifter/shifter_platform/openapi/v1.json`, ADR-040).

This document classifies every HTTP route the platform exposes so app-local
JSON/data routes can be consolidated onto the versioned `/api/v1/` DRF surface.

## Classification scheme

- **A. Published**: already served under `/api/v1/`.
- **B. Consolidate**: app-local JSON/data with no `/api/v1/` equivalent; needs a
  new `/api/v1/` endpoint.
- **C. Stays**: template UI, SPA page host, or auth/infra route (not a data API).
- **D. Deprecate**: app-local JSON/data whose `/api/v1/` twin already exists; the
  old path is redundant once its consumers move to `/api/v1/`.

## Summary

| Class | Meaning | Count |
| --- | --- | --- |
| A | Already on `/api/v1/` | ~89 |
| B | Needs a new `/api/v1/` endpoint | 2 |
| C | Template UI / SPA page / auth-infra (stays) | ~70 |
| D | App-local JSON with an existing `/api/v1/` twin | 62 |

The `/api/v1/` surface is already comprehensive. The remaining work is narrow:
two missing CTF endpoints, and retiring 62 redundant app-local paths once their
consumers move off them.

## Class B: needs a new `/api/v1/` endpoint (2)

Both are organizer-scoped CTF JSON endpoints implemented in `ctf/views/api/`
with no `/api/v1/ctf/` route. Adding them via `ctf/api/urls.py` +
`ctf/api/views.py` (the `legacy_api_view` wrapper with `CTF_EVENT_WRITE`) reaches
full CTF parity:

1. `POST /ctf/api/events/<event_id>/spares/` (`api_provision_event_spares`).
2. `POST /ctf/api/participants/<participant_id>/range/recover/` (`api_recover_participant_range`).

## Class D: app-local JSON with an existing `/api/v1/` twin (62)

These paths duplicate a published `/api/v1/` operation, but they are **still
consumed by the active legacy template UIs**, so they cannot be removed until
those consumers move to `/api/v1/` or the legacy UI is retired.

- **Mission Control (21)**: every `/mission-control/api/*` route. These resolve
  to the identical DRF view objects as `/api/v1/mission-control/*` (mounted
  twice). Consumers: the legacy templates `mission_control/ngfw/*` and
  `mission_control/credentials/*`. The new SPA uses `/api/v1/` only.
- **CTF (39)**: every `/ctf/api/*` route except the two Class B endpoints. Same
  underlying `ctf.views.api.*` functions; `/api/v1/ctf/*` adds token scopes.
  Consumers: `static/js/ctf-ranges.js`, `static/js/admin-participant-detail.js`,
  `templates/ctf/admin/participant_list.html`. CTF is not SPA-ported ([#1372](https://github.com/Brad-Edwards/shifter/issues/1372)).
- **Scenario editor (2)**: `/scenario-editor/validate-yaml/` and
  `/scenario-editor/<id>/export/`. Twins live under `/api/v1/cms/scenario-editor/`;
  the SPA already uses the `/api/v1/` versions, so these have no remaining
  consumer and are the safest to retire.

## Class C notes

- Scenario-editor mutation routes are form-POST handlers that return a redirect
  (template UI), not JSON. Their data operations are fully covered by
  `/api/v1/`, so they retire with the legacy templates during SPA cutover, not
  as an API-consolidation step.
- `/auth/identity/session/` returns JSON but is session-mint auth plumbing (like
  `/oidc/`); it stays outside the versioned surface by design.
- `/health` and `/health/` are intentionally duplicated (the no-slash variant is
  for the AWS ALB target group, which does not follow redirects).

## Oddities

1. **Mission Control duplicate mounts**: `/mission-control/api/*` and
   `/api/v1/mission-control/*` are the same `View.as_view()` objects mounted at
   two paths.
2. **CTF scoreboard twin is not behavior-equivalent**: legacy
   `/ctf/api/events/<id>/scoreboard/` is organizer-authenticated, while
   `/api/v1/ctf/events/<id>/scoreboard/` (`PublicScoreboardView`) is public and
   honors freeze/visibility. Retiring the legacy path requires confirming the
   public view covers the organizer use case or adding an authenticated variant.
3. **CTF auth split**: legacy `/ctf/api/*` is session-only; `/api/v1/ctf/*` adds
   scoped token auth. Consolidating removes the split.

## Consolidation sequence

1. Add the two Class B CTF endpoints to `/api/v1/ctf/` (additive; passes the
   breaking-change gate).
2. Retire the scenario-editor Class D pair (no remaining consumer).
3. Move the CTF legacy UI JavaScript to `/api/v1/ctf/*`, then retire `/ctf/api/*`
   (except where the scoreboard semantics differ).
4. Move (or retire with the legacy pages) the Mission Control `ngfw`/`credentials`
   templates off `/mission-control/api/*`, then delete the duplicate mounts.

CTF (`ctf.*`) is currently excluded from the published contract until its SPA
consumer lands (#1372); the Class B additions live at runtime and enter the
committed contract when CTF is un-excluded.
