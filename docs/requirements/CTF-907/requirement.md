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

Shifter's infrastructure serves both CTF events and regular Mission Control demo environments. A CTF event provisioning 50 ranges must not starve Mission Control users who need ranges for customer demos. Resource isolation and quotas ensure peaceful coexistence of the two workloads on shared infrastructure. Note: polaris at Ottawa BSides validated that the "if needed" enforcement deferral in this requirement is already overdue, the concern is broader than static quotas and includes anticipatory capacity planning. See PLAT-201 (Capacity-Aware Provisioning) and CTF-908 (Event Capacity Declaration) for the concrete refinements.

## Traceability

- IMPLEMENTS → CODE_FILE `ctf/bridges.py` (CTF-CMS bridge module (shared provisioning path))
- IMPLEMENTS → CODE_FILE `ctf/models.py` (CTF models (event config, max_participants))
- IMPLEMENTS → CODE_FILE `cms/services.py` (CMS range creation service (shared infrastructure entry point))
- IMPLEMENTS → CODE_FILE `ctf/services/range.py` (CTF range provisioning service (throttled provisioning))
- IMPLEMENTS → CODE_FILE `mission_control/views.py` (Mission Control views (shared cms.services.create_range() call))
- IMPLEMENTS → CODE_FILE `shared/auth.py` (Shared auth (CTF participants as standard platform users via group membership))
- TESTS → TEST `tests/ctf/test_services/test_range.py` (CTF range provisioning tests (verifies shared CMS path))
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#546` (CTF-907: MC + CTF Range Coexistence)
