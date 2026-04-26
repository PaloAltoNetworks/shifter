# CTF Extraction Checklists

Basis:
- Source branch: `claude/ctf-management-platform-2Gknm`
- Target base: `origin/dev`
- Review date: `2026-03-11`

Recommended deployment path:
- Extract the CTF capability onto `origin/dev`.
- Do not deploy the docker/runtime migration on the same timeline.

Use these files in order:
1. `01-port-checklist.md`
2. `02-fixes-before-deploy.md`
3. `03-validation-and-cutover.md`

Current state notes:
- The committed branch tip is not a complete CTF launch branch by itself.
- The local uncommitted phase 7 work closes some gaps, but it also introduces deploy blockers that need edits before use.
- `origin/dev` already has `management/migrations/0002_add_threat_research_group.py`, so the branch's management `0002` migration cannot be taken as-is.
