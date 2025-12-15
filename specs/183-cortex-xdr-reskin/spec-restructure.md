# Feature Specification: Cortex XDR Full Layout Restructure

**Feature Branch**: `feature/183-cortex-ui`
**Created**: 2025-12-15
**Status**: Draft
**Input**: User description: "Full restructure to match Cortex XDR layout exactly - icon sidebar, two-panel navigation, darker theme"

## Overview

Phase 2 of the Cortex XDR portal reskin. Phase 1 applied colors, typography, and component styling. This phase restructures the layout to match Cortex XDR's navigation pattern: a narrow icon sidebar on the far left with an expandable text panel, darker backgrounds, and improved empty states.

## User Scenarios & Testing

### User Story 1 - Icon Sidebar Navigation (Priority: P1)

Users see a narrow icon strip on the far left edge of the screen (similar to Cortex XDR's main navigation). Clicking an icon either navigates directly or expands a secondary panel with text links.

**Why this priority**: The icon sidebar is the most visually distinctive element of Cortex XDR. Without it, the portal will never feel like Cortex.

**Independent Test**: Navigate to any authenticated page and verify the icon sidebar appears on the far left with recognizable icons for Dashboard, Agents, History, Settings, Help. Clicking icons navigates to corresponding sections.

**Acceptance Scenarios**:

1. **Given** a logged-in user on any Mission Control page, **When** the page loads, **Then** a narrow (~48-60px) icon sidebar appears fixed on the far left edge
2. **Given** the icon sidebar is visible, **When** user hovers over an icon, **Then** a tooltip shows the section name
3. **Given** the icon sidebar is visible, **When** user clicks a navigation icon, **Then** they navigate to that section
4. **Given** the icon sidebar, **When** the current section is active, **Then** that icon is visually highlighted (blue accent or background)

---

### User Story 2 - Secondary Navigation Panel (Priority: P2)

For sections with sub-navigation (like Risk Register with "All Risks", "New Risk", "API Keys"), clicking the main icon expands a secondary text panel showing the sub-items.

**Why this priority**: Cortex XDR uses this pattern for complex sections. Matching it provides consistency and professional polish.

**Independent Test**: Navigate to Risk Register and verify clicking the icon shows a secondary panel with text links for sub-sections.

**Acceptance Scenarios**:

1. **Given** the icon sidebar, **When** user clicks an icon for a section with sub-navigation, **Then** a secondary panel (~180-200px) slides out showing text links
2. **Given** the secondary panel is open, **When** user clicks a sub-item, **Then** they navigate to that page
3. **Given** the secondary panel is open, **When** user clicks elsewhere or a different icon, **Then** the panel collapses
4. **Given** the secondary panel, **When** viewing a page within that section, **Then** the current sub-item is highlighted

---

### User Story 3 - Darker Background Theme (Priority: P1)

The background color matches Cortex XDR's near-black theme (#000000 to #151515) rather than the current #1f1f1f, creating the authentic Cortex feel.

**Why this priority**: Background color is immediately noticeable. A darker background makes the UI feel more like Cortex XDR.

**Independent Test**: Load any portal page and verify background appears near-black, matching Cortex XDR screenshots.

**Acceptance Scenarios**:

1. **Given** any portal page, **When** the page loads, **Then** the main content area background is #000000 or #0a0a0a
2. **Given** the darker background, **When** viewing cards/panels, **Then** they use #151515 or similar for contrast
3. **Given** the darker background, **When** viewing text, **Then** text remains readable with proper contrast (WCAG AA)

---

### User Story 4 - Improved Empty States (Priority: P3)

Empty states (no agents, no risks, no history) display graphical icons/illustrations similar to Cortex XDR's "No data available" pattern with a circular graphic.

**Why this priority**: Empty states are frequently seen during demos. Professional graphics make the product feel polished.

**Independent Test**: View the Dashboard with no agents uploaded and verify an attractive empty state graphic appears instead of plain text.

**Acceptance Scenarios**:

1. **Given** Dashboard with no active range, **When** page loads, **Then** empty state shows a circular/graphical icon (not just text)
2. **Given** Agents page with no agents, **When** page loads, **Then** empty state includes a visual element and call-to-action
3. **Given** any empty state, **When** viewing it, **Then** the primary action button is clearly visible

---

### User Story 5 - User Avatar in Sidebar (Priority: P3)

The bottom of the icon sidebar shows a user avatar/initials circle (like Cortex XDR's "BE" circle in the reference screenshot).

**Why this priority**: Nice-to-have polish that matches Cortex XDR's user presence indicator.

**Independent Test**: Log in and verify user initials appear in a circle at the bottom of the icon sidebar.

**Acceptance Scenarios**:

1. **Given** a logged-in user, **When** viewing the icon sidebar, **Then** a circular avatar with user initials appears at the bottom
2. **Given** the user avatar, **When** user clicks it, **Then** a dropdown appears with "Settings" and "Logout" options

---

### Edge Cases

- What happens when sidebar is viewed on narrow screens (< 1024px)? Icon sidebar collapses or becomes a hamburger menu
- What happens with very long section names in secondary panel? Text truncates with ellipsis
- How does the layout behave when secondary panel is open and user resizes window? Panel remains functional

## Requirements

### Functional Requirements

- **FR-001**: Portal MUST display a fixed icon sidebar (48-60px width) on the far left of all authenticated pages
- **FR-002**: Icon sidebar MUST include icons for: Dashboard, Agents, History, Settings, Help (Mission Control) and Risks, API Keys (Risk Register)
- **FR-003**: Icon sidebar MUST highlight the currently active section with visual indicator (accent color or background)
- **FR-004**: Icon sidebar MUST show tooltips on hover revealing section names
- **FR-005**: Sections with sub-navigation MUST expand a secondary text panel (180-200px) when clicked
- **FR-006**: Secondary panel MUST collapse when clicking outside or selecting a different main section
- **FR-007**: Background color MUST be near-black (#000000 to #0a0a0a) for main content areas
- **FR-008**: Cards and panels MUST use #151515 or darker for proper contrast against background
- **FR-009**: All text MUST maintain WCAG AA contrast ratios (4.5:1 minimum)
- **FR-010**: Empty states MUST include graphical elements (icons/illustrations), not just text
- **FR-011**: User initials avatar MUST appear at bottom of icon sidebar
- **FR-012**: Avatar dropdown MUST provide access to Settings and Logout
- **FR-013**: Portal MUST maintain minimum supported width of 1024px

### Key Entities

- **Icon Sidebar**: Fixed-position navigation strip containing section icons, always visible
- **Secondary Panel**: Collapsible text navigation panel that slides out from icon sidebar
- **User Avatar**: Circular element displaying user initials with dropdown menu
- **Empty State Component**: Reusable component with graphic, message, and CTA button

## Success Criteria

### Measurable Outcomes

- **SC-001**: Users can navigate to any section using only the icon sidebar within 2 clicks
- **SC-002**: Side-by-side comparison with Cortex XDR shows matching navigation structure
- **SC-003**: All empty states display graphical elements (zero text-only empty states)
- **SC-004**: Background colors match Cortex XDR reference within 10% luminosity
- **SC-005**: Icon sidebar loads and renders within 100ms of page load
- **SC-006**: Demo audience cannot distinguish portal navigation pattern from Cortex XDR at a glance

## Assumptions

- SVG icons will be used for sidebar navigation (simple, scalable)
- Icons can be sourced from existing icon libraries (Heroicons, Lucide, or custom)
- Secondary panel animation uses CSS transitions (no JavaScript animation library required)
- User avatar uses first letters of email or name (e.g., "BE" for brad.edwards@example.com)
- Empty state graphics can be simple CSS/SVG shapes (circular loading-style graphics)

## Out of Scope

- Mobile responsive hamburger menu (current min-width 1024px remains)
- Animated page transitions between sections
- Customizable sidebar icon order
- Collapsible/hideable sidebar toggle
