---
id: UX-060
title: "Translatable strings externalized"
status: DRAFT
type: NON_FUNCTIONAL
priority: SHOULD
created_at: 2026-05-09T04:39:19.649478Z
updated_at: 2026-05-09T04:39:19.649478Z
---

# UX-060: Translatable strings externalized

## Statement

Every user-facing string in the platform shall be externalized into the i18n catalog using Django's gettext workflow. Hard-coded English in templates or template-rendered Python shall be rejected at review. This requirement supersedes CTF-1403, which is scoped only to the CTF module; the obligation applies platform-wide.

## Rationale

Externalizing strings is cheap when done as code is written and prohibitively expensive as a retrofit. Doing it from the start of the redesign avoids retrofit cost and makes any future translation work strictly additive. CTF-1403 already specifies this for CTF only, there's no reason the rest of the platform should be left out.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#787` (Adopt minimum Django i18n to clear 481 Web:InternationalizationCheck findings)
