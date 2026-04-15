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

### Flag 21 — Compartment A
- **Difficulty:** Easy
- **Location:** Connect to the database with discovered credentials. Query `compartment_a.structural_specs` — it's readable with the default `lab-general` role. The flag is in a row where the `component` column is "frame_dorsal_plate" and the `notes` column contains the flag.
- **Flag:** `FLAG{4b9e2a7d0c8f1365}`
- **Mission:** Mission 3 — The Lab

### Flag 27 — Compartment B
- **Difficulty:** Medium
- **Location:** `compartment_b` is restricted to `lab-weapons` role. Getting access requires either: (a) finding the weapons team credentials on A6 or in the database's own `pg_authid` table if you can escalate, (b) SQL injection via a stored procedure that crosses compartment boundaries, or (c) discovering a database link/foreign data wrapper that's misconfigured. Once in, query `effector_systems`. The flag is in the `serial_number` column of the directed energy array row.
- **Flag:** `FLAG{6d1a8f3c7e0b4952}`
- **Mission:** Mission 3 — The Lab

### Flag 28 — What's Built
- **Difficulty:** Hard
- **Location:** `compartment_c.assembly_log` requires `lab-manufacturing` role. The table shows every subsystem with a status column. Most read "COMPLETE." Two read "PENDING: Primary power source" and "PENDING: Autonomous control activation." The flag is in a `metadata` JSONB column on the final row — the one that says "FINAL ASSEMBLY: Awaiting reactor installation. Target: next week." The JSONB contains nested data and the flag is buried three levels deep.
- **Flag:** `FLAG{a3f7d9e1c0b52846}`
- **Mission:** Mission 3 — The Lab

---

## Build Plan

**Base image:** postgres:16-alpine

**Content directory:** `scenario-dev/polaris/build/A8-research-database/`

### Steps

1. **Configure PostgreSQL**
   - Listen on standard port 5432
   - Accept connections from Lab zone IPs
   - Create databases: `research_public`, `compartment_a`, `compartment_b`, `compartment_c`

2. **Create roles with compartment access**
   - `lab-general` — can read `research_public` and `compartment_a`
   - `lab-weapons` — can read `compartment_b`
   - `lab-manufacturing` — can read `compartment_c`
   - Initial credentials discoverable from A6 config files or A2 service accounts
   - Users mapped to roles: e.g., tanaka gets `lab-general`, vasik gets all

3. **Populate research_public**
   - `publications` table — mundane internal research papers
   - `personnel` table — researcher list with specializations

4. **Populate compartment_a (structural)**
   - `materials_tests` — alloy stress test results (titanium-tungsten)
   - `structural_specs` — dimensions including 120.4m height, 48,000 metric tons. Flag 21 in `notes` column for `frame_dorsal_plate` row.
   - `supplier_records` — cross-references A4 procurement orders

5. **Populate compartment_b (weapons)**
   - `effector_systems` — directed energy array 2.4 GW, kinetic weapons. Flag 27 in `serial_number` column.
   - `targeting_algorithms` — references A7 navigation AI
   - `power_requirements` — 1.8 GW sustained draw
   - Also store Vasik's GPG private key as base64 blob in a table (needed for A6 flag 30 chain)

6. **Populate compartment_c (manufacturing)**
   - `assembly_log` — line-by-line build status for every subsystem, most COMPLETE, two PENDING
   - `qa_results` — quality assurance outcomes
   - `delivery_schedule` — upcoming reactor delivery
   - Flag 28 in `metadata` JSONB column on final assembly_log row, nested 3 levels deep

7. **Implement compartment pivot vulnerability (for flag 27)**
   - **Chosen: SECURITY DEFINER stored procedure with SQL injection.**
   - `research_public` has a function `search_research(text)` owned by a superuser-adjacent role
   - The function is `SECURITY DEFINER` (runs as owner, not caller)
   - It concatenates the search term into a query without parameterization
   - Participants can inject SQL to query `compartment_b` tables through this function
   - Example: `SELECT search_research('x'' UNION SELECT serial_number FROM compartment_b.effector_systems--')`

8. **Implement `lab-manufacturing` access path (for flag 28)**
   - **Chosen: credential on A6.** Nielsen's `.pgpass` on A6 contains DB creds for `lab_mfg` user
   - This ties into A6 flag 26 (need to access Nielsen's home dir first)
   - `.pgpass` entry: `researchdb.boreas.local:5432:compartment_c:lab_mfg:Mfg2025!`

9. **Write SQL init scripts**
   - `01-roles.sql` — create roles and users
   - `02-schemas.sql` — create databases and tables
   - `03-data.sql` — populate all tables with content
   - `04-permissions.sql` — set up GRANT/REVOKE for compartment isolation
   - `05-vulns.sql` — set up the privilege escalation path (FDW, stored proc, etc.)

10. **Write Dockerfile**
    - Start from postgres:16-alpine
    - Copy init SQL scripts to `/docker-entrypoint-initdb.d/`
    - Expose port 5432

### Build Notes

- **Init script:** `A8-research-database/01-init.sql` — single script, tested on PostgreSQL 15 (Debian 12)
- **Uses schemas not separate databases.** Simpler for a container — all in one DB with schema-level isolation.
- **SQLi vulnerability:** `research_public.search_research(text)` is `SECURITY DEFINER` owned by `research_bridge` role which has `lab_weapons` access. String concatenation allows UNION injection to query compartment_b.
- **Example injection:** `SELECT * FROM research_public.search_research('x'' UNION SELECT serial_number, system_name, system_type FROM compartment_b.effector_systems--');`
- **GPG key blob:** Stored in `compartment_b.key_storage` as base64 text (5527 chars). Participants extract with: `SELECT key_data FROM compartment_b.key_storage WHERE key_owner = 'e.vasik';` then `base64 -d | gpg --import`.
- **Override code piece AL42:** In `compartment_c.assembly_log` FINAL ASSEMBLY row, JSONB path `metadata->'integration'->'code'`.
- **Nielsen .pgpass added to A6:** `researchdb.boreas.local:5432:*:lab_mfg:Mfg2025!` in `/home/p.nielsen/.pgpass`
