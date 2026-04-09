# A8: Research Database

**Zone:** Lab (per participant)
**Type:** Database server (PostgreSQL or MySQL)

## Purpose

Compartmentalized research database used by AURORA's engineering teams. Each research compartment has its own schema/database, and access is segmented — a hydraulics researcher can't see weapons data. The flags require SQL skills, understanding database structure, and pivoting between compartments.

## Configuration

- PostgreSQL (or MySQL) on standard port
- Multiple databases/schemas representing compartments
- Role-based access — initial access gives read on one compartment
- Cross-compartment access requires privilege escalation or credential discovery
- Database credentials discoverable from A6 (engineering workstation config files) or A2 (AD service accounts)

## Databases / Schemas

| Database | Access Role | Contents |
|---|---|---|
| `research_public` | All Lab users | Published research summaries, boring reports |
| `compartment_a` | `lab-general` role | Structural engineering data, materials testing |
| `compartment_b` | `lab-weapons` role | Weapons system specifications, targeting data |
| `compartment_c` | `lab-manufacturing` role | Assembly status, build schedules, QA logs |

## Key Tables

### research_public
- `publications` — internal research papers, all mundane
- `personnel` — researcher list with specializations (useful for social engineering)

### compartment_a (structural)
- `materials_tests` — alloy stress test results. Titanium-tungsten at extreme loads.
- `structural_specs` — dimensions, load ratings. One entry: "Primary frame height: 120.4m. Total mass (unloaded): 48,000 metric tons."
- `supplier_records` — cross-references procurement orders from A4

### compartment_b (weapons)
- `effector_systems` — "Primary: directed energy array, 2.4 GW peak output. Secondary: kinetic impact, 4x arm-mounted."
- `targeting_algorithms` — references the navigation AI from A7
- `power_requirements` — "Primary effector requires dedicated reactor feed. Estimated draw: 1.8 GW sustained."

### compartment_c (manufacturing)
- `assembly_log` — line-by-line build status for every subsystem
- `qa_results` — quality assurance test outcomes
- `delivery_schedule` — upcoming component deliveries including the reactor

## Flags

### Flag 21 — Research file share — compartment A
- **Difficulty:** Easy
- **Location:** Connect to the database with discovered credentials. Query `compartment_a.structural_specs` — it's readable with the default `lab-general` role. The flag is in a row where the `component` column is "frame_dorsal_plate" and the `notes` column contains the flag.
- **Flag:** `FLAG{4b9e2a7d0c8f1365}`
- **Mission:** M2

### Flag 27 — Compartment pivot — weapons specs
- **Difficulty:** Medium
- **Location:** `compartment_b` is restricted to `lab-weapons` role. Getting access requires either: (a) finding the weapons team credentials on A6 or in the database's own `pg_authid` table if you can escalate, (b) SQL injection via a stored procedure that crosses compartment boundaries, or (c) discovering a database link/foreign data wrapper that's misconfigured. Once in, query `effector_systems`. The flag is in the `serial_number` column of the directed energy array row.
- **Flag:** `FLAG{6d1a8f3c7e0b4952}`
- **Mission:** M2

### Flag 28 — Assembly status log — what's complete
- **Difficulty:** Hard
- **Location:** `compartment_c.assembly_log` requires `lab-manufacturing` role. The table shows every subsystem with a status column. Most read "COMPLETE." Two read "PENDING: Primary power source" and "PENDING: Autonomous control activation." The flag is in a `metadata` JSONB column on the final row — the one that says "FINAL ASSEMBLY: Awaiting reactor installation. Target: next week." The JSONB contains nested data and the flag is buried three levels deep.
- **Flag:** `FLAG{a3f7d9e1c0b52846}`
- **Mission:** M2, M4
