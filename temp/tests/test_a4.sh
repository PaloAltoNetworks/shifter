#!/bin/bash
# Test A4 — File Share Documents
# Requires: A4 content at /tmp/a4-content/
# Tests: all flags, PDF integrity, XLSX content, directory structure

set -e

BASE="/tmp/a4-content"
[ -d "$BASE" ] || exit 77

python3 << 'PYEOF'
import sys, os, subprocess
import openpyxl
from pdfminer.high_level import extract_text as pdfminer_extract

BASE = "/tmp/a4-content"
errors = []

def check(name, cond, detail=""):
    if not cond:
        errors.append(f"FAIL: {name} — {detail}")
        print(f"  FAIL: {name} — {detail}", file=sys.stderr)

def pdf_text(path):
    """Extract text from PDF using pdfminer."""
    return pdfminer_extract(path)

def pdf_metadata(path):
    """Extract raw strings from PDF (catches metadata that pdfminer may skip)."""
    result = subprocess.run(["strings", path], capture_output=True, text=True)
    return result.stdout

# === Directory structure ===
for d in ["Public", "HR/personnel", "Procurement/specs", "IT", "Executive"]:
    check(f"dir {d} exists", os.path.isdir(os.path.join(BASE, d)))

# === All 16 files exist and are non-empty ===
expected_files = [
    "Public/cafeteria_menu_april.pdf",
    "Public/parking_policy_2025.pdf",
    "Public/office_floorplan.pdf",
    "HR/personnel/chen_james_termination.pdf",
    "HR/personnel/chen_james_nda.pdf",
    "HR/org_chart_current.xlsx",
    "Procurement/PO-2847_hydraulic_actuators.pdf",
    "Procurement/specs/actuator_requirements_v4.pdf",
    "Procurement/PO-3102_servo_motors.pdf",
    "Procurement/PO-3455_exotic_alloys.pdf",
    "Procurement/invoice_reactor_deposit.pdf",
    "IT/network_diagram.pdf",
    "IT/server_inventory.xlsx",
    "IT/backup_verification.log",
    "Executive/board_minutes_Q3_2025.pdf",
    "Executive/budget_summary_2025.pdf",
]
for f in expected_files:
    path = os.path.join(BASE, f)
    check(f"file exists: {f}", os.path.isfile(path), "missing")
    if os.path.isfile(path):
        check(f"file non-empty: {f}", os.path.getsize(path) > 100, f"size={os.path.getsize(path)}")

# === Flag 9: Chen termination case reference (page 2) ===
text = pdf_text(os.path.join(BASE, "HR/personnel/chen_james_termination.pdf"))
check("flag 9 in chen termination", "FLAG{7a1b3d9e2c8f0546}" in text, "flag not found")
check("chen termination mentions security policy", "Information Security Policy" in text or "security policy" in text.lower())
check("chen termination mentions PO-2847", "PO-2847" in text)

# === Flag 11: Cafeteria menu PDF Author metadata ===
text = pdf_metadata(os.path.join(BASE, "Public/cafeteria_menu_april.pdf"))
check("flag 11 in cafeteria PDF metadata", "FLAG{0e6f9c2d4a8b7135}" in text, "flag not in metadata")

# === Flag 13: Actuator requirements spec ===
text = pdf_text(os.path.join(BASE, "Procurement/specs/actuator_requirements_v4.pdf"))
check("flag 13 in actuator spec", "FLAG{8c5a0d3f7e1b2964}" in text, "flag not found")
check("actuator spec mentions 200 tons", "200" in text)
check("actuator spec mentions bipedal", "bipedal" in text.lower())

# === Flag 15: Backup verification log ===
with open(os.path.join(BASE, "IT/backup_verification.log")) as f:
    log_text = f.read()
check("flag 15 in backup log", "FLAG{9a4c7e2f58d0b163}" in log_text)
check("backup log mentions svc-backup", "svc-backup" in log_text)

# === PO-2847 references specs subdirectory ===
text = pdf_text(os.path.join(BASE, "Procurement/PO-2847_hydraulic_actuators.pdf"))
check("PO-2847 references specs/", "specs/" in text or "actuator_requirements" in text)
check("PO-2847 mentions Kursk", "Kursk" in text)
check("PO-2847 mentions $12,000,000", "12,000,000" in text)

# === Org chart XLSX ===
wb = openpyxl.load_workbook(os.path.join(BASE, "HR/org_chart_current.xlsx"))
ws = wb.active
all_values = []
for row in ws.iter_rows(min_row=2, values_only=True):
    all_values.extend([str(v) for v in row if v])
combined = " ".join(all_values)
check("org chart has Underground Operations", "Underground Operations" in combined)
check("org chart has James Chen terminated", "TERMINATED" in combined)
check("org chart has Vasik", "Vasik" in combined)

# === Server inventory XLSX ===
wb = openpyxl.load_workbook(os.path.join(BASE, "IT/server_inventory.xlsx"))
ws = wb.active
all_values = []
for row in ws.iter_rows(min_row=2, values_only=True):
    all_values.extend([str(v) for v in row if v])
combined = " ".join(all_values)
check("server inventory has scada-gw", "scada-gw" in combined)
check("server inventory has VLAN 40", "40" in combined)
check("server inventory has researchdb", "researchdb" in combined)

# === Network diagram mentions VLAN 50 ===
text = pdf_text(os.path.join(BASE, "IT/network_diagram.pdf"))
check("network diagram shows VLAN 50", "50" in text and ("OFFLINE" in text or "Underground" in text))

# === Parking policy mentions Lot B restricted ===
text = pdf_text(os.path.join(BASE, "Public/parking_policy_2025.pdf"))
check("parking policy mentions Lot B", "Lot B" in text)
check("parking policy mentions badge required", "badge" in text.lower())

# === Reactor invoice ===
text = pdf_text(os.path.join(BASE, "Procurement/invoice_reactor_deposit.pdf"))
check("reactor invoice mentions Novikov", "Novikov" in text)
check("reactor invoice mentions $45,000,000", "45,000,000" in text)
check("reactor invoice mentions NV-3200", "NV-3200" in text)

# === Budget summary has classified line ===
text = pdf_text(os.path.join(BASE, "Executive/budget_summary_2025.pdf"))
check("budget has classified program line", "classified" in text.lower())
check("budget shows $95M program", "95" in text)

if errors:
    print(f"\n{len(errors)} checks failed:", file=sys.stderr)
    for e in errors: print(f"  {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
