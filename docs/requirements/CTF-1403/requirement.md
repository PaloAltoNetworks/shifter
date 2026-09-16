---
id: CTF-1403
title: "Internationalization"
status: DRAFT
type: NON_FUNCTIONAL
priority: COULD
wave: 2
created_at: 2026-03-18T05:28:24.411313Z
updated_at: 2026-03-26T06:35:14.180594Z
---

# CTF-1403: Internationalization

## Statement

The CTF module could support multi-language UI using Django's built-in i18n framework. Translatable strings shall be externalized using Django's gettext workflow. Participants could select their preferred language. The system shall support at minimum English and one additional language.

## Rationale

Multi-language support enables running events for participants across different regions and language backgrounds. Django's i18n framework provides the standard gettext-based translation workflow, locale middleware, and template tags needed, no custom translation infrastructure required.

## Traceability

- CONSTRAINS → CONFIG `shifter/shifter_platform/config/settings.py` (Django settings - USE_I18N enabled, LANGUAGE_CODE set)
- CONSTRAINS → CODE_FILE `shifter/shifter_platform/ctf/apps.py` (CTF app configuration - no i18n setup present)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#640` (CTF-1403: Internationalization)
