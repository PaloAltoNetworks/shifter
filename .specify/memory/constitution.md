<!--
Sync Impact Report:
- Version change: N/A → 1.0.0 (Initial constitution)
- Modified principles: N/A (new document)
- Added sections:
  - Core Principles (5 principles)
  - Design Reference (Cortex XDR specifications from assets/styles/)
  - Implementation Constraints
  - Governance
- Removed sections: N/A
- Templates requiring updates:
  - ✅ `.specify/templates/plan-template.md` - No changes required (template is generic)
  - ✅ `.specify/templates/spec-template.md` - No changes required (template is generic)
  - ✅ `.specify/templates/tasks-template.md` - No changes required (template is generic)
- Follow-up TODOs: None
- Source: Colors extracted from assets/styles/login.css (Cortex XSIAM platform)
-->

# Portal Cortex XDR Reskin Constitution

This constitution governs the UI/UX reskinning of the Shifter Django portal (landing page
and Mission Control) to match the Palo Alto Networks Cortex XDR look and feel. The goal
is to deliver demo-ready polish that gives stakeholders confidence during customer demos.

## Core Principles

### I. Visual Fidelity First

The portal MUST visually match Cortex XDR as closely as possible. Design decisions default
to "what does Cortex XDR do?" rather than inventing new patterns.

**Non-negotiables:**
- Color palette MUST use Cortex XDR's actual colors (see Design Reference below)
- Layout structure MUST mirror Cortex XDR sidebar + content pattern
- Typography MUST match Cortex XDR font stack and weights
- Component styling (cards, buttons, inputs, tables) MUST follow XDR patterns
- Spacing and visual rhythm MUST approximate XDR proportions

**Rationale:** Demo credibility requires the portal to feel like a PANW product. Deviation
breaks immersion and undermines the professional impression we need to create.

### II. Demo-Ready Polish

Every visible element MUST meet production-quality standards. No placeholder styling,
broken layouts, or "good enough for now" implementations.

**Non-negotiables:**
- All interactive elements MUST have proper hover/focus/active states
- Loading states MUST be graceful (spinners, skeletons, transitions)
- Empty states MUST be designed, not just "No data"
- Error states MUST look intentional and professional
- Responsive behavior MUST work on typical demo devices (laptop screens 1366×768+)

**Rationale:** First impressions matter. A polished UI signals product maturity and
engineering competence to demo audiences.

### III. CSS-First Implementation

Styling changes MUST be implemented through CSS/template changes. No Python/Django
backend modifications unless strictly necessary for template rendering.

**Non-negotiables:**
- Use CSS custom properties (variables) for all colors, spacing, and typography
- Style changes MUST NOT require database migrations
- Style changes MUST NOT alter existing view logic or URL patterns
- Maintain clean separation between styling and business logic
- Preserve existing HTML structure where possible; restyle rather than rebuild

**Rationale:** A pure reskin minimizes risk. Keeping backend unchanged ensures the
demo portal remains stable and functional throughout the styling work.

### IV. Component Consistency

All UI components MUST follow a single design language. No mixing of styling approaches
or inconsistent visual treatments across pages.

**Non-negotiables:**
- Create and use a unified CSS component library (buttons, cards, forms, tables, badges)
- Document each component's variants (primary, secondary, danger, disabled states)
- Apply components consistently across all Mission Control pages
- Eliminate one-off styles; extract repeated patterns into reusable classes
- Navigation, headers, and footers MUST be identical across all authenticated pages

**Rationale:** Consistency is the hallmark of professional software. Inconsistent UI
immediately signals "work in progress" rather than "production ready."

### V. No Feature Creep

This reskin is cosmetic only. No new features, no new pages, no behavioral changes.

**Non-negotiables:**
- No new Django views, models, or URL patterns
- No new JavaScript functionality beyond styling enhancements (hover effects, transitions)
- No changes to authentication, authorization, or data flows
- No "while we're here" improvements to unrelated areas
- If a styling change suggests a UX improvement, document it for future consideration

**Rationale:** Scope discipline ensures delivery on schedule. Feature additions multiply
risk and delay the primary goal of demo readiness.

## Design Reference

**Source:** `assets/styles/login.css` - Extracted from Cortex XSIAM platform

### Cortex XDR Color System

The reskin MUST adopt these colors from the `.xdr-dark-theme` class, replacing the current
cyberpunk palette:

| Token | Hex | Usage |
|-------|-----|-------|
| `--xdr-primary` | `#128df3` | Primary accent (Cortex blue) |
| `--xdr-on-primary` | `#fff` | Text on primary accent |
| `--xdr-background` | `#1f1f1f` | Main page background (dark gray) |
| `--xdr-on-background` | `#eaebeb` | Primary text on background |
| `--xdr-on-background-secondary` | `#b8b8b8` | Secondary text |
| `--xdr-disabled-text` | `#707070` | Disabled/muted text |
| `--xdr-surface` | `#151515` | Cards, elevated surfaces (darker) |
| `--xdr-surface-secondary` | `#000` | Deepest surface level |
| `--xdr-surface-primary` | `#333` | Highlighted surface |
| `--xdr-hover` | `#333` | Hover state background |
| `--xdr-selected` | `#484848` | Selected state background |
| `--xdr-border` | `#484848` | Default borders |
| `--xdr-border-extra-soft` | `#333` | Subtle borders |
| `--xdr-border-medium` | `#575757` | Medium emphasis borders |
| `--xdr-border-strong` | `#707070` | Strong borders |
| `--xdr-link` | `#128df3` | Link color (same as primary) |
| `--xdr-placeholder` | `#929191` | Placeholder text |
| `--xdr-primary-new` | `#fff` | Button background (primary) |
| `--xdr-on-primary-new` | `#000` | Button text (primary) |
| `--xdr-primary-bg--hover` | `#f4f5f5` | Primary button hover |

**Additional semantic colors (extend as needed):**

| Token | Hex | Usage |
|-------|-----|-------|
| `--xdr-success` | `#0C6` | Success indicators (from gradient) |
| `--xdr-warning` | `#FFB300` | Warning indicators |
| `--xdr-error` | `#FF5252` | Error indicators |
| `--xdr-orange` | `#FA582D` | PANW brand orange (use sparingly) |

### Typography

**Font Family:** `Lato, "Assistant", sans-serif`

Load via Google Fonts:
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Lato:wght@100;400;700&display=swap" rel="stylesheet">
```

| Element | Font | Weight | Size |
|---------|------|--------|------|
| Body | Lato | 400 | calc(10px + 0.2vw) or 14px base |
| Headers | Lato | 700 | 18-24px |
| Labels | Lato | 400 | 12px |
| Buttons | Lato | 600 | 12px |
| Links | Lato | 400 | 12px |

### Component Patterns

**Sidebar Navigation:**
- Fixed left sidebar, dark background (`--xdr-surface` or `--xdr-background`)
- Navigation items with icon + label
- Active item: background `--xdr-selected` + accent indicator
- Hover: background `--xdr-hover`

**Cards:**
- Background: `--xdr-surface` (`#151515`)
- Border: 1px solid `--xdr-border` (`#484848`)
- Border-radius: 4px
- Padding: 16-24px
- Box shadow: `--xdr-surface-box-shadow-floating-object` for elevated cards

**Buttons (per Cortex pattern):**
- Primary: Background `--xdr-primary-new` (#fff), text `--xdr-on-primary-new` (#000)
- Primary hover: `--xdr-primary-bg--hover` (#f4f5f5)
- Border-radius: 20px (pill-shaped per Cortex)
- Font: 12px, weight 600
- Height: 28px, padding 0 18px

**Tables:**
- Header: darker background, standard labels
- Rows: consistent background `--xdr-surface`
- Hover: `--xdr-hover` overlay
- Borders: `--xdr-border` horizontal only

**Form Inputs:**
- Background: `--xdr-background` (`#1f1f1f`)
- Border: none, bottom border only: 1px solid `--xdr-border-medium`
- Focus: border-color `--xdr-on-background`
- Text color: `--xdr-on-background`

**Links:**
- Color: `--xdr-link` (`#128df3`)
- No underline by default
- Hover: underline

## Implementation Constraints

### Reference Files

**Cortex Style Reference (read-only, do not modify):**
- `assets/styles/login.css` - Cortex XSIAM CSS variables and component styles
- `assets/styles/README.md` - Color palette documentation

### Files in Scope

**Templates (Django):**
- `portal/templates/coming_soon.html` - Landing page
- `portal/templates/mission_control/base.html` - Main layout
- `portal/templates/mission_control/dashboard.html`
- `portal/templates/mission_control/agents.html`
- `portal/templates/mission_control/history.html`
- `portal/templates/mission_control/settings.html`
- `portal/templates/mission_control/help.html`

**Static Files:**
- `portal/static/css/` - All CSS files (new or modified)
- `portal/static/images/` - Brand assets if replacement needed
- `portal/static/js/` - Only if styling-related changes needed

### Files Out of Scope

- All Python files (`views.py`, `models.py`, `urls.py`, etc.)
- Test files
- Configuration files
- Documentation
- Any files outside `portal/` directory

### Browser Support

Target modern browsers only (Chrome, Firefox, Safari, Edge - latest versions).
No IE11 support required. Use modern CSS freely (Grid, Flexbox, custom properties).

## Governance

### Amendment Procedure

1. Propose change with rationale
2. Verify change does not violate core principles
3. Update constitution version and `LAST_AMENDED_DATE`
4. Document change in Sync Impact Report header

### Versioning Policy

- **MAJOR**: Changes to core principles or design reference that require restyling
- **MINOR**: New sections, additional constraints, expanded guidance
- **PATCH**: Clarifications, typo fixes, formatting

### Compliance Review

Before any PR is approved:
1. Verify styling matches Cortex XDR design reference
2. Confirm no out-of-scope files modified
3. Check all interactive states are implemented
4. Test on 1366×768 minimum resolution

**Version**: 1.0.0 | **Ratified**: 2025-12-14 | **Last Amended**: 2025-12-14
