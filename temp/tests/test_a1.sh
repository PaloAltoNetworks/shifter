#!/bin/bash
# Test A1 — Mail Server Content
# Requires: A1 content at /tmp/a1-content/
# Tests: all EML files, flags, attachments, narrative content

set -e

BASE="/tmp/a1-content"
[ -d "$BASE" ] || exit 77

python3 << 'PYEOF'
import sys, os, email, subprocess
from email import policy
import openpyxl
from pdfminer.high_level import extract_text

BASE = "/tmp/a1-content"
errors = []

def check(name, cond, detail=""):
    if not cond:
        errors.append(f"FAIL: {name} — {detail}")
        print(f"  FAIL: {name} — {detail}", file=sys.stderr)

def read_eml(folder, filename):
    """Parse an EML file and return (headers_dict, body_text, attachments)."""
    path = os.path.join(BASE, folder, filename)
    with open(path) as f:
        msg = email.message_from_file(f, policy=policy.default)
    body = ""
    attachments = []
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                body += part.get_content()
            elif part.get_filename():
                attachments.append((part.get_filename(), part.get_payload(decode=True)))
    else:
        body = msg.get_content()
    return dict(msg.items()), body, attachments

# === Directory structure — 6 mailboxes + attachments ===
for d in ["v.harlan", "e.vasik", "m.webb", "j.chen", "d.kowalski", "s.morrison", "attachments"]:
    check(f"mailbox dir {d}", os.path.isdir(os.path.join(BASE, d)))

# === Harlan inbox (4 emails) ===
headers, body, _ = read_eml("v.harlan", "01_board_forward.eml")
check("harlan: board forward exists", "board" in headers.get("From", "").lower() or "timeline" in body.lower())

headers, body, _ = read_eml("v.harlan", "02_to_vasik.eml")
check("harlan: locomotion question", "locomotion" in body.lower())
check("harlan: mentions principals", "principals" in body.lower())

# === Vasik inbox — flag 8 in PDF attachment ===
headers, body, attachments = read_eml("e.vasik", "02_status_with_attachment.eml")
check("vasik: has attachment", len(attachments) > 0, f"found {len(attachments)}")
if attachments:
    fname, data = attachments[0]
    check("vasik: attachment is PDF", fname.endswith(".pdf"), f"name={fname}")
    # Write to temp and extract text
    tmp_pdf = "/tmp/a1_test_status.pdf"
    with open(tmp_pdf, "wb") as f:
        f.write(data)
    pdf_text = extract_text(tmp_pdf)
    check("flag 8 in status report PDF", "FLAG{3b7e9a2d1c8f4063}" in pdf_text, "flag not in PDF")
    check("status report mentions 120m", "120" in pdf_text)
    check("status report mentions MIDNIGHT-7", "MIDNIGHT" in pdf_text)
    os.unlink(tmp_pdf)

headers, body, _ = read_eml("e.vasik", "03_midnight7_results.eml")
check("vasik: MIDNIGHT-7 thread", "MIDNIGHT" in body and "bipedal" in body.lower())

headers, body, _ = read_eml("e.vasik", "04_kursk_expedite.eml")
check("vasik: Kursk expedite", "Kursk" in body and "PO-2847" in body)

# === Chen inbox — narrative thread ===
headers, body, _ = read_eml("j.chen", "01_po_question.eml")
check("chen: asks about PO-2847", "PO-2847" in body)
check("chen: mentions 200 tons", "200 ton" in body.lower() or "200 tons" in body.lower())

headers, body, _ = read_eml("j.chen", "02_manager_reply.eml")
check("chen: clearance rebuke", "clearance" in body.lower())

headers, body, _ = read_eml("j.chen", "03_chen_followup.eml")
check("chen: weapons program question", "weapons" in body.lower())

headers, body, _ = read_eml("j.chen", "04_termination.eml")
check("chen: termination notice", "terminated" in body.lower() or "termination" in body.lower())
check("chen: security policy violation", "security policy" in body.lower() or "Information Security" in body)

# === Kowalski inbox — flag 10, creds backup ===
headers, body, _ = read_eml("d.kowalski", "01_welcome.eml")
check("flag 10 in welcome email", "FLAG{e5d1f8c2a7b03946}" in body, "flag not found")

headers, body, _ = read_eml("d.kowalski", "02_creds_backup.eml")
check("kowalski: creds backup has wiki admin", "admin" in body and "admin" in body)
check("kowalski: creds backup has file share creds", "fileserv" in body.lower() or "fileshare" in body.lower())
check("kowalski: creds backup has svc-fileshare password", "F1l3Sh@r3Svc!" in body)

headers, body, _ = read_eml("d.kowalski", "03_scada_vlan.eml")
check("kowalski: SCADA VLAN 40", "VLAN 40" in body)
check("kowalski: scada-gw address", "scada-gw" in body.lower() or "10.10.40" in body)

# === Morrison inbox — guard rotation, Petrov concerns ===
headers, body, attachments = read_eml("s.morrison", "01_rotation_schedule.eml")
check("morrison: has rotation attachment", len(attachments) > 0)
if attachments:
    fname, data = attachments[0]
    check("morrison: attachment is xlsx", fname.endswith(".xlsx"), f"name={fname}")
    tmp_xlsx = "/tmp/a1_test_rotation.xlsx"
    with open(tmp_xlsx, "wb") as f:
        f.write(data)
    wb = openpyxl.load_workbook(tmp_xlsx)
    ws = wb.active
    # Check Petrov entries exist
    petrov_found = False
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[2] and "Petrov" in str(row[2]):
            petrov_found = True
            break
    check("rotation has Petrov entries", petrov_found)
    os.unlink(tmp_xlsx)

headers, body, _ = read_eml("s.morrison", "02_petrov_access.eml")
check("morrison: Petrov underground hatch", "underground hatch" in body.lower() or "hatch" in body.lower())
check("morrison: Petrov 02:00 AM access", "02:00" in body or "2:00" in body)
check("morrison: recommends terminate Petrov", "terminate" in body.lower())

# === Webb inbox ===
headers, body, _ = read_eml("m.webb", "01_kursk_response.eml")
check("webb: Kursk expedite response", "Kursk" in body and "expedite" in body.lower())

headers, body, _ = read_eml("m.webb", "02_reactor_logistics.eml")
check("webb: Novikov delivery", "Novikov" in body)
check("webb: November 25 delivery", "November 25" in body)
check("webb: underground access route", "underground" in body.lower())

# === Total email count ===
total_emls = sum(1 for d in os.listdir(BASE) if os.path.isdir(os.path.join(BASE, d))
                 for f in os.listdir(os.path.join(BASE, d)) if f.endswith(".eml"))
check("at least 20 emails total", total_emls >= 20, f"found {total_emls}")

if errors:
    print(f"\n{len(errors)} checks failed:", file=sys.stderr)
    for e in errors: print(f"  {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
