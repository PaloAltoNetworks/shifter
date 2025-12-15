# Tasks: Cortex XDR Portal Reskin

**Input**: Design documents from `/specs/183-cortex-xdr-reskin/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, quickstart.md ✅

**Tests**: Not requested - validation is visual inspection per quickstart.md

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the unified CSS theme file with all Cortex XDR styles

- [x] T001 Create CSS directory structure at portal/static/css/
- [x] T002 Create xdr-theme.css with CSS custom properties (color variables) in portal/static/css/xdr-theme.css
- [x] T003 Add typography styles (Lato font, weights, sizes) to portal/static/css/xdr-theme.css
- [x] T004 Add button component styles (.btn, .btn-primary, .btn-secondary, .btn-danger) to portal/static/css/xdr-theme.css
- [x] T005 Add card component styles (.card, .card-title) to portal/static/css/xdr-theme.css
- [x] T006 Add form input styles (.form-input, .form-select, .form-textarea) to portal/static/css/xdr-theme.css
- [x] T007 Add table styles (.table) to portal/static/css/xdr-theme.css
- [x] T008 Add navigation styles (.sidebar, .nav-item) to portal/static/css/xdr-theme.css
- [x] T009 Add header styles (.header) to portal/static/css/xdr-theme.css
- [x] T010 Add status indicator styles (.status, .status-dot) to portal/static/css/xdr-theme.css
- [x] T011 Add badge styles (.badge, severity variants) to portal/static/css/xdr-theme.css
- [x] T012 Add utility classes (spacing, text, layout) to portal/static/css/xdr-theme.css
- [x] T013 Add responsive breakpoints and mobile styles to portal/static/css/xdr-theme.css
- [x] T014 Add min-width: 1024px rule to html/body in portal/static/css/xdr-theme.css

**Checkpoint**: CSS foundation complete - all component styles defined

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Update base templates to load the new theme - BLOCKS all user story work

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T015 Update portal/templates/mission_control/base.html to link xdr-theme.css stylesheet
- [x] T016 Update portal/templates/mission_control/base.html to load Lato font from Google Fonts
- [x] T017 Add xdr-dark-theme class to body element in portal/templates/mission_control/base.html
- [x] T018 Remove inline `<style>` block from portal/templates/mission_control/base.html (styles now in xdr-theme.css)

**Checkpoint**: Foundation ready - Mission Control base template uses new theme

---

## Phase 3: User Story 1 - Mission Control Looks Like Cortex XDR (Priority: P1) 🎯 MVP

**Goal**: Mission Control dashboard and all pages match Cortex XDR styling

**Independent Test**: Navigate to `/mission-control/` after login and visually compare to Cortex XDR. Verify colors, typography, buttons, cards, and navigation match.

### Implementation for User Story 1

- [x] T019 [US1] Update header component classes in portal/templates/mission_control/base.html
- [x] T020 [US1] Update sidebar navigation classes in portal/templates/mission_control/base.html
- [x] T021 [US1] Update button classes to use pill-shaped styling in portal/templates/mission_control/base.html
- [x] T022 [US1] Update card components in portal/templates/mission_control/dashboard.html
- [x] T023 [US1] Update form elements (select, inputs) in portal/templates/mission_control/dashboard.html
- [x] T024 [US1] Update status indicators in portal/templates/mission_control/dashboard.html
- [x] T025 [P] [US1] Update portal/templates/mission_control/agents.html to use new component classes
- [x] T026 [P] [US1] Update portal/templates/mission_control/history.html to use new component classes
- [x] T027 [P] [US1] Update portal/templates/mission_control/settings.html to use new component classes
- [x] T028 [P] [US1] Update portal/templates/mission_control/help.html to use new component classes
- [x] T029 [US1] Verify all interactive states (hover, focus, active) work in Mission Control pages
- [x] T030 [US1] Visual review: Compare Mission Control to Cortex XDR reference

**Checkpoint**: Mission Control is fully styled and matches Cortex XDR - MVP complete

---

## Phase 4: User Story 2 - Risk Register Matches Cortex XDR (Priority: P2)

**Goal**: Risk Register uses identical styling to Mission Control, looks seamless

**Independent Test**: Navigate to `/risks/` and verify styling is consistent with Mission Control. Check tables, forms, and severity badges.

### Implementation for User Story 2

- [x] T031 [US2] Update portal/templates/risk_register/base.html to link xdr-theme.css stylesheet
- [x] T032 [US2] Update portal/templates/risk_register/base.html to load Lato font from Google Fonts
- [x] T033 [US2] Add xdr-dark-theme class to body element in portal/templates/risk_register/base.html
- [x] T034 [US2] Remove inline `<style>` block from portal/templates/risk_register/base.html
- [x] T035 [US2] Update header and sidebar in portal/templates/risk_register/base.html to match Mission Control
- [x] T036 [US2] Update severity badge classes in portal/templates/risk_register/risk_list.html
- [x] T037 [US2] Update table styling in portal/templates/risk_register/risk_list.html
- [x] T038 [P] [US2] Update portal/templates/risk_register/risk_detail.html to use new component classes
- [x] T039 [P] [US2] Update form inputs in portal/templates/risk_register/risk_form.html to bottom-border style
- [x] T040 [P] [US2] Update portal/templates/risk_register/apikey_list.html to use new component classes
- [x] T041 [US2] Verify navigation between Mission Control and Risk Register is visually seamless
- [x] T042 [US2] Visual review: Compare Risk Register to Mission Control for consistency

**Checkpoint**: Risk Register matches Mission Control styling exactly

---

## Phase 5: User Story 3 - Landing Page Sets Professional Tone (Priority: P3)

**Goal**: Landing page uses Cortex colors and typography while keeping Shifter branding

**Independent Test**: Navigate to `/` and verify background is `#1f1f1f`, font is Lato, accent is Cortex blue `#128df3` (not neon green).

### Implementation for User Story 3

- [ ] T043 [US3] Update portal/templates/coming_soon.html to link xdr-theme.css stylesheet
- [ ] T044 [US3] Update portal/templates/coming_soon.html to load Lato font from Google Fonts
- [ ] T045 [US3] Replace background color from `#000000` to `#1f1f1f` in portal/templates/coming_soon.html
- [ ] T046 [US3] Replace neon green (`#39FF14`) accent with Cortex blue (`#128df3`) in portal/templates/coming_soon.html
- [ ] T047 [US3] Update text colors to use Cortex palette in portal/templates/coming_soon.html
- [ ] T048 [US3] Remove or update glitch effects to be more subtle/professional in portal/templates/coming_soon.html
- [ ] T049 [US3] Verify Shifter logo and wordmark remain visible and properly styled
- [ ] T050 [US3] Visual review: Confirm landing page looks professional and Cortex-aligned

**Checkpoint**: Landing page complete - all portal pages now use Cortex XDR styling

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation and cleanup

- [ ] T051 Run full visual review using quickstart.md checklist
- [ ] T052 Test all pages at 1366×768 resolution (minimum demo resolution)
- [ ] T053 Verify no console errors related to CSS or fonts in browser dev tools
- [ ] T054 Check text contrast meets WCAG AA requirements (4.5:1 minimum)
- [ ] T055 Test in Chrome, Firefox, Safari, Edge (latest versions)
- [ ] T056 Remove any remaining inline styles that duplicate xdr-theme.css
- [ ] T057 Final cleanup: Remove unused CSS classes from xdr-theme.css if any

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately (T001-T014)
- **Foundational (Phase 2)**: Depends on Setup - BLOCKS all user stories (T015-T018)
- **User Story 1 (Phase 3)**: Depends on Foundational (T019-T030)
- **User Story 2 (Phase 4)**: Depends on Setup only (T031-T042)
- **User Story 3 (Phase 5)**: Depends on Setup only (T043-T050)
- **Polish (Phase 6)**: Depends on all user stories being complete (T051-T057)

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational - No dependencies on other stories
- **User Story 2 (P2)**: Can start after Setup - Independent of US1 (has own base.html)
- **User Story 3 (P3)**: Can start after Setup - Independent of US1/US2 (standalone template)

### Within Each User Story

- Base template updates before page-specific templates
- Structural changes before visual polish
- Interactive states after basic styling

### Parallel Opportunities

**Phase 1 (Setup)**: T005-T012 are sequential (same file xdr-theme.css)

**Phase 3 (US1)**: T025-T028 can run in parallel (different page templates)

**Phase 4 (US2)**: T038-T040 can run in parallel (different page templates)

**Cross-Story**: US2 and US3 can run in parallel with US1 after Setup is complete

---

## Parallel Example: Phase 3 Page Templates

```bash
# Launch all Mission Control page template tasks together:
Task T025: "Update portal/templates/mission_control/agents.html"
Task T026: "Update portal/templates/mission_control/history.html"
Task T027: "Update portal/templates/mission_control/settings.html"
Task T028: "Update portal/templates/mission_control/help.html"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001-T014)
2. Complete Phase 2: Foundational (T015-T018)
3. Complete Phase 3: User Story 1 (T019-T030)
4. **STOP and VALIDATE**: Test Mission Control visually
5. Demo-ready for Mission Control

### Incremental Delivery

1. Complete Setup + Foundational → CSS theme ready
2. Add User Story 1 → Mission Control demo-ready
3. Add User Story 2 → Risk Register demo-ready
4. Add User Story 3 → Landing page demo-ready
5. Polish → Full portal demo-ready

---

## Notes

- [P] tasks = different files or different sections of same file, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story is independently testable via visual inspection
- All styling is CSS-only per constitution principle III
- Reference `assets/styles/login.css` for Cortex color values
- Reference `quickstart.md` for testing procedures
