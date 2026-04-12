#!/usr/bin/env python3
"""
A0 Boreas Systems PDF generator.

Generates the four PDFs served by A0:
  internal/org_chart.pdf            (flag 2 in PDF metadata: Author field)
  internal/boreas-Q1-2025.pdf
  internal/boreas-Q2-2025.pdf
  internal/boreas-annual-2025.pdf   (NOT linked in /internal/index.html; found by fuzzing filename pattern)

Output directory is argv[1]. Invoked from Dockerfile build stage.
"""

import os
import sys
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

FLAG_2 = "FLAG{d4e7b1f283a6c950}"


def make_org_chart(path):
    c = canvas.Canvas(path, pagesize=letter)
    c.setAuthor(FLAG_2)
    c.setTitle("Boreas Systems — Organizational Chart")
    c.setSubject("Corporate org chart (internal)")
    c.setKeywords("boreas, org, internal, hr")
    c.setCreator("Boreas Systems HR")

    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(4.25 * inch, 10 * inch, "BOREAS SYSTEMS")
    c.setFont("Helvetica", 12)
    c.drawCentredString(4.25 * inch, 9.7 * inch, "Organizational Chart — 2025")
    c.setFont("Helvetica-Oblique", 10)
    c.drawCentredString(4.25 * inch, 9.5 * inch, "Confidential — Internal Use Only")

    y = 8.9 * inch
    c.setFont("Helvetica-Bold", 14)
    c.drawString(0.75 * inch, y, "CEO: Viktor Harlan")

    y -= 0.35 * inch
    c.setFont("Helvetica-Bold", 12)
    c.drawString(1.0 * inch, y, "CTO: Dr. Elena Vasik")
    c.setFont("Helvetica", 10)
    for line in [
        "    - Engineering Lead: (vacant)",
        "    - Simulation: R. Tanaka",
        "    - Mechanical: P. Nielsen",
        "    - Sensors: K. Yamamoto",
        "    - AI/ML: F. Okoye",
        "    - Director, Underground Operations: (classified)",
    ]:
        y -= 0.22 * inch
        c.drawString(1.0 * inch, y, line)

    y -= 0.35 * inch
    c.setFont("Helvetica-Bold", 12)
    c.drawString(1.0 * inch, y, "COO: Marcus Webb")
    c.setFont("Helvetica", 10)
    for line in ["    - Procurement", "    - Logistics"]:
        y -= 0.22 * inch
        c.drawString(1.0 * inch, y, line)

    y -= 0.35 * inch
    c.setFont("Helvetica-Bold", 12)
    c.drawString(1.0 * inch, y, "IT: D. Kowalski")

    y -= 0.35 * inch
    c.setFont("Helvetica-Bold", 12)
    c.drawString(1.0 * inch, y, "Security: S. Morrison")
    c.setFont("Helvetica", 10)
    y -= 0.22 * inch
    c.drawString(1.0 * inch, y, "    - Guard team (10)")

    c.setFont("Helvetica-Oblique", 8)
    c.drawCentredString(4.25 * inch, 0.5 * inch,
                        "Distribution: Executive Leadership, HR, IT")
    c.save()


def make_quarterly(path, quarter, revenue_m, net_m, notes):
    c = canvas.Canvas(path, pagesize=letter)
    c.setTitle(f"Boreas Systems {quarter} 2025 Report")
    c.setAuthor("M. Webb, COO")
    c.setSubject(f"{quarter} 2025 financial summary")
    c.setCreator("Boreas Systems Finance")

    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(4.25 * inch, 10 * inch, "BOREAS SYSTEMS")
    c.setFont("Helvetica", 14)
    c.drawCentredString(4.25 * inch, 9.7 * inch, f"{quarter} 2025 Report")
    c.setFont("Helvetica-Oblique", 10)
    c.drawCentredString(4.25 * inch, 9.5 * inch, "Confidential — Internal Distribution Only")

    y = 8.7 * inch
    c.setFont("Helvetica-Bold", 14)
    c.drawString(0.75 * inch, y, "Financial Summary")
    y -= 0.3 * inch
    c.setFont("Helvetica", 11)
    c.drawString(0.75 * inch, y, f"Revenue:      ${revenue_m:.1f}M")
    y -= 0.22 * inch
    c.drawString(0.75 * inch, y, f"Net Income:   ${net_m:.1f}M")

    y -= 0.5 * inch
    c.setFont("Helvetica-Bold", 14)
    c.drawString(0.75 * inch, y, "Operational Notes")
    y -= 0.3 * inch
    c.setFont("Helvetica", 10)
    for line in notes:
        c.drawString(0.75 * inch, y, "- " + line)
        y -= 0.22 * inch

    c.setFont("Helvetica-Oblique", 8)
    c.drawCentredString(4.25 * inch, 0.5 * inch,
                        "Prepared by M. Webb, COO / Approved by V. Harlan, CEO")
    c.save()


def make_annual_report(path):
    """Annual report with Kursk Heavy Industries $12M line buried in 40 expense items.

    Flag 6 (CTFd challenge) requires submitting the supplier name and dollar amount
    in the format KURSK-12000000 after locating this PDF via filename fuzzing.
    """
    c = canvas.Canvas(path, pagesize=letter)
    c.setTitle("Boreas Systems — Annual Report 2025")
    c.setAuthor("M. Webb, COO")
    c.setSubject("Boreas Systems annual report — fiscal year 2025")
    c.setCreator("Boreas Systems Finance")

    c.setFont("Helvetica-Bold", 22)
    c.drawCentredString(4.25 * inch, 10.3 * inch, "BOREAS SYSTEMS")
    c.setFont("Helvetica", 14)
    c.drawCentredString(4.25 * inch, 10 * inch, "Annual Report — Fiscal Year 2025")
    c.setFont("Helvetica-Oblique", 10)
    c.drawCentredString(4.25 * inch, 9.8 * inch, "Confidential — Internal Distribution Only")

    y = 9.3 * inch
    c.setFont("Helvetica-Bold", 13)
    c.drawString(0.75 * inch, y, "Financial Summary")
    y -= 0.28 * inch
    c.setFont("Helvetica", 10)
    c.drawString(0.75 * inch, y, "Total Revenue:        $52,800,000")
    y -= 0.2 * inch
    c.drawString(0.75 * inch, y, "Operating Expenses:   $48,100,000")
    y -= 0.2 * inch
    c.drawString(0.75 * inch, y, "Net Income:           $ 4,700,000")

    y -= 0.4 * inch
    c.setFont("Helvetica-Bold", 13)
    c.drawString(0.75 * inch, y, "Expense Breakdown")
    y -= 0.1 * inch
    c.line(0.75 * inch, y, 7.75 * inch, y)
    y -= 0.2 * inch

    expenses = [
        ("Office lease & utilities", 2400000),
        ("Employee salaries - consulting", 8500000),
        ("Employee salaries - engineering", 6200000),
        ("Employee salaries - executive", 1800000),
        ("Employee salaries - support", 1200000),
        ("Health insurance & benefits", 3100000),
        ("IT infrastructure & licensing", 890000),
        ("Travel & client site visits", 420000),
        ("Professional development", 180000),
        ("Marketing & business development", 340000),
        ("Legal & compliance", 560000),
        ("Accounting & audit", 210000),
        ("Insurance (general liability)", 175000),
        ("Office supplies & equipment", 95000),
        ("Vehicle fleet maintenance", 68000),
        ("Security services", 440000),
        ("Telecommunications", 125000),
        ("Software subscriptions", 310000),
        ("Cloud computing services", 280000),
        ("Kursk Heavy Industries - actuator assemblies", 12000000),
        ("Deutsche Antrieb GmbH - precision motors", 5400000),
        ("SpecMetal Corp - specialty alloys", 850000),
        ("Lab equipment maintenance", 220000),
        ("Calibration services", 95000),
        ("Waste disposal & environmental", 45000),
        ("Facility maintenance", 380000),
        ("HVAC & climate control", 210000),
        ("Fire suppression systems", 125000),
        ("Badge & access control systems", 185000),
        ("Consultant subcontractors", 920000),
        ("Patent filing & IP protection", 340000),
        ("Regulatory compliance testing", 275000),
        ("Quality assurance program", 190000),
        ("Employee recruitment", 165000),
        ("Relocation assistance", 85000),
        ("Conference & event sponsorship", 120000),
        ("Charitable contributions", 50000),
        ("Depreciation - equipment", 680000),
        ("Depreciation - vehicles", 45000),
        ("Miscellaneous operating", 230000),
    ]

    c.setFont("Courier", 8)
    for desc, amount in expenses:
        if y < 0.9 * inch:
            c.showPage()
            c.setFont("Courier", 8)
            y = 10.5 * inch
        line = f"  {desc:50s}  ${amount:>12,}"
        c.drawString(0.75 * inch, y, line)
        y -= 0.18 * inch

    y -= 0.1 * inch
    c.line(0.75 * inch, y, 7.75 * inch, y)
    y -= 0.22 * inch
    total = sum(a for _, a in expenses)
    c.setFont("Courier-Bold", 9)
    c.drawString(0.75 * inch, y, f"  {'TOTAL':50s}  ${total:>12,}")

    y -= 0.5 * inch
    c.setFont("Helvetica", 9)
    c.drawString(0.75 * inch, y, "Report prepared by: M. Webb, COO")
    y -= 0.18 * inch
    c.drawString(0.75 * inch, y, "Approved by: V. Harlan, CEO")

    c.save()


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "./out"
    os.makedirs(f"{out}/internal", exist_ok=True)

    make_org_chart(f"{out}/internal/org_chart.pdf")
    make_quarterly(
        f"{out}/internal/boreas-Q1-2025.pdf", "Q1", 12.4, 1.8,
        [
            "Key projects on track across all active engagements.",
            "Engineering headcount increased by 3.",
            "New procurement cycle launched for specialty components.",
        ],
    )
    make_quarterly(
        f"{out}/internal/boreas-Q2-2025.pdf", "Q2", 14.2, 2.1,
        [
            "Strong consulting demand across defense sector.",
            "Major procurement cycle initiated with European suppliers.",
            "Two senior engineers hired into the Systems Integration group.",
        ],
    )
    make_annual_report(f"{out}/internal/boreas-annual-2025.pdf")

    for f in sorted(os.listdir(f"{out}/internal")):
        size = os.path.getsize(f"{out}/internal/{f}")
        print(f"  built {f} ({size} bytes)")


if __name__ == "__main__":
    main()
