---
id: CTF-405
title: "Brackets"
status: ACTIVE
type: FUNCTIONAL
priority: COULD
wave: 2
created_at: 2026-03-18T05:28:22.430300Z
updated_at: 2026-04-02T17:20:30.521780Z
---

# CTF-405: Brackets

## Statement

The system could support grouping participants into named brackets (for example beginner, intermediate, advanced) with separate scoreboards per bracket. Bracket assignment shall be configurable per participant by organizers. Participants shall see both their bracket scoreboard and the overall scoreboard.

## Rationale

Brackets enable fair competition when participants have vastly different skill levels, a beginner competing against experts has no chance of placing, which is demotivating. For Shifter, brackets allow mixed-experience events where junior and senior consultants compete within their tier. (CTFd supports a similar brackets feature.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTF Models - no bracket model or participant bracket field exists)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/bracket.py` (Bracket CRUD and participant assignment service)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/scoring.py` (Bracket-filtered scoreboards (bracket_id param))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/urls.py` (Bracket admin and API URL routes)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/forms.py` (CTFBracketForm and bracket field on CTFParticipantForm)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/admin.py` (CTFBracketAdmin and bracket on CTFParticipantAdmin)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/__init__.py` (Bracket service exports)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/migrations/0020_add_brackets.py` (Migration for CTFBracket model and participant bracket FK)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_brackets.py` (Bracket model, service, scoring, and view tests)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/participant/scoreboard.html` (Participant scoreboard with bracket tabs)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/admin/scoreboard.html` (Admin scoreboard with bracket tabs)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/admin/bracket_list.html` (Admin bracket list template)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/admin/bracket_form.html` (Admin bracket create/edit form template)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/admin_brackets.py` (Bracket management views, scoreboard bracket tabs, bracket API)
