# Tasks: Risk Register

**Input**: Design documents from `/specs/001-risk-register/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅

**Tests**: Not explicitly requested - test tasks omitted.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Django app**: `portal/risk_register/`
- **Templates**: `portal/templates/risk_register/`
- **Tests**: `portal/tests/risk_register/`
- **API**: `portal/risk_register/api/`

---

## Phase 1: Setup (Shared Infrastructure) ✅ COMPLETE

**Purpose**: Project initialization and Django app structure

- [x] T001 Add djangorestframework dependency in portal/pyproject.toml
- [x] T002 Create risk_register Django app structure in portal/risk_register/
- [x] T003 [P] Create portal/risk_register/__init__.py
- [x] T004 [P] Create portal/risk_register/apps.py with RiskRegisterConfig
- [x] T005 Add risk_register and rest_framework to INSTALLED_APPS in portal/config/settings.py
- [x] T006 Add REST_FRAMEWORK configuration to portal/config/settings.py
- [x] T007 [P] Create portal/risk_register/api/__init__.py
- [x] T008 [P] Create portal/tests/risk_register/__init__.py

---

## Phase 2: Foundational (Blocking Prerequisites) ✅ COMPLETE

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T009 Create Risk model with all fields in portal/risk_register/models.py
- [x] T010 Create AuditLog model in portal/risk_register/models.py
- [x] T011 Create APIKey model with create_key classmethod in portal/risk_register/models.py
- [x] T012 Run makemigrations for risk_register app
- [x] T013 Run migrate to create database tables
- [x] T014 Create API key authentication backend in portal/risk_register/api/authentication.py
- [x] T015 [P] Create permission classes in portal/risk_register/api/permissions.py
- [x] T016 Add risk-register URL routes to portal/config/urls.py
- [x] T017 [P] Create base URL routing in portal/risk_register/urls.py
- [x] T018 [P] Create API URL routing in portal/risk_register/api/urls.py
- [x] T019 Register models in Django admin in portal/risk_register/admin.py

**Checkpoint**: Foundation ready - user story implementation can now begin

---

## Phase 3: User Story 1 - View and Browse Risks (Priority: P1) 🎯 MVP ✅ COMPLETE

**Goal**: Enable viewing all risks with threat modeling data via UI and API

**Independent Test**: Create sample risks via Django admin, verify they appear in list view (UI) and GET /api/v1/risks/ (API)

### Implementation for User Story 1

- [x] T020 [US1] Create RiskSerializer in portal/risk_register/api/serializers.py
- [x] T021 [US1] Create RiskViewSet with list and retrieve actions in portal/risk_register/api/views.py
- [x] T022 [US1] Register RiskViewSet routes in portal/risk_register/api/urls.py
- [x] T023 [US1] Add filtering support (status, severity) to RiskViewSet in portal/risk_register/api/views.py
- [x] T024 [US1] Add pagination configuration to RiskViewSet in portal/risk_register/api/views.py
- [x] T025 [US1] Create base template portal/templates/risk_register/base.html extending portal base
- [x] T026 [US1] Create risk list view in portal/risk_register/views.py
- [x] T027 [US1] Create risk list template portal/templates/risk_register/risk_list.html
- [x] T028 [US1] Create risk detail view in portal/risk_register/views.py
- [x] T029 [US1] Create risk detail template portal/templates/risk_register/risk_detail.html
- [x] T030 [US1] Add UI URL routes for list and detail in portal/risk_register/urls.py

**Checkpoint**: User Story 1 complete - risks viewable via UI and API

---

## Phase 4: User Story 2 - Create and Update Risks (Priority: P2) ✅ COMPLETE

**Goal**: Enable creating and updating risks with full audit trail

**Independent Test**: Create risk via POST /api/v1/risks/, update via PATCH, verify audit log entries exist

### Implementation for User Story 2

- [x] T031 [US2] Add create action to RiskViewSet in portal/risk_register/api/views.py
- [x] T032 [US2] Add update (partial_update) action to RiskViewSet in portal/risk_register/api/views.py
- [x] T033 [US2] Create audit logging helper function in portal/risk_register/models.py
- [x] T034 [US2] Integrate audit logging into RiskViewSet create/update in portal/risk_register/api/views.py
- [x] T035 [US2] Add actor identification (user vs apikey) to audit log entries in portal/risk_register/api/views.py
- [x] T036 [US2] Create risk create/edit form view in portal/risk_register/views.py
- [x] T037 [US2] Create risk form template portal/templates/risk_register/risk_form.html
- [x] T038 [US2] Add form validation for STRIDE categories, likelihood/impact scores in portal/risk_register/views.py
- [x] T039 [US2] Add UI URL routes for create and edit in portal/risk_register/urls.py

**Checkpoint**: User Story 2 complete - risks can be created and updated with audit trail

---

## Phase 5: User Story 3 - Comment on Risks (Priority: P3) ✅ COMPLETE

**Goal**: Enable adding immutable comments to risks

**Independent Test**: Add comment via POST /api/v1/risks/{id}/comments/, verify it appears on risk detail

### Implementation for User Story 3

- [x] T040 [US3] Create Comment model in portal/risk_register/models.py
- [x] T041 [US3] Create migration for Comment model
- [x] T042 [US3] Create CommentSerializer in portal/risk_register/api/serializers.py
- [x] T043 [US3] Create CommentViewSet (list, create, destroy) in portal/risk_register/api/views.py
- [x] T044 [US3] Add nested comment routes under risks in portal/risk_register/api/urls.py
- [x] T045 [US3] Add author identification (user/apikey) to comment creation in portal/risk_register/api/views.py
- [x] T046 [US3] Add comments section to risk detail template portal/templates/risk_register/risk_detail.html
- [x] T047 [US3] Add comment form to risk detail view in portal/risk_register/views.py
- [x] T048 [US3] Add comment_count computed property to RiskSerializer in portal/risk_register/api/serializers.py

**Checkpoint**: User Story 3 complete - comments can be added and viewed on risks

---

## Phase 6: User Story 4 - Close and Delete Risks (Priority: P4) ✅ COMPLETE

**Goal**: Enable closing, soft-deleting, and restoring risks

**Independent Test**: Close risk via PATCH (status=closed), delete via DELETE, restore via POST /restore/

### Implementation for User Story 4

- [x] T049 [US4] Add destroy (soft-delete) action to RiskViewSet in portal/risk_register/api/views.py
- [x] T050 [US4] Add restore action endpoint to RiskViewSet in portal/risk_register/api/views.py
- [x] T051 [US4] Add include_deleted query param support to RiskViewSet list in portal/risk_register/api/views.py
- [x] T052 [US4] Add audit logging for delete/restore/close/reopen actions in portal/risk_register/api/views.py
- [x] T053 [US4] Add close/reopen buttons to risk detail UI in portal/templates/risk_register/risk_detail.html
- [x] T054 [US4] Add delete button with confirmation to risk detail UI in portal/templates/risk_register/risk_detail.html
- [x] T055 [US4] Add close/delete/restore handlers to views in portal/risk_register/views.py
- [x] T056 [US4] Add view deleted risks toggle to list UI in portal/templates/risk_register/risk_list.html

**Checkpoint**: User Story 4 complete - full risk lifecycle management available

---

## Phase 7: User Story 5 - API Key Management (Priority: P5) ✅ COMPLETE

**Goal**: Enable creating and managing API keys for AI agent access

**Independent Test**: Create API key via admin, use it in X-API-Key header to call API, revoke and verify rejection

### Implementation for User Story 5

- [x] T057 [US5] Create APIKeySerializer in portal/risk_register/api/serializers.py
- [x] T058 [US5] Create APIKeyViewSet (list, create, retrieve) in portal/risk_register/api/views.py
- [x] T059 [US5] Add revoke action endpoint to APIKeyViewSet in portal/risk_register/api/views.py
- [x] T060 [US5] Add API key routes in portal/risk_register/api/urls.py
- [x] T061 [US5] Add admin-only permission check to APIKeyViewSet in portal/risk_register/api/views.py
- [x] T062 [US5] Create API key list view in portal/risk_register/views.py
- [x] T063 [US5] Create API key list template portal/templates/risk_register/apikey_list.html
- [x] T064 [US5] Add create key form with one-time key display in portal/risk_register/views.py
- [x] T065 [US5] Add revoke button to API key list UI in portal/templates/risk_register/apikey_list.html
- [x] T066 [US5] Update last_used_at on successful API key authentication in portal/risk_register/api/authentication.py

**Checkpoint**: User Story 5 complete - AI agents can authenticate via API keys

---

## Phase 8: Polish & Cross-Cutting Concerns ✅ COMPLETE

**Purpose**: Improvements that affect multiple user stories

- [x] T067 [P] Add navigation links to risk register in portal base template
- [x] T068 [P] Add breadcrumb navigation to all risk_register templates
- [x] T069 Add structured JSON error responses for all API validation errors in portal/risk_register/api/views.py
- [x] T070 [P] Add risk register section to Django admin with filters and search in portal/risk_register/admin.py
- [x] T071 Run quickstart.md validation - verify all operations work as documented
- [x] T072 [P] Add indexes to models per data-model.md recommendations in portal/risk_register/models.py

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3-7)**: All depend on Foundational phase completion
  - US1 → US2 → US3 → US4 → US5 (recommended sequential order)
  - US3, US4, US5 can start after US2 if parallelizing
- **Polish (Phase 8)**: Depends on all user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational - READ only, no dependencies
- **User Story 2 (P2)**: Depends on US1 (extends RiskViewSet with create/update)
- **User Story 3 (P3)**: Depends on US1 (builds on risk detail), can parallel with US4/US5
- **User Story 4 (P4)**: Depends on US2 (audit logging patterns), can parallel with US3/US5
- **User Story 5 (P5)**: Depends on Phase 2 only - independent of other stories

### Within Each User Story

- API implementation before UI (API-first per constitution)
- Serializers before ViewSets
- ViewSets before URL routing
- Backend before templates
- Core features before polish

### Parallel Opportunities

**Phase 1 (Setup)**:
```
T003, T004, T007, T008 can run in parallel
```

**Phase 2 (Foundational)**:
```
T014, T015 can run in parallel (after T009-T011)
T017, T018 can run in parallel
```

**Across User Stories** (after Phase 2):
```
US1 must complete first
Then US2, US3, US4, US5 can run in parallel teams
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001-T008)
2. Complete Phase 2: Foundational (T009-T019)
3. Complete Phase 3: User Story 1 (T020-T030)
4. **STOP and VALIDATE**: Test risk list/detail via UI and API
5. Deploy/demo as read-only risk dashboard

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. Add User Story 1 → Test → Deploy (Read-only MVP!)
3. Add User Story 2 → Test → Deploy (CRUD capability)
4. Add User Story 3 → Test → Deploy (Comments)
5. Add User Story 4 → Test → Deploy (Lifecycle)
6. Add User Story 5 → Test → Deploy (AI agent auth)

### Single Developer Strategy

1. Complete Setup + Foundational together
2. Follow US priority order: US1 → US2 → US3 → US4 → US5
3. Each story is a complete, deployable increment
4. Polish at the end

---

## Summary

| Phase | Story | Tasks | Completed |
|-------|-------|-------|-----------|
| Phase 1 | Setup | T001-T008 (8) | 8/8 ✅ |
| Phase 2 | Foundational | T009-T019 (11) | 11/11 ✅ |
| Phase 3 | US1 - View Risks | T020-T030 (11) | 11/11 ✅ |
| Phase 4 | US2 - Create/Update | T031-T039 (9) | 9/9 ✅ |
| Phase 5 | US3 - Comments | T040-T048 (9) | 9/9 ✅ |
| Phase 6 | US4 - Close/Delete | T049-T056 (8) | 8/8 ✅ |
| Phase 7 | US5 - API Keys | T057-T066 (10) | 10/10 ✅ |
| Phase 8 | Polish | T067-T072 (6) | 6/6 ✅ |
| **Total** | | **72 tasks** | **72/72 ✅** |

**All tasks complete!** Implementation validated on 2025-12-14.

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- API implementation before UI (constitution principle I)
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
