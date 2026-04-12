#!/usr/bin/env python3
"""
A1 Mail Server smoketest.

Runs every flag path from an attacker's perspective. Intended to be executed
from inside the a14-kali container (or any host on the corporate network that
can resolve mail.boreas.local via the DNS sidecar). Every assertion mirrors
what a participant would do in a walkthrough.

Usage (from the range host):
    docker exec a14-kali python3 /tmp/a1-smoke.py
Or:
    docker cp smoketest.py a14-kali:/tmp/a1-smoke.py
    docker exec a14-kali python3 /tmp/a1-smoke.py

Exits 0 on full pass, 1 on any failure.
"""
import email
import imaplib
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from email.policy import default
from http.cookiejar import CookieJar

HOST = os.environ.get("A1_HOST", "mail.boreas.local")
TMP = "/tmp/a1-smoke"
os.makedirs(TMP, exist_ok=True)

ACCOUNTS = [
    ("v.harlan", "Boreas2025!"),
    ("e.vasik", "Reactor#Core9"),
    ("m.webb", "Welcome1"),
    ("j.chen", "Summer2024"),
    ("d.kowalski", "P@ssw0rd123"),
    ("s.morrison", "Br3ach!ng"),
]

EXPECTED_FLAG_8 = "FLAG{3b7e9a2d1c8f4063}"
EXPECTED_FLAG_10 = "FLAG{e5d1f8c2a7b03946}"

fails = 0


def pass_(label):
    print(f"  [PASS] {label}")


def fail(label):
    global fails
    fails += 1
    print(f"  [FAIL] {label}")


def check(label, cond):
    (pass_ if cond else fail)(label)
    return cond


def fetch_inbox(user, pw):
    M = imaplib.IMAP4(HOST, 143)
    M.login(user, pw)
    M.select("INBOX")
    typ, data = M.search(None, "ALL")
    msgs = []
    for mid in (data[0] or b"").split():
        typ, resp = M.fetch(mid, "(RFC822)")
        parsed = email.message_from_bytes(resp[0][1], policy=default)
        msgs.append(parsed)
    M.logout()
    return msgs


def message_text(msg):
    if msg.is_multipart():
        return "\n".join(
            str(p.get_content())
            for p in msg.iter_parts()
            if p.get_content_type() == "text/plain"
        )
    return str(msg.get_content())


def pdf_to_text(path):
    if os.path.exists("/opt/tools/bin/pdf2txt.py"):
        r = subprocess.run(
            ["/opt/tools/bin/pdf2txt.py", path],
            capture_output=True, text=True, timeout=30,
        )
        return r.stdout
    r = subprocess.run(
        ["pdftotext", path, "-"],
        capture_output=True, text=True, timeout=30,
    )
    return r.stdout


print(f"A1 smoketest - target={HOST}")
print()
print("--- IMAP auth for all 6 accounts ---")
inboxes = {}
for user, pw in ACCOUNTS:
    try:
        inboxes[user] = fetch_inbox(user, pw)
        check(f"{user}: {len(inboxes[user])} messages", len(inboxes[user]) > 0)
    except Exception as e:
        fail(f"{user}: IMAP login failed - {e}")

print()
print("--- Flag 10: Kowalski welcome email via IMAP ---")
flag10_found = None
for msg in inboxes.get("d.kowalski", []):
    text = message_text(msg)
    m = re.search(r"FLAG\{[a-f0-9]+\}", text)
    if m and "Welcome" in (msg["Subject"] or ""):
        flag10_found = m.group(0)
        break
check(f"flag 10 = {EXPECTED_FLAG_10}", flag10_found == EXPECTED_FLAG_10)

print()
print("--- Flag 8: Vasik PDF attachment + text extraction ---")
flag8_found = None
for msg in inboxes.get("e.vasik", []):
    for part in msg.walk():
        fname = part.get_filename() or ""
        if fname.endswith(".pdf"):
            out = os.path.join(TMP, fname)
            with open(out, "wb") as f:
                f.write(part.get_payload(decode=True))
            text = pdf_to_text(out)
            m = re.search(r"FLAG\{[a-f0-9]+\}", text)
            if m:
                flag8_found = m.group(0)
                break
check(f"flag 8 = {EXPECTED_FLAG_8}", flag8_found == EXPECTED_FLAG_8)

print()
print("--- Roundcube webmail login flow (design: log in as d.kowalski) ---")
cj = CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
opener.addheaders = [("User-Agent", "Mozilla/5.0")]
try:
    r = opener.open(f"http://{HOST}/")
    html = r.read().decode("utf-8", errors="ignore")
    check("GET / returns Roundcube page", "Roundcube" in html)
    m_token = re.search(r'name="_token"\s+value="([^"]+)"', html)
    token = m_token.group(1) if m_token else ""
    data = urllib.parse.urlencode({
        "_token": token, "_task": "login", "_action": "login",
        "_timezone": "UTC", "_url": "",
        "_user": "d.kowalski", "_pass": "P@ssw0rd123",
    }).encode()
    req = urllib.request.Request(f"http://{HOST}/?_task=login&_action=login", data=data)
    req.add_header("Referer", f"http://{HOST}/")
    r = opener.open(req)
    final_url = r.url
    html2 = r.read().decode("utf-8", errors="ignore")
    check("Roundcube login redirects to _task=mail", "_task=mail" in final_url)
    check("Roundcube login response lacks 'invalid'", "invalid" not in html2.lower() and "incorrect" not in html2.lower())
except Exception as e:
    fail(f"Roundcube webmail login flow broke: {e}")

print()
print("--- Flag 15 A4 pivot creds in Kowalski 'creds backup' email ---")
creds_email_text = ""
for msg in inboxes.get("d.kowalski", []):
    if "creds backup" in (msg["Subject"] or "").lower():
        creds_email_text = message_text(msg)
        break
check("creds backup email present", bool(creds_email_text))
check("contains svc-fileshare username", "svc-fileshare" in creds_email_text)
check("contains F1l3Sh@r3Svc! password", "F1l3Sh@r3Svc!" in creds_email_text)
check("contains fileserv hostname", "fileserv" in creds_email_text)

print()
print("--- Narrative / cross-asset content ---")
vasik_text = " ".join(message_text(m) for m in inboxes.get("e.vasik", []))
check("Vasik: MIDNIGHT-7 simulation", "MIDNIGHT-7" in vasik_text)
check("Vasik: locomotion / bipedal", "locomotion" in vasik_text.lower() or "bipedal" in vasik_text.lower())
check("Vasik: reactor / power source", "reactor" in vasik_text.lower() or "power source" in vasik_text.lower())
check("Vasik: Kursk shipment email", "Kursk" in vasik_text)

chen_text = " ".join(message_text(m) for m in inboxes.get("j.chen", []))
chen_subjects = [m["Subject"] or "" for m in inboxes.get("j.chen", [])]
check("Chen: PO-2847 referenced", "PO-2847" in chen_text)
check("Chen: termination email present",
      any("termination" in s.lower() or "terminated" in s.lower() for s in chen_subjects))

mor_text = " ".join(message_text(m) for m in inboxes.get("s.morrison", []))
mor_subjects = [m["Subject"] or "" for m in inboxes.get("s.morrison", [])]
check("Morrison: Petrov mentioned", "Petrov" in mor_text)
check("Morrison: rotation schedule attachment", any("rotation" in s.lower() for s in mor_subjects))

harlan_subjects = [m["Subject"] or "" for m in inboxes.get("v.harlan", [])]
check("Harlan: locomotion milestone email thread",
      any("locomotion" in s.lower() for s in harlan_subjects))

webb_text = " ".join(message_text(m) for m in inboxes.get("m.webb", []))
check("Webb: Kursk procurement response", "Kursk" in webb_text)
check("Webb: Novikov reactor logistics", "Novikov" in webb_text or "reactor" in webb_text.lower())

print()
print("--- Kowalski SCADA VLAN 40 ticket breadcrumb ---")
kow_text = " ".join(message_text(m) for m in inboxes.get("d.kowalski", []))
check("SCADA VLAN 40 referenced", "VLAN 40" in kow_text)
check("scada-gw host referenced", "scada-gw" in kow_text)

print()
if fails == 0:
    print("A1 smoketest: PASS")
    sys.exit(0)
else:
    print(f"A1 smoketest: FAIL ({fails} failure(s))")
    sys.exit(1)
