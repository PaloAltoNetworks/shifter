# Tasks: Cortex XDR Full Layout Restructure

**Input**: Design documents from `/specs/183-cortex-xdr-reskin/`
**Prerequisites**: plan-restructure.md, spec-restructure.md, research-restructure.md

**Tests**: Not requested - focusing on implementation tasks only.

**Organization**: Tasks grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story (US1, US2, US3, US4, US5)
- Include exact file paths in descriptions

---

## Phase 1: Setup

**Purpose**: Create new files and folder structure for restructure

- [x] T001 Create portal/static/css/xdr-sidebar.css for sidebar-specific styles
- [x] T002 Create portal/static/js/sidebar.js for expand/collapse logic
- [x] T003 [P] Create portal/static/icons/ directory for SVG icons
- [x] T004 [P] Create SVG icon: portal/static/icons/dashboard.svg
- [x] T005 [P] Create SVG icon: portal/static/icons/agents.svg
- [x] T006 [P] Create SVG icon: portal/static/icons/history.svg
- [x] T007 [P] Create SVG icon: portal/static/icons/settings.svg
- [x] T008 [P] Create SVG icon: portal/static/icons/help.svg
- [x] T009 [P] Create SVG icon: portal/static/icons/risks.svg
- [x] T010 [P] Create SVG icon: portal/static/icons/api-keys.svg

**Checkpoint**: Setup complete - all new files and icons created

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Update base layout structure and darken theme - MUST complete before user stories

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T011 Update --xdr-background from #1f1f1f to #000000 in portal/static/css/xdr-theme.css
- [x] T012 Update --xdr-surface values for proper contrast in portal/static/css/xdr-theme.css
- [x] T013 Verify text contrast meets WCAG AA (4.5:1) after color changes
- [x] T014 Create base icon sidebar HTML structure in portal/templates/mission_control/base.html
- [x] T015 Create base icon sidebar HTML structure in portal/templates/risk_register/base.html
- [x] T016 Link xdr-sidebar.css stylesheet in portal/templates/mission_control/base.html
- [x] T017 Link xdr-sidebar.css stylesheet in portal/templates/risk_register/base.html
- [x] T018 Link sidebar.js script in portal/templates/mission_control/base.html
- [x] T019 Link sidebar.js script in portal/templates/risk_register/base.html

**Checkpoint**: Foundation ready - base layout restructured, darker theme applied

---

## Phase 3: User Story 1 - Icon Sidebar Navigation (Priority: P1) 🎯 MVP

**Goal**: Narrow icon strip (56px) on far left with navigation icons

**Independent Test**: Navigate to any page and verify icon sidebar appears with working navigation

### Implementation for User Story 1

- [x] T020 [US1] Add .icon-sidebar container styles (56px width, fixed left) in portal/static/css/xdr-sidebar.css
- [x] T021 [US1] Add .icon-sidebar-item styles (icon container, 48px height) in portal/static/css/xdr-sidebar.css
- [x] T022 [US1] Add .icon-sidebar-item.active styles (blue accent highlight) in portal/static/css/xdr-sidebar.css
- [x] T023 [US1] Add .icon-sidebar-item:hover styles in portal/static/css/xdr-sidebar.css
- [x] T024 [US1] Add tooltip styles for icon hover in portal/static/css/xdr-sidebar.css
- [x] T025 [US1] Include SVG icons in icon sidebar in portal/templates/mission_control/base.html
- [x] T026 [US1] Include SVG icons in icon sidebar in portal/templates/risk_register/base.html
- [x] T027 [US1] Add data-tooltip attributes for tooltip text in portal/templates/mission_control/base.html
- [x] T028 [US1] Add data-tooltip attributes for tooltip text in portal/templates/risk_register/base.html
- [x] T029 [US1] Update .main content area margin-left to 56px in portal/static/css/xdr-sidebar.css
- [x] T030 [US1] Wire up active state detection based on current URL in portal/templates/mission_control/base.html
- [x] T031 [US1] Wire up active state detection based on current URL in portal/templates/risk_register/base.html

**Checkpoint**: Icon sidebar fully functional with navigation and active states

---

## Phase 4: User Story 2 - Secondary Navigation Panel (Priority: P2)

**Goal**: Expandable text panel (180px) slides out for sections with sub-navigation

**Independent Test**: Click Risk Register icon and verify secondary panel slides out with sub-links

### Implementation for User Story 2

- [x] T032 [US2] Add .secondary-panel container styles (180px, slide animation) in portal/static/css/xdr-sidebar.css
- [x] T033 [US2] Add .secondary-panel.open transform styles in portal/static/css/xdr-sidebar.css
- [x] T034 [US2] Add .secondary-panel-item styles (text links) in portal/static/css/xdr-sidebar.css
- [x] T035 [US2] Add .secondary-panel-item.active styles in portal/static/css/xdr-sidebar.css
- [x] T036 [US2] Add .secondary-panel-header styles (section title) in portal/static/css/xdr-sidebar.css
- [x] T037 [US2] Implement panel toggle function in portal/static/js/sidebar.js
- [x] T038 [US2] Implement outside click handler to close panel in portal/static/js/sidebar.js
- [x] T039 [US2] Add secondary panel HTML for Risk Register in portal/templates/risk_register/base.html
- [x] T040 [US2] Wire up icon click to expand secondary panel in portal/static/js/sidebar.js
- [x] T041 [US2] Update .main margin-left when panel open (56px + 180px) in portal/static/css/xdr-sidebar.css

**Checkpoint**: Secondary panel slides out and closes correctly

---

## Phase 5: User Story 4 - Improved Empty States (Priority: P3)

**Goal**: Graphical circular elements in empty states instead of text-only

**Independent Test**: View Dashboard with no agents and verify graphical empty state appears

### Implementation for User Story 4

- [x] T042 [US4] Add .empty-state-graphic CSS (circular shape) in portal/static/css/xdr-theme.css
- [x] T043 [US4] Add .empty-state-graphic inner arc/segment styles in portal/static/css/xdr-theme.css
- [x] T044 [US4] Update empty state in portal/templates/mission_control/dashboard.html with graphic (N/A - uses functional state card)
- [x] T045 [US4] Update empty state in portal/templates/mission_control/agents.html with graphic
- [x] T046 [US4] Update empty state in portal/templates/mission_control/history.html with graphic
- [x] T047 [US4] Update empty state in portal/templates/risk_register/risk_list.html with graphic
- [x] T048 [US4] Update empty state in portal/templates/risk_register/apikey_list.html with graphic

**Checkpoint**: All empty states display graphical elements

---

## Phase 6: User Story 5 - User Avatar in Sidebar (Priority: P3)

**Goal**: User initials circle at bottom of icon sidebar with dropdown

**Independent Test**: Log in and verify initials avatar appears with working dropdown

### Implementation for User Story 5

- [ ] T049 [US5] Create initials template filter in portal/templatetags/user_extras.py
- [ ] T050 [US5] Add .user-avatar styles (32-40px circle) in portal/static/css/xdr-sidebar.css
- [ ] T051 [US5] Add .user-dropdown styles in portal/static/css/xdr-sidebar.css
- [ ] T052 [US5] Add avatar HTML to icon sidebar in portal/templates/mission_control/base.html
- [ ] T053 [US5] Add avatar HTML to icon sidebar in portal/templates/risk_register/base.html
- [ ] T054 [US5] Implement avatar dropdown toggle in portal/static/js/sidebar.js
- [ ] T055 [US5] Add dropdown items (Settings, Logout) in portal/templates/mission_control/base.html
- [ ] T056 [US5] Add dropdown items (Settings, Logout) in portal/templates/risk_register/base.html

**Checkpoint**: User avatar with dropdown fully functional

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final testing, validation, and cleanup

- [ ] T057 Test all navigation flows in browser at 1366×768 resolution
- [ ] T058 Visual comparison with Cortex XDR reference screenshots
- [ ] T059 Test in Chrome, Firefox, Safari, Edge (latest versions)
- [ ] T060 Verify sidebar behavior on window resize
- [ ] T061 Remove any unused CSS from Phase 1 sidebar in portal/static/css/xdr-theme.css
- [ ] T062 Run quickstart-restructure.md validation checklist

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately (T001-T010)
- **Foundational (Phase 2)**: Depends on Setup - BLOCKS all user stories (T011-T019)
- **User Story 1 (Phase 3)**: Depends on Foundational (T020-T031)
- **User Story 2 (Phase 4)**: Depends on Foundational, can parallel with US1 (T032-T041)
- **User Story 4 (Phase 5)**: Depends on Foundational (T042-T048)
- **User Story 5 (Phase 6)**: Depends on Foundational and US1 (T049-T056)
- **Polish (Phase 7)**: Depends on all user stories (T057-T062)

### User Story Dependencies

- **User Story 1 (P1)**: Core icon sidebar - MVP, no dependencies on other stories
- **User Story 2 (P2)**: Secondary panel - independent, works with or without US1
- **User Story 4 (P3)**: Empty states - fully independent
- **User Story 5 (P3)**: User avatar - depends on US1 sidebar structure

### Within Each User Story

- CSS styles before HTML structure
- HTML structure before JavaScript behavior
- Base components before variants

### Parallel Opportunities

**Phase 1 (Setup)**:
```
Parallel: T004, T005, T006, T007, T008, T009, T010 (all SVG icons)
```

**Phase 3 (US1)**:
```
Parallel: T025/T026 (both base templates)
Parallel: T027/T028 (tooltips in both templates)
Parallel: T030/T031 (active state in both templates)
```

**Phase 4 (US2)**:
```
Parallel with Phase 3 (different functionality)
```

**Phase 5 (US4)**:
```
Parallel: T044, T045, T046, T047, T048 (different template files)
```

---

## Implementation Strategy

### MVP First (User Stories 1 + 3)

1. Complete Phase 1: Setup (icons and files)
2. Complete Phase 2: Foundational (darker theme + layout structure)
3. Complete Phase 3: User Story 1 (icon sidebar)
4. **STOP and VALIDATE**: Test icon navigation independently
5. Demo if ready - this is the most impactful visual change

### Incremental Delivery

1. Setup + Foundational → Base restructure ready
2. Add US1 (Icon Sidebar) → Demo (MVP!)
3. Add US2 (Secondary Panel) → Demo
4. Add US4 (Empty States) → Demo
5. Add US5 (User Avatar) → Demo
6. Each story adds polish without breaking previous work

---

## Summary

| Phase | Story | Tasks | Parallelizable |
|-------|-------|-------|----------------|
| 1 | Setup | T001-T010 (10) | 7 icon tasks |
| 2 | Foundational | T011-T019 (9) | Limited |
| 3 | US1 - Icon Sidebar | T020-T031 (12) | Template pairs |
| 4 | US2 - Secondary Panel | T032-T041 (10) | Can parallel with US1 |
| 5 | US4 - Empty States | T042-T048 (7) | All templates |
| 6 | US5 - User Avatar | T049-T056 (8) | Template pairs |
| 7 | Polish | T057-T062 (6) | Limited |
| **Total** | | **62 tasks** | |

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to user story for traceability
- Each user story should be independently testable
- Commit after each task or logical group
- Stop at any checkpoint to validate independently
- US3 (Darker Background) is included in Foundational phase as it affects all pages
