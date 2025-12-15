# Implementation Plan: Cortex XDR Portal Reskin

**Branch**: `feature/183-cortex-ui` | **Date**: 2025-12-14 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/183-cortex-xdr-reskin/spec.md`

## Summary

Reskin the Shifter Django portal (landing page, Mission Control, and Risk Register) to match
the Cortex XDR look and feel. This is a pure CSS/template refactor with no backend changes.
The goal is demo-ready polish that makes the portal indistinguishable from a PANW product.

## Technical Context

**Language/Version**: HTML/CSS (Django templates)
**Primary Dependencies**: Google Fonts (Lato), CSS custom properties
**Storage**: N/A (no data changes)
**Testing**: Visual inspection, browser dev tools
**Target Platform**: Modern browsers (Chrome, Firefox, Safari, Edge)
**Project Type**: Web application (Django portal)
**Performance Goals**: Page load <2s, interaction response <100ms
**Constraints**: CSS-only changes, no Python/Django backend modifications
**Scale/Scope**: 12 template files, 1 shared CSS file

## Constitution Check

*GATE: Must pass before implementation. All gates ✅ PASSED.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Visual Fidelity First | ✅ | Colors, typography, components defined in constitution |
| II. Demo-Ready Polish | ✅ | All interactive states required per spec FR-003 |
| III. CSS-First Implementation | ✅ | No backend changes per spec FR-010 |
| IV. Component Consistency | ✅ | Unified CSS library approach planned |
| V. No Feature Creep | ✅ | Pure reskin, no new features |

## Project Structure

### Documentation (this feature)

```text
specs/183-cortex-xdr-reskin/
├── spec.md              # Feature specification
├── plan.md              # This file
├── research.md          # CSS architecture decisions
├── quickstart.md        # How to run and test
└── checklists/
    └── requirements.md  # Validation checklist
```

### Source Code (files to modify)

```text
portal/
├── templates/
│   ├── coming_soon.html              # P3: Landing page
│   ├── mission_control/
│   │   ├── base.html                 # P1: Shared layout (header, sidebar, footer)
│   │   ├── dashboard.html            # P1: Dashboard page
│   │   ├── agents.html               # P1: Agents page
│   │   ├── history.html              # P1: History page
│   │   ├── settings.html             # P1: Settings page
│   │   └── help.html                 # P1: Help page
│   └── risk_register/
│       ├── base.html                 # P2: Risk Register layout
│       ├── risk_list.html            # P2: Risk list table
│       ├── risk_detail.html          # P2: Risk detail view
│       ├── risk_form.html            # P2: Risk create/edit form
│       └── apikey_list.html          # P2: API keys page
└── static/
    └── css/
        └── xdr-theme.css             # NEW: Unified Cortex XDR theme
```

**Structure Decision**: All CSS consolidated into a single `xdr-theme.css` file that replaces
inline styles in template `<style>` blocks. Templates will link to this shared stylesheet.

## Implementation Approach

### Phase 1: CSS Foundation

1. Create `portal/static/css/xdr-theme.css` with all Cortex XDR CSS variables
2. Define component classes: buttons, cards, forms, tables, badges, navigation
3. Include responsive breakpoints and state classes (hover, focus, active, disabled)

### Phase 2: Mission Control Templates (P1)

1. Update `base.html` to link `xdr-theme.css` and load Lato font
2. Replace inline `<style>` blocks with class references
3. Update each page template to use new component classes
4. Test all interactive states

### Phase 3: Risk Register Templates (P2)

1. Update `risk_register/base.html` to use shared theme
2. Style severity badges with Cortex-compatible colors
3. Update form inputs to bottom-border style
4. Ensure table styling matches Mission Control

### Phase 4: Landing Page (P3)

1. Update `coming_soon.html` with Cortex colors/typography
2. Replace neon green accents with Cortex blue
3. Maintain Shifter branding (logo/wordmark)

## Complexity Tracking

No constitution violations. Implementation follows all principles.

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Inline styles override new CSS | Medium | Low | Use specific selectors or !important sparingly |
| Template structure changes needed | Low | Medium | Prefer adding classes over restructuring HTML |
| Browser inconsistencies | Low | Low | Modern browsers only, test in Chrome/Firefox |
