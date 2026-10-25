---
id: CTF-907
title: "MC + CTF Range Coexistence"
status: ACTIVE
type: CONSTRAINT
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:23.689350Z
updated_at: 2026-04-16T22:50:07.317157Z
---

# CTF-907: MC + CTF Range Coexistence

## Statement

CTF range instances and Mission Control range instances shall coexist without conflict because they share the same underlying CMS/Engine provisioning pipeline. CTF participants are standard platform users whose ranges are provisioned via cms.services.create_range(), the same path Mission Control uses. Resource quota enforcement, if needed, should be implemented at the Engine or CMS layer to apply uniformly to all range consumers, not as CTF-specific logic.

## Rationale

CTF events and Mission Control demos share provisioning infrastructure. Concurrent events must not starve other range consumers. Engine and CMS capacity controls must account for shared bottlenecks as well as per-range limits. PLAT-201 and CTF-908 refine capacity planning and advance event declarations.

## Traceability

- IMPLEMENTS → CODE_FILE `ctf/bridges.py` (CTF-CMS bridge module (shared provisioning path))
- IMPLEMENTS → CODE_FILE `ctf/models.py` (CTF models (event config, max_participants))
- IMPLEMENTS → CODE_FILE `cms/services.py` (CMS range creation service (shared infrastructure entry point))
- IMPLEMENTS → CODE_FILE `ctf/services/range.py` (CTF range provisioning service (throttled provisioning))
- IMPLEMENTS → CODE_FILE `mission_control/views.py` (Mission Control views (shared cms.services.create_range() call))
- IMPLEMENTS → CODE_FILE `shared/auth.py` (Shared auth (CTF participants as standard platform users via group membership))
- TESTS → TEST `tests/ctf/test_services/test_range.py` (CTF range provisioning tests (verifies shared CMS path))
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#546` (CTF-907: MC + CTF Range Coexistence)
