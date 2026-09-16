---
id: CTF-1104
title: "CTFd Format Compatibility"
status: DRAFT
type: INTERFACE
priority: COULD
wave: 2
created_at: 2026-03-18T05:28:24.069942Z
updated_at: 2026-03-19T03:06:33.613384Z
---

# CTF-1104: CTFd Format Compatibility

## Statement

The system could support importing and exporting challenges in CTFd-compatible format (CTFd JSON export schema). Compatibility shall cover: challenge metadata, flags, hints, and file references. Shifter-specific fields (range integration, scheduling) that have no CTFd equivalent shall be omitted from CTFd-format exports and ignored during imports.

## Rationale

CTFd is the de facto standard CTF platform. Many publicly available challenge packs are distributed in CTFd format. Compatibility enables Shifter to leverage the existing CTF community's challenge libraries without requiring authors to reformat their content specifically for Shifter.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/challenge.py` (Challenge service - would need CTFd import/export functions)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFChallenge model - would need file references field for CTFd compat)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/urls.py` (CTF URL config - would need import/export URL routes)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#632` (CTF-1104: CTFd Format Compatibility)
- DOCUMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/admin_people.py` (CTF views - would need import/export endpoints)
