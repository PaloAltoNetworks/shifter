---
id: CTF-108
title: "Challenge File Attachments"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:21.656090Z
updated_at: 2026-03-26T06:11:27.701474Z
---

# CTF-108: Challenge File Attachments

## Statement

The system should support attaching one or more files to a challenge for participants to download. Files shall be stored using the platform's shared storage abstraction (shared.cloud StorageProvider / shared.s3) and served via time-limited, authenticated presigned download URLs. The system shall enforce a maximum file size limit. Attachments shall be deletable without affecting the challenge itself. The CTF layer shall not implement its own storage backend.

## Rationale

Many CTF challenges require participants to analyze provided files, pcap captures, memory dumps, binaries, encrypted archives, or configuration files. CTFd supports file attachments per challenge. Without this, organizers must host files externally and link them in descriptions, which is fragile and creates access control gaps.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFChallenge model - no attachment/file fields)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/s3.py` (CTF S3 operations - upload, delete, presigned download URLs)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/attachment.py` (CTF attachment service - CRUD for challenge files)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_attachments.py` (CTF attachment tests - upload, validation, limits, soft-delete, S3 mocking, and confidential-error redaction)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#517` (CTF-108: Challenge File Attachments)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/api/files.py` (CTF views - file upload, delete, and download endpoints)
