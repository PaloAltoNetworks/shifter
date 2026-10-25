# Prepared account administration

ADR-066 S4 composes policy-aware services with DRF, the existing policy journal,
Django locks/constraints, strict shared.audit writes, signed invitations and the
existing React query client. `config.account_admin_urls` is a standalone test
and schema URLConf; production `config.urls` and `config.api_urls` do not include
it. Domain routing modules own their paths. The implementation introduces no
new authentication provider, policy evaluator, audit store or environment key.

Organization/workspace memberships retain legacy user/role rows alongside
principal-only rows with an empty role. Named database constraints prohibit
mixed identity shapes. `WorkspaceOwnership` is a separate, unique-per-principal
fact, allowing multiple owners. Owning services lock the parent row to preserve
membership, quota and last-owner invariants. Migration 0020 refuses rollback
once principal facts or invitation provenance exist; empty preparation can be
reversed. S8 maps historical facts explicitly rather than activating guessed
membership or policy.

Owning services revalidate the active principal, immutable credential ceiling,
exact registered action, SQL-owned ancestry and live evaluator. Provider calls
precede SQL row locks; locked writers compare the authorized ancestry and
eligibility again. An incomplete batch or evaluator error cannot produce a
partial list/count. Administrative account/organization/workspace reads belong
to the declared administrator action set. Self-leave is a separately registered
ordinary action, subject to live policy and the last-owner invariant.

The CMS service composes source/destination tenancy proofs with Engine's
expected-owner/ancestry comparisons. Ownership preserves existing range and VPN
constraints. Scope changes update CMS request, CMS projection, Engine projection
and quota reservation in one transaction. Destination capacity is admitted
before releasing the source. Reopened historical reservations support moving
back without bypassing quota. Strict audit failure rolls effects back.

Prepared Django-admin classes disable add/change/delete and bulk mutation.
`PolicyAdminSite` admits active human browser sessions without a staff-flag requirement;
registered model admins authorize reads and filter before counting. Canonical
DRF/browser commands replace direct lifecycle, invitation and quota writes.
The existing admin site and registrations remain unchanged until S8.

The prepared OpenAPI artifact is derived from the same DRF serializers as the
prepared routes. Regenerate it and its client with:

```bash
cd shifter/shifter_platform
TESTING=1 TEST_DB_BACKEND=sqlite uv run python manage.py spectacular \
  --urlconf config.account_admin_urls --format openapi-json \
  --file openapi/account-admin-prepared.json --validate --fail-on-warn
cd frontend
./node_modules/.bin/openapi-typescript ../openapi/account-admin-prepared.json \
  -o src/api/account-admin-schema.d.ts
```

The ordinary API contract continues to describe production routing. The
prepared SPA exports account and platform pages without router/nav imports;
individual presentation comes from the principal/account context. Parent scope
keys reset child drafts, query keys contain exact paths, and policy mutations
reuse the incumbent frozen idempotency and reconciliation behavior.

See [the operation inventory](../../architecture/account-administration-coverage-2317.md)
for baseline replacements and tests. The released OpenFGA/PostgreSQL suite
verifies human/service hierarchy discovery using the declared administrator
credential ceiling and proves that narrowed credentials cannot edit descendants.
Existing journal suites cover delegation, descendant proof, deny and recovery.

Offboarding preserves the command’s expected departing owner through both legacy
and prepared per-range writers, including Engine comparison; an intervening
owner change is blocked. Named active-range collisions roll back that resource
and retain the earlier successful counts. Terminal status convergence locks the
range projection and releases the current persisted workspace reservation, even
when the consumer loaded its instance before a scope move. The integer-user
workspace transfer compatibility helper uses principal ownership facts and
leaves legacy role rows unchanged.

Known per-resource policy, membership, ownership and projection rejections retain
earlier committed offboarding effects. The prepared `workspaces_blocked` count
covers all workspace rejections; the incumbent missing-membership count retains
its narrower meaning. Archived ownership is reported as blocked after an exact
policy check, without preventing transfers of eligible resources. Standalone
organization operation recovery derives the
persisted account ancestry before the journal reauthorizes its recorded effect.

Personal credential commands lock the owner before the token, matching lifecycle
revocation. Metadata email changes require that owner's human session under the
same locked user boundary. The administrative grant alone cannot redirect a
password reset to another recipient.

The exact generated TypeScript declaration follows the incumbent schema analysis
exclusion recorded as an owned, time-bounded ADR-003-R7 exception. DRF drift,
TypeScript compilation and consumer tests remain enforced; handwritten code is
fully analyzed.
