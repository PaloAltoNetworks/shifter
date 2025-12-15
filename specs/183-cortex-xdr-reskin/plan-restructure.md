# Implementation Plan: Cortex XDR Full Layout Restructure

**Feature**: Cortex XDR Full Layout Restructure
**Spec**: [spec-restructure.md](./spec-restructure.md)
**Branch**: `feature/183-cortex-ui`
**Created**: 2025-12-15

## Technical Context

### Current State
- Phase 1 complete: Colors, typography, and component styling applied
- Current layout: Text-based sidebar (200px) + content area
- Background: `#1f1f1f` (needs to be darker)
- Empty states: Text-only

### Target State
- Icon sidebar (48-60px) on far left
- Secondary text panel (180-200px) slides out on demand
- Background: `#000000` to `#0a0a0a`
- Empty states: Graphical with circular icons
- User avatar at bottom of icon sidebar

### Dependencies
- Existing `xdr-theme.css` (Phase 1 foundation)
- SVG icons for navigation (Lucide, Heroicons, or inline SVG)
- No new Python/Django dependencies

## Constitution Check

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Visual Fidelity First | ✅ Pass | Matches Cortex XDR two-panel navigation |
| II. Demo-Ready Polish | ✅ Pass | All states (hover, active, empty) designed |
| III. CSS-First Implementation | ✅ Pass | CSS/HTML/minimal JS only, no backend changes |
| IV. Component Consistency | ✅ Pass | Unified icon sidebar component |
| V. No Feature Creep | ✅ Pass | Navigation restructure only, no new features |

### Files in Scope (from Constitution)
- `portal/templates/mission_control/base.html`
- `portal/templates/risk_register/base.html`
- `portal/static/css/xdr-theme.css`
- New: `portal/static/css/xdr-sidebar.css`
- New: `portal/static/js/sidebar.js` (minimal, expand/collapse only)

## Implementation Approach

### Phase 1: Foundation (Icon Sidebar)

**Goal**: Replace text sidebar with icon sidebar structure

1. Create icon sidebar HTML structure in base templates
2. Add SVG icons for navigation items
3. Style icon sidebar (48-60px, fixed left)
4. Implement active state highlighting
5. Add tooltip on hover

### Phase 2: Secondary Panel

**Goal**: Add expandable text panel for sections with sub-navigation

1. Create secondary panel HTML structure
2. Add slide-out animation (CSS transition)
3. Implement expand/collapse JavaScript (~30 lines)
4. Wire up click handlers for icon → panel expansion
5. Handle outside click to collapse

### Phase 3: Theme Refinement

**Goal**: Darken background and adjust contrast

1. Update CSS variables for darker background (#000)
2. Adjust card/surface colors for contrast (#151515)
3. Verify text contrast (WCAG AA)
4. Update any hardcoded colors

### Phase 4: Empty States

**Goal**: Add graphical elements to empty states

1. Create circular/graphical SVG component
2. Update Dashboard empty state
3. Update Agents empty state
4. Update History empty state
5. Update Risk Register empty state

### Phase 5: User Avatar

**Goal**: Add user initials avatar with dropdown

1. Create avatar component HTML
2. Style circular avatar (32-40px)
3. Extract user initials from email
4. Add dropdown with Settings/Logout
5. Position at bottom of icon sidebar

### Phase 6: Polish & Integration

**Goal**: Final testing and refinement

1. Test all navigation flows
2. Verify visual match with Cortex XDR
3. Test at 1366×768 minimum resolution
4. Browser testing (Chrome, Firefox, Safari, Edge)

## Project Structure

```
portal/
├── static/
│   ├── css/
│   │   ├── xdr-theme.css      # Existing - update variables
│   │   └── xdr-sidebar.css    # NEW - sidebar-specific styles
│   ├── js/
│   │   └── sidebar.js         # NEW - expand/collapse logic
│   └── icons/                  # NEW - SVG icons (or inline)
│       ├── dashboard.svg
│       ├── agents.svg
│       ├── history.svg
│       ├── settings.svg
│       ├── help.svg
│       ├── risks.svg
│       └── api-keys.svg
└── templates/
    ├── mission_control/
    │   └── base.html          # Update layout structure
    └── risk_register/
        └── base.html          # Update layout structure
```

## Icon Reference

| Section | Icon | Source |
|---------|------|--------|
| Dashboard | Grid/Home | Lucide `layout-dashboard` or `home` |
| Agents | Server/Box | Lucide `server` or `box` |
| History | Clock | Lucide `clock` |
| Settings | Gear | Lucide `settings` |
| Help | Question/Info | Lucide `help-circle` |
| Risks | Shield/Alert | Lucide `shield-alert` |
| API Keys | Key | Lucide `key` |

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Layout breaks on resize | Test at multiple breakpoints, use CSS Grid |
| Icon accessibility | Add proper aria-labels and tooltips |
| Panel animation jank | Use CSS transforms, not width changes |
| Color contrast issues | Verify with WCAG contrast checker |

## Estimated Effort

| Phase | Tasks | Complexity |
|-------|-------|------------|
| Phase 1: Icon Sidebar | 5 | Medium |
| Phase 2: Secondary Panel | 5 | Medium |
| Phase 3: Theme Refinement | 4 | Low |
| Phase 4: Empty States | 5 | Low |
| Phase 5: User Avatar | 5 | Medium |
| Phase 6: Polish | 4 | Low |
| **Total** | **28 tasks** | |
