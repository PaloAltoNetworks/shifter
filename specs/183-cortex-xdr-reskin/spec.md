# Feature Specification: Cortex XDR Portal Reskin

**Feature Branch**: `183-ui-redesign`
**Created**: 2025-12-14
**Status**: Draft
**Input**: Reskin the Django portal (landing page, Mission Control, and Risk Register) to match the Cortex XDR look and feel for polished demo presentations

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Mission Control Looks Like Cortex XDR (Priority: P1)

A Domain Consultant opens the Mission Control dashboard to demo Shifter to a customer. The interface immediately looks like a Palo Alto Networks product—same colors, fonts, and component styling as Cortex XDR. The customer sees a professional, polished interface that reinforces trust in the platform.

**Why this priority**: Mission Control is the primary authenticated experience. Demos start here. First impressions determine customer confidence.

**Independent Test**: Navigate to `/mission-control/` after login and visually compare to Cortex XDR. The color palette, typography, sidebar navigation, cards, and buttons must match the Cortex design language.

**Acceptance Scenarios**:

1. **Given** a user is logged into Mission Control, **When** they view the dashboard, **Then** the page uses the Cortex XDR dark theme colors (`#1f1f1f` background, `#128df3` accent, `#151515` surfaces)
2. **Given** a user is on any Mission Control page, **When** they interact with buttons, **Then** buttons are pill-shaped with white background and black text (matching Cortex primary button style)
3. **Given** a user is on any Mission Control page, **When** they view the sidebar navigation, **Then** it uses dark surface background with hover/selected states matching Cortex patterns
4. **Given** a user is on any Mission Control page, **When** they view any text, **Then** the font is Lato (not Roboto) matching Cortex typography

---

### User Story 2 - Risk Register Matches Cortex XDR (Priority: P2)

A Domain Consultant accesses the Risk Register during a demo to show security governance features. The Risk Register styling is consistent with Mission Control and matches Cortex XDR, providing a seamless experience across portal sections.

**Why this priority**: Risk Register is a secondary but visible feature. Inconsistent styling between portal sections breaks immersion and looks unfinished.

**Independent Test**: Navigate to `/risks/` and visually compare to Mission Control. Both should use identical styling for shared components (header, sidebar, cards, buttons, tables, forms).

**Acceptance Scenarios**:

1. **Given** a user navigates from Mission Control to Risk Register, **When** the page loads, **Then** the header, sidebar, and overall layout are visually identical in styling
2. **Given** a user views the risk list table, **When** they see severity badges (Critical, High, Medium, Low), **Then** the badges use Cortex-compatible styling that maintains visual hierarchy
3. **Given** a user opens the risk creation form, **When** they view form inputs, **Then** inputs use Cortex-style bottom-border inputs with proper focus states

---

### User Story 3 - Landing Page Sets Professional Tone (Priority: P3)

A prospective user or returning user visits the Shifter landing page. Instead of the current cyberpunk aesthetic, they see a professional, Cortex-aligned design that signals enterprise-grade quality.

**Why this priority**: Landing page is the first touchpoint but users spend minimal time here. Mission Control and Risk Register are where demos happen.

**Independent Test**: Navigate to the root URL (`/`) and verify the page uses Cortex XDR colors and typography while maintaining brand identity (Shifter logo/wordmark).

**Acceptance Scenarios**:

1. **Given** a user visits the landing page, **When** the page loads, **Then** the background uses Cortex dark theme (`#1f1f1f`) instead of pure black
2. **Given** a user views the landing page, **When** they see text content, **Then** it uses Lato font family matching Cortex typography
3. **Given** a user views the landing page, **When** they see accent colors, **Then** the primary accent is Cortex blue (`#128df3`) rather than neon green

---

### Edge Cases

- What happens when users resize browser below 1024px? Cortex has min-width 1024px; maintain responsive behavior for tablets but document minimum supported width.
- How do severity badges (Critical/High/Medium/Low) translate to Cortex styling? Maintain semantic color meaning while using Cortex-compatible color values.
- What happens to the Shifter logo and branding? Keep Shifter branding but integrate with Cortex color scheme.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Portal MUST use the Cortex XDR dark theme color palette as defined in `assets/styles/login.css`
- **FR-002**: Portal MUST use Lato font family (weights 100, 400, 700) as the primary typeface
- **FR-003**: All interactive elements (buttons, links, inputs) MUST have proper hover, focus, and active states per Cortex patterns
- **FR-004**: Sidebar navigation MUST use Cortex styling: dark background, left-border accent for active items, hover states
- **FR-005**: Cards MUST use `#151515` background with `#484848` borders
- **FR-006**: Primary buttons MUST be pill-shaped (20px border-radius) with white background and black text
- **FR-007**: Form inputs MUST use bottom-border-only styling with focus state changing border color
- **FR-008**: Tables MUST use horizontal-only borders with hover row highlighting
- **FR-009**: Header MUST maintain fixed positioning with Cortex surface colors
- **FR-010**: All styling MUST be implemented through CSS only; no Python/Django backend changes
- **FR-011**: Risk Register severity badges MUST maintain clear visual hierarchy while using Cortex-compatible styling
- **FR-012**: Portal MUST support minimum browser width of 1024px (matching Cortex)
- **FR-013**: Links MUST use Cortex blue (`#128df3`) with no underline by default, underline on hover

### Assumptions

- The Shifter logo and wordmark will be retained (not replaced with Cortex branding)
- Existing HTML structure will be preserved where possible; only CSS/styling changes
- No new pages, features, or JavaScript functionality will be added
- The Cortex styles in `assets/styles/login.css` represent the authoritative design reference
- Modern browsers only (Chrome, Firefox, Safari, Edge latest versions); no IE11 support

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A stakeholder viewing Mission Control cannot distinguish the styling from an actual Cortex XDR interface (qualitative visual review)
- **SC-002**: All pages (Landing, Mission Control, Risk Register) use consistent styling with zero visual discrepancies between sections
- **SC-003**: Page load time remains under 2 seconds on standard broadband connection
- **SC-004**: All interactive elements respond to user input within 100ms (hover, focus states)
- **SC-005**: Portal renders correctly on screens 1366×768 and larger (typical demo laptop resolution)
- **SC-006**: Zero styling-related console errors or warnings in browser developer tools
- **SC-007**: All text is legible with sufficient contrast (WCAG AA minimum 4.5:1 for normal text)
