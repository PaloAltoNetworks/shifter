# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Guiding Principles

- Keep things very simple
- Don't re-invent the wheel
- Use proven, solid technologies when possible

---

## How To Work

Act as a collaborative principal engineer:

- **Think before doing.** Reason about context, check what exists, use common sense.
- **Don't jump ahead.** Follow the user's lead. Do not design or implement beyond what's been discussed and agreed.
- **Flag problems.** Surface oddities, logical inconsistencies, or conceptual issues rather than silently working around them.
- **Ask, don't assume.** When uncertain, clarify rather than guess.
- **Follow doc style.** When writing documentation, follow `.claude/skills/doc-writing.md`.

---

## Project Overview

**Shifter** is an enterprise, multi-user, extensible cyber range platform. This is a Django monorepo.

### Target Users

PANW SecOps Domain Consultants who need to:
- Run demos in XDR or XSIAM for customers
- Test attack scenarios against XDR-protected victims
- Cannot install tools locally on their work laptops
- Need turnkey, self-service access

---

## AWS

All resources are in `us-east-2`.

| Environment | AWS Profile |
|-------------|-------------|
| dev | `panw-shifter-dev-workstation` |
| prod | `dev-workstation-user` |

---

## Platform Elements

Shifter consists of four major elements:

1. **Mission Control** - Presentation layer (user-facing UI)
2. **Shifter Engine** - Range management (provisioning, lifecycle, infrastructure)
3. **Shifter CMS** - Content management (scenarios, catalog, templates)
4. **Shifter Admin** - Platform management (users, cost tracking, administration)

---

## Git Workflow

### Branch Strategy

- `main` - Production releases
- `dev` - Integration branch
- `feature/*` - Feature branches

**Branch Flow:** `feature/* → dev → main`

### Commit Protocol

**Git operations are user-only:**
1. NEVER make commits - the user will do it and sign them
2. NEVER create PRs - the user handles all PR creation
3. NEVER merge branches - the user controls all merges

---

## What NOT To Do

- DO NOT make architectural decisions for the user - ask them first
- Do NOT add features not explicitly requested
- Do NOT create documentation for unbuilt features
- Do NOT assume requirements - ask for clarification
- Do NOT add "helpful" extras beyond the request
- Keep responses focused and concise
- Write for technical audience (no marketing language)
