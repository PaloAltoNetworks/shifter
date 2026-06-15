# Portal Context-Processor Cost Audit (#852)

Status: diagnostic finding (analytical)

Date: 2026-06-07

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/852>

Companion preflight: [`portal-context-processor-preflight-852.md`](portal-context-processor-preflight-852.md)

## Method and scope

This audit is **analytical**: per-render database work is derived by reading
the registered context processors and the service calls they make, and counting
the ORM queries each issues. Query count is used as the cost proxy because every
contributing processor is DB-bound (no CPU-heavy or network work beyond the
engine ORM lookup). No empirical wall-time / p95 measurement was run; that was
deliberately out of scope for this pass. The preflight note proposes a local
`Client` + `CaptureQueriesContext` measurement harness as the empirical evidence
bar — see [Decision](#ac3-decision-does-684-cover-this) for how that is routed.

**Where context processors run.** Django template context processors execute
**only on HTML template renders**. They do **not** run for:

- DRF / JSON API responses,
- the terminal WebSocket stream (`mission_control/consumers.py`),
- any `JsonResponse`-based polling (range status, scoreboard refresh).

So the per-request cost is paid on **full page navigations**, not on the
high-frequency XHR/WebSocket traffic that dominates an active event session.
This materially bounds the blast radius and is itself an AC#4 finding.

## AC#1 — Per-render query cost

Custom processors are registered in
`shifter/shifter_platform/config/settings.py` (`TEMPLATES → OPTIONS →
context_processors`, the four `mission_control` / `shared` / `ctf` entries).

| Processor | Queries per authenticated render | Source |
| --- | --- | --- |
| `mission_control.active_range` | **1** baseline: latest `RangeInstance` (`filter(user_id).exclude(DESTROYING).order_by("-created_at").first()`). When a range exists: **+1** engine cross-layer (`_resolve_runtime_ips` → `engine.services.get_instance_ips_by_uuid` → `Range.objects.get(id)`), **+1** `instance.agent` FK, **+1** `instance.request` FK (no `select_related`), **+1** `is_ctf_participant_only`, **+1** `get_scenario` (registry, DB-first). → **1 (no range) … ~6 (ready range)** | `cms/services/_range_queries.py:225`, `cms/services/_common.py:227`, `engine/services/_range.py:358` |
| `mission_control.terminal_cdn_assets` | **0** — returns a settings dict | `mission_control/context_processors.py:18` |
| `shared.user_permissions` | **1** — `can_edit_cms_authoring` → `user.groups.filter(THREAT_RESEARCH).exists()`; **0** for staff (short-circuits before the query) | `shared/auth.py:60` |
| `ctf.ctf_navigation` | `get_user_role`: **2** group `.exists()` + (participant) **1** `get_user_profile` `get_or_create` + **1** `CTFEvent…first()`; **plus** a second `is_ctf_participant_only` (**1**). → **~3 (non-participant) … ~5 (active participant)** | `ctf/bridges.py:29`, `shared/auth.py:38`, `management/services.py:59` |

**Worst case = the live-event participant the issue is about** (CTF participant +
active range + active event): **~12 queries per page render**. Participant
without a range: ~7. Staff with a range: ~7.

## AC#2 — Material contributors

1. **`active_range`** — heaviest. Fans into the **engine layer** on every render
   where a range exists, and does a 2-query FK **N+1** (`agent`, `request`) that
   a single `select_related("agent", "request")` would erase.
2. **`ctf_navigation`** — most queries for participants (group ×2 + profile +
   event + a redundant `is_ctf_participant_only`).
3. **Redundant `auth_user_groups` lookups** — `user.groups` is queried **5
   separate times** per render and never cached:
   `is_ctf_participant_only` (in `active_range`), `can_edit_cms_authoring` (in
   `user_permissions`), two `get_user_role` `.exists()` calls, and a second
   `is_ctf_participant_only` (in `ctf_navigation`). `is_ctf_participant_only`
   is literally invoked **twice** per render. One request-scoped group fetch
   collapses all five into one.
4. `terminal_cdn_assets` and `user_permissions` are individually negligible
   (0 and 1 query); the latter's single query is part of the group-lookup
   redundancy above.

## AC#4 — Where the global behaviour is genuinely required

| Context | Required on | Not required on |
| --- | --- | --- |
| Full `active_range` payload (`RangeContext.instances`, runtime IP overlay, `connection_urls`, `terminal_instances`) | The terminal page (`mission_control/terminal.html`) | Everything else. The shared sidebar needs only a cheap `has_active_range` indicator, not the full payload. |
| `has_active_range` indicator | Mission Control sidebar / dashboard banner | Anonymous, JSON, and WebSocket paths |
| `ctf_navigation` role/event flags | Authenticated MC pages that render the CTF sidebar (`ctf/base.html`) | Anonymous, JSON, and WebSocket paths |
| `user_permissions` (`can_access_threat_research`) | Pages rendering the Threat Research / CMS authoring links | Anonymous, JSON, and WebSocket paths |
| `terminal_cdn_assets` | Terminal template only | Everywhere else (harmless — settings-only) |

The architectural lever (deferred to follow-up, not done here): these are
registered **globally and eagerly**. The full active-range payload is a
terminal-page concern wrongly paid on every render. Note the preflight caveat —
a `SimpleLazyObject` is **not** automatically cheaper if a globally-included
template (e.g. `icon_sidebar.html`, `ctf/base.html`) reads the variable on every
page; the real fix is page-scoped/tiered context (`none` / `nav` / `ctf` /
`terminal_full`), not blind laziness.

## AC#3 — Decision: does #684 cover this?

**Partially. No, not on its own.**

#684 ("Refactor Mission Control terminal and context god modules") has the
acceptance criterion *"active_range() context assembly is extracted into a
focused projection/service path"* — so it owns the **structural decomposition**
of `active_range`. But #684 is a god-module refactor, not a per-request cost
change. It does **not** cover:

- the per-request laziness / page-scoping that stops non-terminal pages paying
  for the full payload,
- the redundant `auth_user_groups` lookups and the double `is_ctf_participant_only`,
- the `select_related("agent", "request")` N+1 fix,
- `ctf_navigation` / `user_permissions` cost,
- the empirical measurement harness and safe-page documentation.

These are small and independent of the god-module refactor, so they are routed
to a dedicated follow-up issue (see below). #684 stays valid for the structural
work; this audit does not subsume it.

## Recommended follow-ups

1. **Per-request context-processor cost reduction** (new issue): request-scope
   the group lookups (collapses 5 → 1, removes the double
   `is_ctf_participant_only`), add `select_related("agent", "request")` to
   `get_active_range`, and make the full active-range payload terminal-page-scoped
   rather than global (per the preflight's `none`/`nav`/`ctf`/`terminal_full`
   seam). Land with the local `Client` + `CaptureQueriesContext` rendered-page
   evidence the preflight specifies.
2. #684 retains ownership of the `active_range` structural extraction.

## Deviation note

Per explicit direction on the tracking issue, this pass is **analytical only**.
The preflight note sets an empirical evidence bar (rendered-page query/SQL/wall
time + p50/p95 via `CaptureQueriesContext`). That empirical measurement is
**deferred to the follow-up implementation issue** above, where the query-count
reductions can be proven against rendered pages, rather than blocking this
diagnostic/decision pass.
