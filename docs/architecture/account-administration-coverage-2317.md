# Account administration operation inventory (#2317)

This inventory completes the S4 preparation described in ADR-066. It compares
all administer, audit, organization/workspace and range-scoping methods in the
baseline v1 contract with the prepared service, DRF, browser and non-API paths.
The scope clarification in [issue #2317](https://github.com/Brad-Edwards/shifter/issues/2317#issuecomment-5825481291)
makes #2321 the sole production activation point. Completion of this preparation
does not claim that unmounted routes enforce production traffic.

Prepared paths are exercised through `config.account_admin_urls`; its domain
URL modules are not included by production. `AccountAdministrationEntry` and
`PlatformAdministrationPage` are not imported by production router/navigation.
All actors use admission-derived credentials; facts, flags and UI hints do not
grant policy. Public principal and hierarchy inputs use UUIDs; existing v1
user-ID and request-correlation contracts are retained.

| Baseline methods / behavior | Prepared operation and registered gate | Enforcement and behavioral evidence |
| --- | --- | --- |
| Workspace context; administrable organizations GET | `/accounts/context/`, `/accounts/`, `/accounts/current/`; account.read and exact subdivision reads | `_policy_context`, `_account_policy_admin`, `_account_policy_reads`; account-policy, profile and prepared-route tests. Individual presentation has no subdivision selector; service identities do not impersonate a contact. |
| Organization detail GET/PATCH | `/accounts/{account}/organizations/{organization}/`; organization.read/update | `_policy_profiles`, `policy_profile_views`; profile and prepared-route tests preserve exact parent, validation and PATCH mask. Browser account-page tests exercise selection and mask. |
| Workspace collection GET/POST, detail GET/PATCH | Account/org workspace list/search/create/detail plus `/workspaces/{uuid}/rename/`; workspace.read/update, organization.manage_workspaces | `_account_policy_reads`, `_account_policy_admin`, `_account_policy_lifecycle`; account-policy service/API, lifecycle and profile tests cover authorized counts, search, archived discovery, siblings, ceilings, defaults and strict audit. |
| Workspace archive/restore POST | Same paths; workspace.archive/restore | Incumbent locked lifecycle writers through policy commands. Defaults and personal compatibility protection remain; archival does not delete ranges. `test_account_policy_admin.py`, `test_lifecycle.py`. |
| Workspace owner transfer POST | Same path, principal source/destination UUIDs; workspace.transfer | `_policy_memberships`; multiowner facts, destination membership, last-owner and audit rollback tests. Owner add/remove are also prepared. No role/policy grant accompanies ownership. |
| Workspace self membership GET and leave POST | Same path families; workspace.read and separately registered workspace.leave | `_policy_memberships`, `policy_membership_views`; self query takes no subject, leave cannot abandon the last owner. Principal membership tests. |
| Workspace roster GET/POST, remove POST, role POST | Principal roster GET/POST/DELETE. Role authoring is replaced by scoped policy/group assignment, not stored membership roles | workspace.manage_members; `_policy_memberships` tests human/service, empty-role facts, ceiling denial, owner protection, quota and strict rollback. The integer-user compatibility transfer delegates to principal ownership facts without editing legacy roles. Old user-role mutation is not mounted in the prepared URLConf. |
| Workspace invitation GET/POST, resend/revoke POST | Same path families; workspace.manage_invitations | `_policy_invitations` reuses signature/generation/delivery/rate/quota/status writers. Invitation and browser panel tests cover rotation, revoke, sibling denial, exact verified binding/current inviter and replay. Principal provenance constraints forbid partial/mixed rows. |
| Workspace quota GET, egress PUT | Same path families plus quota-policy PUT; workspace.read/manage_quota/manage_egress | `_policy_profiles`, `_account_policy_quota`; incumbent projection and locked writers. Policy profile/quota/egress service/API tests and prepared browser limits. Egress remains a provisioning selection, not retrofit enforcement. |
| Authorization/predefined catalogs GET | Existing catalog paths, same central catalog | `authorization_views`; catalog/model/surface tests. No copied action list or evaluator. |
| Groups and policies GET/POST | Existing workspace paths, generalized installation/account/org paths; matching manage_authorization | Existing `_authorization_policy` and `_authorization_scoped_api`; account/scoped authorization API and browser tests preserve exact ancestry and authority-before-count. |
| Group membership, policy assignment/actions, direct/predefined assignment POST | Same journal adapters generalized to every concrete scope | Matching manage/delegate_authorization plus native action/descendant proof; existing delegation, policy journal, native conformance and released OpenFGA tests. Frozen idempotency, uncertainty and current-authority recovery remain. |
| Authorization operation GET/POST reconciliation | Same scope's journal read/reconcile | Existing operation services and browser operation status/retry controls. No new mutation workflow or implicit retry. |
| Users collection/detail GET and search/filter/page | Same paths; installation.manage_principals | `management.admin_services`, `PolicyAdminUser*View`; lifecycle/policy and composition tests authorize before search/count/lookup. No staff/superuser/model-permission veto. |
| User lifecycle/set-active/delete POST | Same paths; installation.manage_principals | Existing locked `management.lifecycle`; policy-lifecycle tests retain temporary-account, recovery and lifecycle invariants. Prepared hints are advisory and include the durable principal UUID. |
| User reset-password POST | Same path; installation.manage_principals | Existing password-reset delivery and throttling; policy lifecycle/reset tests. A service administrator never receives the human's password. |
| User grant-organizer POST | Same path with a concrete account/org/workspace and idempotency key | Root manage_principals plus scoped create_event delegation/journal. `api_account_administration`; journal API tests and scoped browser mutation reuse. No Django global-group mutation or creator impersonation. |
| User transfer-ownership POST | Same path and bounded summary; installation.manage_principals plus workspace.transfer / range.transfer_ownership | `_policy_offboarding` composes tenancy and Engine public services. Offboarding/composition tests verify inactive source, active/member destination, blocked outcomes, projection drift and no fabricated membership/grants. Effects are per-resource. |
| Global audit collection/detail GET, filter/search | Same paths; installation.read_audit | Existing authorized audit service and PolicyAuditLogViewSet plus AuditPage; audit policy/store/browser suites. Historical evidence stays installation-wide. No export/download operation exists in this baseline inventory. |
| Lease settings GET, tenant/group PUT and reset POST (five operations) | Same paths; installation.manage_lease_policy | Prepared policy subclasses invoke existing revision-aware locked lease writers. `test_policy_lease_admin.py` and runtime lease suite cover service authority, ceiling and validation. Customer quota never grants deployment lease authority. |
| Range-scoping collection GET and range workspace POST | Same paths; workspace.manage_range_scope in persisted source and requested destination | CMS `_policy_range_scope`, tenancy proofs and Engine CAS. Tests move all ancestry/reservations together, move back, reject destination policy/quota, preserve immutable aggregates, discover archived sources and roll back strict audit failures. Browser confirmation uses public correlation/destination UUIDs. |
| Personal/service credentials and privileged revoke | Existing credential API plus prepared administrator personal list/revoke | Incumbent #2316 services and ceremonies; exact installation actions, credential policy/native admission tests and `test_policy_token_admin.py`. Full administrator excludes own personal-token use; owner-session issuance/rotation still requires its separate action and ceremony. |

## Non-API paths

| Path | Prepared behavior and evidence |
| --- | --- |
| Django User/UserProfile admin add/change/delete/bulk | `PolicyUserAdmin`, `PolicyUserProfileAdmin`, `PolicyAdminSite` are dormant. Reads use policy. Direct writes are disabled; canonical profile/lifecycle/reset commands retain supported operations. Provider binding, recovery state, password, flags and authority cannot be edited as ordinary metadata. Policy admin tests cover each write hook and admission without staff flags. |
| Workspace quota/invitation admin | Dormant `PolicyWorkspaceQuotaAdmin` / `PolicyWorkspaceInvitationAdmin` filter the complete policy-visible queryset before Django counts/pages; all writes/bulk actions disabled in favor of canonical commands. Legacy registrations stay live only until S8. |
| Audit/activity admin | Dormant immutable policy reads; no add/change/delete or bulk mutation. Historical rows are installation-only. |
| Login invitation staging/callback | Existing signed token staging and CSRF/login proof; prepared callback uses fresh issuer+subject directory binding and current inviter policy. The adapter is not registered until S8. Invitation behavioral tests exercise acceptance and replay. |
| Legacy browser paths | Existing shell serves the current SPA. Prepared account/platform components reuse apiFetch, same-origin session/CSRF and TanStack Query. No production route/nav swap or new browser-storage credential path. Account/scope panel, range confirmation and platform identity tests cover prepared interactions. |
| Management commands/utilities | No retained production administrative command grants policy, edits account ancestry or performs lifecycle deletion. `delete_user` now requires both the explicit test-run marker and test environment before any lookup, and is not wired to the prepared admin site/API. Identity onboarding remains with the existing admission/proof services. |
| Count, search, pagination, export/download | Authorized collections are filtered before count/page; queries are bounded. The baseline administer/audit/workspace inventory exposes no export/download. Credential one-time delivery and range access downloads remain under their incumbent dedicated services and ceremonies. |

## Acceptance mapping

- [x] Customer/sibling isolation in prepared direct services, routed test API,
  collection/search/detail/create/update and browser scope selection:
  `_account_policy_admin`, `_account_policy_reads`, `_policy_profiles` and their
  service/API/browser tests.
- [x] Human/service parity for prepared platform, identity, policy, quota, lease,
  audit and credential administration, preserving owner-session ceremonies:
  policy lifecycle, credential, lease, composition and released-provider suites.
- [x] Delegated credential ceiling, ancestor proof, sibling/higher scope and
  revocation denial: existing native policy/delegation journal suites plus
  released-server hierarchy discovery using the declared administrator ceiling.
- [x] Source/destination authority and consistent affected ownership/scope:
  `_policy_offboarding`, `_policy_range_scope`, tenancy membership/owner writers,
  Engine expected-owner/ancestry CAS and quota reservation tests. Offboarding carries the original departing user through enumeration and each locked writer; named active-range collisions remain bounded blocked outcomes. Terminal status convergence locks and rereads the persisted range binding before quota release.
- [x] Baseline operation and non-API mapping: the method inventory and tables
  above, derived prepared OpenAPI/client, dormant routes and admin registrations.

#2321 activates these prepared surfaces together with the final account mapping
and authority cutover. S4 has no mixed-authority production rollout; the issue
can be closed after its completed preparation is reviewed and merged according
to the authoritative scope clarification.
