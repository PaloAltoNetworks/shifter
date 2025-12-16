take <!--
Sync Impact Report:
- Version change: 1.0.0 → 2.0.0 (Major scope change: Django portal → OpenWeb UI)
- Modified principles:
  - I. Visual Fidelity First → unchanged (applies to OpenWeb UI now)
  - II. Demo-Ready Polish → unchanged (applies to OpenWeb UI now)
  - III. CSS-First Implementation → III. Minimal Footprint Implementation (adapted for OWUI)
  - IV. Component Consistency → IV. Brand Concealment (new priority for demo focus)
  - V. No Feature Creep → V. Upgrade-Safe Customization (adapted for containerized app)
- Added sections:
  - OpenWeb UI Theming Approach (new technical guidance)
  - Customization Strategy (CSS injection vs fork decision)
  - Key UI Elements to Restyle
- Removed sections:
  - Django template file references
  - Python/Django implementation constraints
- Templates requiring updates:
  - ✅ `.specify/templates/plan-template.md` - Generic, no changes required
  - ✅ `.specify/templates/spec-template.md` - Generic, no changes required
  - ✅ `.specify/templates/tasks-template.md` - Generic, no changes required
- Follow-up TODOs: None
- Source: OpenWeb UI v0.6.41 (ghcr.io/open-webui/open-webui:v0.6.41)
-->

# OpenWeb UI Cortex XDR Reskin Constitution

This constitution governs the UI/UX reskinning of OpenWeb UI to match the Palo Alto Networks
Cortex XDR look and feel. The goal is to deliver a demo-ready chat interface that appears as
a native PANW product, concealing OpenWeb UI branding so technical sellers can focus on the
demo experience without distracting "what tool is this?" questions.

## Core Principles

### I. Visual Fidelity First

The chat interface MUST visually match Cortex XDR as closely as possible. Design decisions
default to "what does Cortex XDR do?" rather than inventing new patterns.

**Non-negotiables:**
- Color palette MUST use Cortex XDR's actual colors (see Design Reference below)
- Typography MUST match Cortex XDR font stack (Lato) and weights
- Component styling (buttons, inputs, cards, menus) MUST follow XDR patterns
- Dark theme is MANDATORY (Cortex XDR is dark-themed)
- Spacing and visual rhythm MUST approximate XDR proportions

**Rationale:** Demo credibility requires the chat interface to feel like a PANW product.
Deviation breaks immersion and undermines the professional impression needed for client demos.

### II. Demo-Ready Polish

Every visible element MUST meet production-quality standards. No placeholder styling,
jarring transitions, or "good enough for now" implementations.

**Non-negotiables:**
- All interactive elements MUST have proper hover/focus/active states matching XDR patterns
- Loading states MUST be graceful (use XDR-style spinners or skeletons)
- Empty states MUST be designed, not default OpenWeb UI text
- Error states MUST look intentional and professional
- Responsive behavior MUST work on typical demo devices (laptop screens 1366×768+)
- Chat bubbles, input areas, and sidebars MUST feel cohesive

**Rationale:** First impressions matter. A polished UI signals product maturity and
engineering competence to demo audiences.

### III. Minimal Footprint Implementation

Styling changes MUST be implemented with the smallest possible footprint to minimize
maintenance burden and preserve upgrade paths.

**Non-negotiables:**
- Prefer CSS injection via OpenWeb UI Admin Settings (Settings → Admin → Customization)
- Use CSS custom properties (variables) to override OpenWeb UI's theme tokens
- Avoid forking OpenWeb UI source code unless absolutely necessary
- If forking is required, document exact changes and create a clear merge strategy
- Custom assets (logos, icons) MUST be hosted externally or via environment config
- No modifications to OpenWeb UI's Python/JavaScript source unless essential

**Rationale:** OpenWeb UI is actively developed. A minimal footprint ensures we can
upgrade to new versions without massive rework. CSS-only changes survive upgrades better
than source modifications.

### IV. Brand Concealment

OpenWeb UI branding MUST be replaced or hidden. The interface MUST appear as a PANW product
called "Cortex AI" or similar approved naming.

**Non-negotiables:**
- OpenWeb UI logo MUST be replaced with PANW/Cortex branding
- "Open WebUI" text references MUST be hidden or replaced via CSS/config
- Default model names should reflect PANW naming if possible (via Admin settings)
- Page title MUST reflect PANW product naming
- Favicon MUST be PANW-branded
- Footer links to OpenWeb UI docs/GitHub MUST be hidden (not removed—just concealed)

**Rationale:** During demos, clients should focus on the AI capabilities and XDR integration,
not wonder about the underlying chat platform. Brand consistency reinforces the professional,
integrated product narrative.

### V. Upgrade-Safe Customization

All customizations MUST be documented and designed to survive OpenWeb UI version upgrades.

**Non-negotiables:**
- Document every customization in a central location (this repo)
- CSS overrides MUST use specific selectors, not fragile positional selectors
- Test customizations against OpenWeb UI release notes before upgrading
- Maintain a "customization manifest" listing all changes and their purpose
- Environment variables and Admin settings are preferred over file modifications
- If source modifications are unavoidable, track them in a dedicated branch or patch file

**Rationale:** We use OpenWeb UI because it's maintained upstream. Preserving our ability
to upgrade ensures we get security fixes, new features, and bug fixes without rework.

## Design Reference

**Source:** `assets/styles/login.css` - Extracted from Cortex XSIAM platform

### Cortex XDR Color System

The reskin MUST adopt these colors from the `.xdr-dark-theme` class:

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

**Additional semantic colors:**

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
<link href="https://fonts.googleapis.com/css2?family=Lato:wght@100;400;600;700&display=swap" rel="stylesheet">
```

| Element | Font | Weight | Size |
|---------|------|--------|------|
| Body | Lato | 400 | 14px base |
| Headers | Lato | 700 | 18-24px |
| Labels | Lato | 400 | 12px |
| Buttons | Lato | 600 | 12px |
| Links | Lato | 400 | 12px |
| Chat messages | Lato | 400 | 14px |

### Component Patterns

**Sidebar Navigation:**
- Fixed left sidebar, dark background (`--xdr-surface` or `--xdr-background`)
- Navigation items with icon + label
- Active item: background `--xdr-selected` + accent indicator
- Hover: background `--xdr-hover`

**Buttons (per Cortex pattern):**
- Primary: Background `--xdr-primary-new` (#fff), text `--xdr-on-primary-new` (#000)
- Primary hover: `--xdr-primary-bg--hover` (#f4f5f5)
- Border-radius: 20px (pill-shaped per Cortex)
- Font: 12px, weight 600
- Height: 28px, padding 0 18px

**Form Inputs:**
- Background: `--xdr-background` (`#1f1f1f`)
- Border: none, bottom border only: 1px solid `--xdr-border-medium`
- Focus: border-color `--xdr-on-background`
- Text color: `--xdr-on-background`

**Links:**
- Color: `--xdr-link` (`#128df3`)
- No underline by default
- Hover: underline

**Chat Bubbles:**
- User messages: `--xdr-surface-primary` (#333) background
- AI messages: `--xdr-surface` (#151515) background
- Border-radius: 8px (softer than buttons)
- Text: `--xdr-on-background` (#eaebeb)

## OpenWeb UI Theming Approach

### Primary Method: CSS Injection via Admin Settings

OpenWeb UI allows custom CSS injection through Admin Panel → Settings → Interface → Custom CSS.

**Advantages:**
- No source code modifications
- Survives container rebuilds
- Stored in database (persisted with PostgreSQL)
- Can be updated without redeployment

**Limitations:**
- Cannot change favicon or logo via CSS alone (requires environment variables)
- Some deeply nested components may resist CSS overrides
- JavaScript behavior cannot be modified

### Secondary Method: Environment Variables

OpenWeb UI supports branding via environment variables:

| Variable | Purpose |
|----------|---------|
| `WEBUI_NAME` | Application title (appears in browser tab, UI headers) |
| `CUSTOM_NAME` | Alternative product name |
| `ENABLE_SIGNUP` | Control signup visibility |

Set these in `agentchat/docker-compose.yml` under the `open-webui` service.

### Tertiary Method: Custom Build (If Necessary)

If CSS injection and environment variables are insufficient, a custom Docker image may be
required. This would involve:

1. Forking OpenWeb UI or creating a custom layer
2. Replacing static assets (logo, favicon)
3. Modifying Svelte components for deep UI changes
4. Maintaining a separate image tag (e.g., `ghcr.io/panw/cortex-chat:v0.6.41-panw`)

**Use only if:** CSS injection cannot achieve required visual fidelity or branding.

## Key UI Elements to Restyle

### Priority 1: Brand Identity (Must Hide OpenWebUI)

| Element | Current | Target | Method |
|---------|---------|--------|--------|
| Page title | "Open WebUI" | "Cortex AI" | `WEBUI_NAME` env var |
| Favicon | OpenWebUI icon | PANW icon | Custom build or env var |
| Header logo | OpenWebUI logo | Cortex logo | CSS `background-image` replacement |
| Footer text | OpenWebUI links | Hidden or PANW | CSS `display: none` |

### Priority 2: Color Theme (Cortex Dark)

| Element | Target Style |
|---------|--------------|
| Background | `--xdr-background` (#1f1f1f) |
| Sidebar | `--xdr-surface` (#151515) |
| Cards/panels | `--xdr-surface` with `--xdr-border` |
| Primary buttons | Pill-shaped, white bg, black text |
| Text | `--xdr-on-background` (#eaebeb) |
| Accents | `--xdr-primary` (#128df3) |

### Priority 3: Component Refinement

| Component | Cortex Pattern |
|-----------|----------------|
| Chat input | Bottom border only, XDR focus state |
| Message bubbles | XDR surface colors, consistent radius |
| Model selector | XDR dropdown styling |
| Settings panels | XDR card styling |
| Scrollbars | Thin, dark, XDR-themed |

## Implementation Constraints

### Reference Files (Read-Only)

**Cortex Style Reference:**
- `assets/styles/login.css` - Cortex XSIAM CSS variables and component styles
- `assets/styles/README.md` - Color palette documentation

### Files in Scope

**Docker Compose Configuration:**
- `agentchat/docker-compose.yml` - Environment variables for branding

**Custom CSS (to be created):**
- `agentchat/custom-theme/cortex-theme.css` - Main CSS override file
- Documentation in this repo for applying via Admin Settings

**Documentation:**
- `docs/src/agentchat/theming.md` - Instructions for applying theme (to be created)

### Files Out of Scope

- OpenWeb UI source code (unless CSS injection proves insufficient)
- OpenWeb UI Docker image internals
- MCP server code
- Bedrock Access Gateway code
- Django portal code (separate reskin effort)

### Browser Support

Target modern browsers only (Chrome, Firefox, Safari, Edge - latest versions).
No IE11 support required.

## Governance

### Amendment Procedure

1. Propose change with rationale
2. Verify change does not violate core principles
3. Update constitution version and `LAST_AMENDED_DATE`
4. Document change in Sync Impact Report header

### Versioning Policy

- **MAJOR**: Scope change (e.g., different target application) or principle redefinition
- **MINOR**: New sections, additional constraints, expanded guidance
- **PATCH**: Clarifications, typo fixes, formatting

### Compliance Review

Before any theme change is deployed:
1. Verify styling matches Cortex XDR design reference
2. Confirm OpenWeb UI branding is concealed
3. Check all interactive states are implemented
4. Test on 1366×768 minimum resolution
5. Verify theme survives container restart (if using Admin CSS injection)
6. Document any upgrade considerations for new OpenWeb UI versions

**Version**: 2.0.0 | **Ratified**: 2025-12-14 | **Last Amended**: 2025-12-15
