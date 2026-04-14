# A4: File Share

**Zone:** Front Office (per participant)
**Type:** SMB/CIFS file server (Samba)

## Purpose

Corporate file share for Boreas Systems. Contains HR documents, procurement records, contracts, and internal memos. This is where the mundane-but-telling paperwork lives — the procurement anomalies, the terminated engineer's personnel file, and the everyday office artifacts that make the cover story feel real.

## Configuration

- Samba file server with SMB shares
- Authenticated access (domain accounts from A2, or service account creds from A1)
- Multiple shares with different permission levels
- Some shares misconfigured with overly broad read access

## Shares


| Share Name    | Access                         | Contents                                                              |
| ------------- | ------------------------------ | --------------------------------------------------------------------- |
| `Public`      | All authenticated users        | Cafeteria menus, holiday calendar, parking policy, office floor plans |
| `HR`          | HR group + Executives          | Personnel files, termination records, org charts                      |
| `Procurement` | Procurement group + Executives | Purchase orders, invoices, supplier contracts                         |
| `IT`          | IT group                       | Network diagrams, server inventory, backup scripts                    |
| `Executive`   | Executives only                | Board meeting minutes, budget summaries                               |


## Key Documents

### Public Share

- `cafeteria_menu_april.pdf` — actual cafeteria menu. Passive-aggressive note about the coffee machine taped to the bottom.
- `parking_policy_2025.pdf` — mentions "restricted lot B" for "project staff only"
- `office_floorplan.pdf` — surface building only. No underground levels shown.

### HR Share

- `personnel/chen_james_termination.pdf` — termination letter. Reason: "violation of information security policy." Effective immediately.
- `personnel/chen_james_nda.pdf` — NDA with unusually broad scope covering "all programs, projects, and research activities"
- `org_chart_current.xlsx` — shows reporting structure. Some roles have no names filled in. "Director, Underground Operations" reports to Vasik.

### Procurement Share

- `PO-2847_hydraulic_actuators.pdf` — Purchase order to Kursk Heavy Industries. 48 units, rated for 200-ton force. $12M.
- `PO-3102_servo_motors.pdf` — High-torque servo motors from a German manufacturer. Specs reference "rotational joint assembly."
- `PO-3455_exotic_alloys.pdf` — Titanium-tungsten alloy plates, heat-treated for extreme stress tolerance. Supplier note: "custom specification per your engineering team."
- `invoice_reactor_deposit.pdf` — 30% deposit to "Novikov Energy Systems" for "compact power generation unit." $45M total contract.

### IT Share

- `network_diagram.vsd` — shows VLANs. VLAN 10 (Corporate), VLAN 20 (Security), VLAN 30 (Lab), VLAN 40 (SCADA/OT). VLAN 50 is labeled "OFFLINE — Underground" with no connections drawn.
- `server_inventory.xlsx` — lists all servers including scada-gw and its IP

## Flags

### Flag 9 — HR records — terminated engineer

- **Difficulty:** Easy
- **Location:** `\\fileshare\HR\personnel\chen_james_termination.pdf`. The flag is on the second page of the PDF in a "case reference number" field.
- **Flag:** `FLAG{7a1b3d9e2c8f0546}`
- **Mission:** M1

### Flag 11 — Cafeteria menu / mundane file share

- **Difficulty:** Easy
- **Location:** `\\fileshare\Public\cafeteria_menu_april.pdf`. The flag is hidden in the PDF metadata (Author field). This is a gimme flag to reward basic enumeration of the share.
- **Flag:** `FLAG{0e6f9c2d4a8b7135}`
- **Mission:** M1

### Flag 13 — Procurement orders — hydraulic actuators

- **Difficulty:** Medium
- **Location:** `\\fileshare\Procurement\PO-2847_hydraulic_actuators.pdf`. The flag is not on the PO itself — it's in a linked document referenced in the PO's "special instructions" field: a specifications PDF stored in a subdirectory `\\fileshare\Procurement\specs\actuator_requirements_v4.pdf`. Requires reading the PO carefully and following the reference.
- **Flag:** `FLAG{8c5a0d3f7e1b2964}`
- **Mission:** M1, M2

---

## Build Plan

**Base image:** debian:bookworm-slim (Samba file server)

**Content directory:** `scenario-dev/polaris/build/A4-file-share/`

### Steps

1. **Install and configure Samba (standalone file server)**
   - Not a DC — standalone mode, or joined to A2 domain if auth integration works
   - If standalone: local user accounts mirroring A2 users + service accounts
   - If domain-joined: authenticate against A2's Samba AD DC

2. **Create SMB shares with permissions**
   - `Public` — all authenticated users (read)
   - `HR` — HR group + Executives (read)
   - `Procurement` — Procurement group + Executives (read)
   - `IT` — IT group only (read). Service account from Kowalski's email on A1 can also access.
   - `Executive` — Executives only (read)

3. **Create Public share documents**
   - `cafeteria_menu_april.pdf` — actual menu with passive-aggressive coffee machine note. Flag 11 in PDF Author metadata field.
   - `parking_policy_2025.pdf` — mentions restricted lot B for project staff
   - `office_floorplan.pdf` — surface building only, no underground levels

4. **Create HR share documents**
   - `personnel/chen_james_termination.pdf` — termination letter, case reference number on page 2 is flag 9
   - `personnel/chen_james_nda.pdf` — NDA with broad scope
   - `org_chart_current.xlsx` — reporting structure with blank names, "Director, Underground Operations" role

5. **Create Procurement share documents**
   - `PO-2847_hydraulic_actuators.pdf` — Kursk Heavy Industries, 48 units, 200-ton force, $12M. "Special instructions" field references specs subdirectory.
   - `specs/actuator_requirements_v4.pdf` — the linked document containing flag 13
   - `PO-3102_servo_motors.pdf` — German manufacturer, rotational joint assembly
   - `PO-3455_exotic_alloys.pdf` — titanium-tungsten alloy plates
   - `invoice_reactor_deposit.pdf` — Novikov Energy Systems, $45M compact power generation unit

6. **Create IT share documents**
   - `network_diagram.vsd` (or .png/.pdf) — VLANs 10-50, VLAN 50 labeled "OFFLINE — Underground"
   - `server_inventory.xlsx` — all servers including scada-gw IP
   - `backup_verification.log` — accessible only via IT service account creds (from A1 Kowalski email). Contains flag 15.

7. **Create Executive share documents**
   - Board meeting minutes (mundane)
   - Budget summaries (one line item is suspicious)

8. **Embed flags**
   - Flag 9: Case reference number on page 2 of Chen termination PDF
   - Flag 11: PDF Author metadata field on cafeteria menu
   - Flag 13: In `specs/actuator_requirements_v4.pdf` (linked from PO-2847 special instructions)
   - Flag 15: In `IT/backup_verification.log` (only accessible with service account creds from A1)

9. **Write Dockerfile**
   - Install Samba
   - Copy share directory structure and all documents
   - Copy smb.conf with share definitions and permissions
   - Entrypoint: create users/groups, set passwords, start smbd/nmbd
   - Expose ports 139, 445
