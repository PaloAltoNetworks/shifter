# Workspace membership SPA preflight

Issue: #1941 (PLAT-234), "Org/workspace admin: membership & roles management surface"

This note records the client boundary for the already implemented workspace
membership API. It adds no role, API, persistence, or workflow model.

## Decision

The SPA membership surface is a consumer of the `workspaces` API contract, not
an authorization implementation. It must use the selected workspace's
server-derived `PrincipalWorkspaceContext.capabilities` for presentation and
must let each command endpoint make the authoritative decision.

The closed `WorkspaceRoleEnum` (`owner`, `admin`, `member`) is rendered only as
membership data and as the generated request enum. Client code must not compare
the actor's role code, reconstruct `ROLE_OPERATIONS`, copy the operation
matrix, or turn `is_staff`, organization authority, a token scope, or a cloud
role into a workspace grant.

The existing Membership navigation entry cannot be gated only by
`read_members`: every member has `read_self_membership` and `leave_workspace`,
but not `read_members`. The navigation/surface predicate therefore needs the
existing capability list to admit the membership surface for either roster
access or self-service leave. It must not use a role string as a shortcut. A
member sees an honest self-service state rather than a roster; owner/admin sees
the roster and the actions the advertised workspace operations permit.

`change_member_role` and `remove_member` capabilities are workspace-level
hints, not target-member grants. The existing service has additional
owner-target, personal-workspace, self-removal, and last-owner rules. Do not
invent client-side target authorization to fill that gap. The client may make
the known final-owner case clear from the rendered roster, but a 409
`last_owner_required` remains the required final result because another request
can change the roster between render and submit.

## Reuse boundaries

- Keep API calls and query keys in one typed membership client alongside
  `frontend/src/api/workspaces.ts`; use `apiFetch`, the generated
  `schema.d.ts`/`types.ts` aliases, `ApiError`, and the shared TanStack Query
  client. Do not hand-copy membership DTOs or create component-local fetches.
- Preserve browser session behaviour from `api/client.ts`: same-origin
  credentials, CSRF on unsafe methods, and request-ID propagation. The SPA does
  not send bearer tokens, store credentials, or expose email input in URLs or
  telemetry.
- Invalidate the roster and self-membership snapshots after successful
  membership mutations. Also invalidate the current-principal context after a
  successful self role change or leave, since its role/capabilities and selected
  workspace validity may have changed. Mutations remain non-retrying.
- Present all server validation/conflict outcomes through `ApiError` and the
  shared error envelope. Use the shared destructive confirmation dialog for
  remove/leave and the existing accessible form primitives; do not replace a
  bounded 403/404/409 response with a locally inferred authorization message.

## Scope limits

This is add-existing-active-account by email only. It does not add invitations,
email delivery, account provisioning, organization-role administration, owner
transfer, bulk operations, a new permission endpoint, a new feature flag, or
any AWS/GCP-specific behavior. No environment, secret, infrastructure,
provider, or OS/process configuration is needed.
