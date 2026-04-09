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
