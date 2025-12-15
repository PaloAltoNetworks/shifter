# Feature Specification: OpenWeb UI Cortex XDR Reskin

**Feature Branch**: `227-cortex-reskin`
**Created**: 2025-12-15
**Status**: Draft
**Input**: User description: "Reskin OpenWeb UI to match Cortex XDR look and feel for demo-ready PANW branding"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Brand Concealment (Priority: P1)

As a technical seller giving a client demo, I need OpenWeb UI to appear as a native Palo Alto
Networks product so that clients focus on the AI capabilities rather than asking "what chat tool
is this?" which derails the demo narrative.

**Why this priority**: This is the core requirement. Without brand concealment, the reskin fails
its primary purpose. A perfectly themed UI still fails if "Open WebUI" appears anywhere visible.

**Independent Test**: Can be fully tested by loading the chat interface and verifying no OpenWebUI
branding is visible on any page. Delivers immediate demo credibility.

**Acceptance Scenarios**:

1. **Given** a user loads the chat interface, **When** the page renders, **Then** the page title shows "Cortex AI" (or approved PANW product name), not "Open WebUI"
2. **Given** a user views the main chat interface, **When** looking at the header/logo area, **Then** a Cortex/PANW logo is displayed instead of OpenWebUI logo
3. **Given** a user views the footer or about sections, **When** scanning for branding, **Then** no "Open WebUI" text, GitHub links, or community references are visible
4. **Given** a user views the browser tab, **When** the page is loaded, **Then** the favicon shows PANW branding, not OpenWebUI icon

---

### User Story 2 - Cortex Dark Theme (Priority: P2)

As a technical seller, I need the chat interface to use Cortex XDR's dark color scheme so that
the tool visually matches other PANW products clients may have seen, reinforcing the integrated
product story.

**Why this priority**: Color is the most immediately noticeable visual element after branding.
Wrong colors make the product feel "off" even if the logo is correct.

**Independent Test**: Can be fully tested by comparing screenshots of the themed chat interface
against Cortex XDR reference screenshots. Delivers visual consistency with PANW product family.

**Acceptance Scenarios**:

1. **Given** a user loads the chat interface, **When** the page renders, **Then** the background color is dark (#1f1f1f or close variant)
2. **Given** a user views the sidebar, **When** looking at navigation elements, **Then** the sidebar uses Cortex surface colors (#151515 background, #484848 borders)
3. **Given** a user interacts with primary buttons, **When** hovering or clicking, **Then** buttons use Cortex pill-shaped styling (white background, black text, 20px radius)
4. **Given** a user views text throughout the interface, **When** reading content, **Then** primary text is light gray (#eaebeb) on dark background
5. **Given** a user sees accent elements (links, highlights), **When** viewing them, **Then** accents use Cortex blue (#128df3)

---

### User Story 3 - Typography Alignment (Priority: P3)

As a technical seller, I need the chat interface to use the same fonts as Cortex XDR so that
the text styling matches the professional feel of PANW products.

**Why this priority**: Typography is a subtle but important consistency marker. Wrong fonts
create a subconscious "something is off" feeling even if colors are correct.

**Independent Test**: Can be tested by inspecting font rendering in browser dev tools and
comparing against Cortex reference. Delivers typographic consistency.

**Acceptance Scenarios**:

1. **Given** a user views any text in the interface, **When** inspecting the font, **Then** the font family is Lato (with fallback to Assistant, sans-serif)
2. **Given** a user views body text, **When** checking font properties, **Then** the base font size is approximately 14px with weight 400
3. **Given** a user views headers, **When** checking font properties, **Then** headers use font weight 700
4. **Given** a user views buttons, **When** checking font properties, **Then** buttons use font size 12px with weight 600

---

### User Story 4 - Chat Component Styling (Priority: P4)

As a user chatting with the AI, I need chat bubbles, input areas, and message styling to match
Cortex XDR patterns so the conversation interface feels professional and native.

**Why this priority**: Chat-specific components are the most frequently viewed elements during
demos. They should feel polished after foundational theming is complete.

**Independent Test**: Can be tested by sending test messages and verifying visual styling of
the conversation view. Delivers a polished chat experience.

**Acceptance Scenarios**:

1. **Given** a user sends a message, **When** viewing the chat history, **Then** user messages have a distinct background color (#333) matching Cortex surface-primary
2. **Given** the AI responds, **When** viewing the chat history, **Then** AI messages have a darker background (#151515) matching Cortex surface
3. **Given** a user views the chat input area, **When** focusing on the input, **Then** the input shows Cortex-style bottom border focus state
4. **Given** a user hovers over interactive elements, **When** hovering, **Then** hover states use Cortex hover color (#333)

---

### User Story 5 - Demo Device Compatibility (Priority: P5)

As a technical seller using a laptop during demos, I need the themed interface to display
correctly on typical demo screen sizes so that the reskin looks professional regardless of venue.

**Why this priority**: Demos happen on various devices. The theme must not break on common
screen sizes or the professional impression is undermined.

**Independent Test**: Can be tested by resizing browser to common demo resolutions (1366×768,
1920×1080) and verifying layout integrity. Delivers reliable demo experience.

**Acceptance Scenarios**:

1. **Given** a user views the interface on a 1366×768 screen, **When** the page renders, **Then** all elements are visible without horizontal scrolling and no content is cut off
2. **Given** a user views the interface on a 1920×1080 screen, **When** the page renders, **Then** the layout uses space proportionally without excessive whitespace
3. **Given** a user resizes the browser window, **When** transitioning between sizes, **Then** the layout adapts gracefully without breaking

---

### Edge Cases

- What happens when the user's browser blocks external font loading (Google Fonts)?
  *Expected*: Falls back to Assistant or system sans-serif gracefully
- What happens when CSS injection via Admin settings is not persisted (container restart without DB)?
  *Expected*: Theme is lost; documentation must cover persistence requirements
- What happens when OpenWebUI is upgraded to a new version?
  *Expected*: CSS selectors may break; upgrade process must include theme verification step

## Requirements *(mandatory)*

### Functional Requirements

**Brand Concealment:**
- **FR-001**: Page title MUST display "Cortex AI" or approved PANW product name
- **FR-002**: Header logo MUST display Cortex/PANW branding instead of OpenWebUI logo
- **FR-003**: Footer text and OpenWebUI community links MUST be hidden from view
- **FR-004**: Browser favicon MUST show PANW branding
- **FR-005**: Any "powered by" or attribution text MUST be hidden during normal usage

**Color Theme:**
- **FR-006**: Page background MUST use Cortex background color (#1f1f1f)
- **FR-007**: Sidebar MUST use Cortex surface color (#151515) with appropriate borders
- **FR-008**: Primary buttons MUST use Cortex pill-shaped styling (white bg, black text, 20px radius)
- **FR-009**: Secondary/ghost buttons MUST use Cortex secondary patterns
- **FR-010**: Links and accents MUST use Cortex blue (#128df3)
- **FR-011**: Text colors MUST follow Cortex hierarchy (primary #eaebeb, secondary #b8b8b8)

**Typography:**
- **FR-012**: Font family MUST be Lato with fallback to Assistant, sans-serif
- **FR-013**: Lato font MUST be loaded from Google Fonts or bundled
- **FR-014**: Font weights MUST include 400 (regular), 600 (semi-bold), 700 (bold)

**Chat Components:**
- **FR-015**: User message bubbles MUST use distinct Cortex surface color (#333)
- **FR-016**: AI message bubbles MUST use Cortex surface color (#151515)
- **FR-017**: Chat input MUST use Cortex input styling (bottom border, focus state)
- **FR-018**: Interactive elements MUST show Cortex hover states (#333)

**Persistence:**
- **FR-019**: Theme customizations MUST persist across user sessions
- **FR-020**: Theme customizations MUST survive container restarts (when using PostgreSQL)

**Compatibility:**
- **FR-021**: Theme MUST display correctly on screens 1366×768 and larger
- **FR-022**: Theme MUST work in Chrome, Firefox, Safari, and Edge (latest versions)

### Key Entities

- **Theme Configuration**: The collection of CSS overrides and environment variables that define the Cortex appearance; stored via Admin settings (database) or environment variables
- **Brand Assets**: Logo images, favicon files, and related visual identity assets; hosted externally or bundled
- **Customization Manifest**: Documentation tracking all changes made to achieve the reskin; maintained in repository

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of OpenWebUI visible branding is concealed or replaced when a user loads the interface
- **SC-002**: Color scheme achieves 90%+ visual match to Cortex XDR reference screenshots (validated by side-by-side comparison)
- **SC-003**: Theme displays correctly on 1366×768 resolution without horizontal scrolling or content cutoff
- **SC-004**: Theme persists across browser sessions when user returns (no re-application needed)
- **SC-005**: Technical sellers can demonstrate the chat interface without clients asking "what tool is this?" (qualitative validation via demo feedback)
- **SC-006**: Theme can be applied or updated in under 30 minutes by a developer following documentation
- **SC-007**: Theme survives a container restart when using PostgreSQL persistence (verified by restart test)

## Assumptions

- OpenWebUI Admin Settings → Interface → Custom CSS feature is available and functional in v0.6.41
- OpenWebUI environment variables (WEBUI_NAME, etc.) support branding customization
- PostgreSQL database is used for OpenWebUI persistence (theme settings survive container restarts)
- PANW-branded assets (logo, favicon) will be provided or created separately
- The approved product name is "Cortex AI" (can be adjusted if different name is approved)
- External access to Google Fonts is available (or fonts can be bundled if not)
- Modern browsers only (no IE11 support required)
