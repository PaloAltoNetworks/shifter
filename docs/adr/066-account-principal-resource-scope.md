# ADR-066: Stable accounts, independent principals, and explicit resource scope

## Status

Accepted for the identity and authorization redesign agreed on #2308. Issue
#2314 is the first schema and mapping slice. Runtime cutover remains S8.

## Context

The current tenancy model gives every Django user a synthetic personal
organization and workspace. It also treats one deployment as one customer
boundary. Those assumptions cannot represent an individual customer without
invented subdivisions, a person who belongs to several customer accounts, an
independent service identity, or shared B2C and B2B hosting.

The useful incumbent boundaries remain sound: `workspaces` owns customer scope
and membership policy, `management` owns application identity, `shared` owns
dependency-neutral contracts and cross-cutting primitives, and other domains
carry validated scalar scope references rather than cross-layer foreign keys.

## Decision

### Customer hierarchy

`workspaces` owns one stable, publicly opaque `Account` root with a closed type.
An individual account has no organization or workspace. A team or enterprise
account has one default organization and may have more; every organization has
one default workspace and may have more. An organization belongs to exactly one
account and a workspace belongs to exactly one organization.

Creating the type-required default structure is an idempotent domain operation.
It does not infer or create a membership, owner, administrator, policy, or cloud
grant from the caller, creator, Django user, provider claim, or account type.
Any grant is a separate explicit mutation.

Existing organization and workspace primary keys and UUIDs remain stable when
the row has a valid place in the new hierarchy. The words account,
organization, and workspace describe distinct facts and are not aliases.

### Principals and provider bindings

`management` owns stable `Principal` records with a closed human or service
kind. A human principal retains the existing Django user as its authentication
and lifecycle record. A service principal has no fabricated Django human and is
not the principal of its creator or responsible contact. Changing or removing
creator/contact responsibility does not change the service principal identity,
memberships, policies, or owned resources.

Provider identity is an immutable binding from an exact, opaque
`(issuer, subject)` pair to one principal. The tuple is unique. Email, username,
provider group, sign-in method, or subject without issuer is not an identity
key and cannot merge, repair, or rebind a principal. A collision fails closed.
The existing `shared.verified_identity.VerifiedIdentity` gate remains the only
provider-evidence shape admitted by the Cognito/OIDC and Identity Platform
adapters.

Email-free temporary CTF users remain supported as human principals without a
provider binding. Their durable `UserProfile.is_ctf_account` origin marker,
password-change gate, event-native authority, and provider-login exclusions
remain authoritative.

### Membership and authority

Customer membership targets a principal, not a Django user, email, provider
identity, API token, or creator relationship. Account, organization, and
workspace memberships are explicit facts at their own scope. A membership or
role at one scope grants nothing at another scope unless the owning policy
explicitly composes it.

The existing `workspaces.services` boundary stays the customer-scope owner and
the only resolver of SQL-owned resource ancestry. Cross-domain consumers
receive immutable scalar projections or authorization results and never import
workspaces models. OpenFGA becomes authoritative for application permission
relationships at the S8 cutover; SQL continues to own identities, resource
state and ancestry, and display metadata. SQL rows must not mirror or evaluate
OpenFGA relationships. Provider groups, Django groups, token scopes, CTF roles,
cloud IAM, and cached UI capabilities do not become alternate application
permission stores or implicit grants.

### Shared principal and scope contracts

`shared` owns one dependency-neutral principal reference and one closed
`ResourceScope` contract. The scope has an explicit discriminator:

The principal reference carries only the stable opaque principal UUID and its
closed human/service kind. It carries no user, provider, credential, account,
membership, role, or policy data.

- installation scope has no account, organization, or workspace identity;
- account scope requires an account identity, may include its organization,
  and may include a workspace only with its organization.

Missing customer identifiers never means installation scope. The shared
contract rejects malformed shapes; `workspaces.services` resolves identifiers
and rejects an organization from another account, a workspace from another
organization, archived or otherwise inadmissible scope, and any subdivision on
an individual account. Owning domains persist the validated scalar scope facts
they require. They do not add a cross-layer foreign key, JSON scope bag, copied
hierarchy, or local scope validator.

CTF event creation authorizes against one existing account, organization, or
workspace parent before the event exists. Personal events use their individual
account directly. Business events use validated organization or workspace
ancestry. The OpenFGA event object has exactly one parent relation matching the
SQL-owned scope; extra or stale parent edges deny, including for event-derived
ranges. The shared action catalog registers parent-scoped creation and the
separate CTF management distinctions. Creator attribution, principal ownership,
event administration, and competition participation remain separate facts.
S5 prepares and tests these contracts; S8 activates them together with the rest
of the application authority cutover.

### Mapping and cutover

Current users map to human principals by durable user ID. Existing provider
tuples map to provider bindings only from complete, valid evidence. Existing
membership and ownership rows map through that user-to-principal relation, not
through email, name, group, or ordering. Existing organization and workspace
rows keep their durable IDs when their ancestry is valid.

Legacy personal-workspace data maps to an individual's account-level scope only
when the current ownership projections and synthetic personal structure make
that mapping unambiguous. Shared organizations cannot be guessed to be team or
enterprise accounts. Subject-only provider rows cannot be assigned an issuer by
guessing. Extra members, conflicting owners, cross-layer projection drift, or
other contradictory evidence stop mapping with bounded internal row
identifiers. Mapping never deletes, silently reassigns, or fabricates a grant to
make inconsistent data fit.

Source changes may establish and test the new schema before S8, but they do not
activate a mixed authority model. There is no dual-write compatibility window,
read fallback, customer-specific deployment requirement, feature-flagged
policy fork, rollback to the personal-workspace model, or partial production
cutover. S8 is the activation point after all mappings and constraints pass.

### Hosting and policy boundaries

One deployment may host unrelated B2C and B2B accounts. Account scope is an
application authorization and data-partition fact; it does not by itself prove
separate PostgreSQL, encryption-key, cloud-project, network, secret, workload
identity, or incident boundaries. Those guarantees require their own effective
controls and evidence.

Application, cloud, organization, workspace, event, participant, operator, and
external-client authority remain distinct and compose only through their owning
service boundaries. Deliberately granting one principal full application and
cloud authority is supported as two explicit grants. No role or account type
implies the other grant. Dependency loss never creates permission or a
successful effect.

The redesign uses provider-native GCP identity, IAM, and renewal; OpenFGA for
application policy; established Django mechanisms; and django-rest-knox in the
slices that own those integrations. This ADR does not authorize a custom
authentication protocol, policy engine, token format, secret broker, JIT/Vault
dependency, or organizational approval workflow.

S7 (#2320) preserves deliberately assigned project-admin operator service
accounts and permits the same service full application authority through a
separate explicit grant. Protect credential use, impersonation and execution
boundaries; do not silently reduce chosen powers or broaden ordinary workload
defaults. Supported single-project deployment supersedes ADR-008-R7's mandatory
distinct dynamic-secret project and migration-only equality rule for S7. The
explicit project seam and named/prefix-conditioned access controls remain;
parent-scoped create-only access is not a prefix or separate-project boundary.
[The GCP integration preflight](../architecture/gcp-native-identity-authority-preflight-2320.md)
records the native renewal, SQL-duty, configuration/admission and OpenFGA trust
limits. Preshared client authentication and runtime method allowlisting do not
claim server-enforced per-client model/store privileges. Enforcement must be
reconciled with these documented choices without blanket exemptions. This
clarification does not approve custom source or move S8 activation.

### Administration at cutover

At S8, every application administration operation, including its direct service
call, uses the registered action, resolved target/scope, live principal, and
credential ceiling through the shared authorization contract. Human and service
application administrators can perform the same valid application operations
when their credentials permit them. Django staff/superuser flags, model
permissions, customer membership, and browser capabilities remain distinct
facts; none substitutes for an application policy decision. A browser-only
credential ceremony still requires its own session and CSRF admission.

This supersedes ADR-045-R3's staff-session-only audit-read gate at S8: the
deployment-global ledger is read through `installation.read_audit`, with the
same policy check for its list and detail views and an authorized credential.
The current ledger has no trustworthy customer scope per row, so a customer
role cannot filter or read it by inferred entity, actor, selected workspace,
or request parameter. Tenant-visible audit would require explicit scope at
emission, integrity-protected persistence, and a separately registered scoped
read action. Historical rows without such evidence remain installation-only.

The same S8 policy boundary supersedes the Django-superuser-only application
override in ADR-046-R13, quota authoring in ADR-046-R10, and organization
overrides in ADR-048-R2/R3 for operations delivered by the new administration
surface. Source and destination scopes must each be resolved and authorized for a transfer;
existing owner, membership, lifecycle, cloud, and consistency constraints still
apply. Retained Django-admin or legacy browser writes enter the same authorized
service command or are disabled once a supported canonical UI/API path exists.
These changes do not grant a service principal a Django admin session, make
cloud IAM an application grant, or alter historical audit evidence. Before S8,
the established gates remain the sole production authority.

The #2317 [preflight](../architecture/account-administration-preflight-2317.md)
and [coverage inventory](../architecture/account-administration-coverage-2317.md)
clarify the integration boundary: human-user lifecycle is not customer Account
lifecycle, deployment-wide settings are not customer policy, and invitation
acceptance is not identity resolution by email. Prepared adapters and catalog
entries do not prove mounted-operation coverage. Provider failure cannot become
an empty authorized result; transfer summaries must preserve blocked outcomes
and must not claim atomicity across independently committed resources.

Per-resource membership, ownership, policy and projection rejection must retain
earlier committed offboarding counts. The prepared summary reports all blocked
workspaces separately from confirmed missing-membership cases. Credential
revocation and rotation acquire the owner mutex before the token mutex, matching
identity lifecycle. Recovery-email changes require the owning human session;
an installation principal-administration grant alone cannot redirect recovery.
Standalone organization operation recovery derives its persisted account
ancestry and retains the journal's current-effect authorization checks.

The prepared OpenAPI TypeScript declaration follows the incumbent generated
schema analysis exclusion under the exact, owned, time-bounded ADR-003-R7
exception. DRF contract drift and TypeScript consumer checks remain mandatory;
handwritten administration code retains the ordinary analysis gates.

The OpenFGA application-policy boundary, supported SDK operations, durable
write semantics, deployment contract, and cutover constraints are clarified by
`docs/architecture/openfga-authorization-preflight-2315.md`. That clarification
does not move the S8 activation point or authorize mixed runtime authority.
Delegation proofs enumerate a bounded, complete descendant set from the
SQL-owning domain service boundaries before asking OpenFGA to evaluate it;
provider graph discovery is never authoritative ancestry. A blocking Quality
job runs the released OpenFGA/PostgreSQL harness whenever platform changes are
selected, so missing harness configuration or skipped conformance cannot pass.
The general PostgreSQL lane deselects the `openfga` marker because that service
posture is owned by the equally mandatory released-server job, not by a bare
PostgreSQL service. Both jobs retain the PostgreSQL fail-on-skip guard; the
OpenFGA harness also requires its server configuration explicitly. CI contract
tests keep the lane selection and mandatory dedicated job coupled.
Each descendant retains its SQL scope during delegation checks. Durable
operations bind their provider store and model; explicit HTTP recovery checks
the caller's current authority for the recorded effect before replay. Helm
migration service-account and egress prerequisites remain present until the
dependent job finishes, including first enablement on an existing deployment.

## Supersession

S3's credential integration is documented in
[the credential boundary and client contract](../technical/shifter_platform/access-credentials.md)
and [its preflight](../architecture/unified-credential-auth-preflight-2316.md).
It uses Knox and Google/Firebase public SDKs, immutable SQL credential metadata,
live personal-token eligibility and shared HTTP/Channels session validation.
Personal credentials retain an immutable exact target in their shared action
ceiling; policy requests and mutation journals preserve that target dimension.
Principal-based CTF admission uses an explicit event-scoped API and the existing
participant-safe projection and registration/status eligibility predicate.
Credential-authorized mutations propagate canonical principal UUID attribution
through the shared audit contract and durable authorization journal. Audit v2
hashes that indexed identity while retaining the frozen v1 historical profile;
the migration advances the append profile without rewriting committed evidence.
`config` may consume `workspaces.services.hierarchy_target_scope` solely for
credential-issuance ancestry; it gains no workspace model or mutation access.
The standalone `shifter_client` package is owned by the platform quality unit,
with native-renewal tests in the platform test suite. These source and enforcement
changes preserve the coordinated S8 activation boundary.

This decision supersedes:

- ADR-045-R3's staff-session-only audit read when the S8 policy cutover occurs.
  Shared audit ownership, append-only integrity, and denied-read evidence remain.
- ADR-046's per-user personal organization/workspace compatibility default and
  the parts of its membership contract that use a Django user as the durable
  member identity. Its workspaces-domain ownership, scalar cross-layer
  references, service authorization, locking, opaque denial, and distinct
  authority rules remain incumbent.
- ADR-048's bootstrap administrator inference for personal organizations. Its
  explicit organization authority, service ownership, UUID-only public
  identity, transaction, and strict-audit rules remain incumbent for real
  organizations.
- ADR-054's one-customer-per-deployment decision and its personal-workspace
  migration assumption. Its least-privilege, distinct-authority,
  deployment-local effect ownership, fail-closed outage, and real-boundary
  evidence requirements are carried forward here.

PLAT-2011, PLAT-232, and PLAT-233 must be reconciled through Ground Control when
implementation begins. Historical migration files remain immutable evidence;
new forward migrations replace the active invariant.

## Consequences

The model can represent an individual without fake subdivisions, one person in
several accounts, and a service whose identity outlives its creator. It also
requires explicit account scope on customer data and explicit ancestry checks
at every owning service boundary. Current personal-workspace shortcuts cannot
be retained as hidden defaults.

Shared-hosting support increases the importance of negative authorization,
mapping, and provider-isolation evidence. Schema presence alone does not claim
that S8 cutover or live multi-customer isolation has occurred.

### Prepared composition boundaries (#2317)

Dormant domain URL modules own their account administration routes. The
composition root imports the public `PolicyAdminView` admission/error base and
`AuthorizationMutationSerializer` operation projection for its two cross-domain
adapters. The layer checker permits only those named presentation symbols and
the exact tenancy journal/placement services. Domain persistence and private
helpers remain inaccessible to composition. No production URL or Django-admin
registration changes in S4.

## S7 native identity integration

Issue #2320 adds the released Cloud SQL Auth Proxy as one digest-pinned native
sidecar with a loopback SQL listener and automatic IAM renewal. The hardened
provisioner Job admits exactly that sidecar only when trusted deployment
parameters select native GCP SQL; image/argument/credential/mount/identity
substitution remains denied. Deterministic Job recovery also verifies it.
IAM connector/login bindings apply only to the installation instance. The
Guacamole client and deployment owner receive connector transport only; guacd
has its own KSA and no cloud identity. Existing WIF, operator and CI grants stay
additive. The portal directory duty contains only `firebaseauth.users.get`.

OpenFGA runtime and administration use separate private authenticated listeners,
KSAs/GSAs and native database duties. Released PostgreSQL ACLs deny runtime
store/model/assertion mutation, schema ownership and migration-version writes;
the migration identity owns only the policy datastore. Runtime tuple writers
remain trusted. Deployment-owned bootstrap removes documented Cloud SQL runtime
role defaults, checks effective inheritance/ownership and fails closed on drift.
It preserves the separate qualified migration owner. Native IAM and admission
negative tests, released-server SQL tests and existing guards enforce this
boundary. The released-server lane publishes supplemental coverage for these
SQL duties to Sonar, alongside the platform fast-lane report. The existing
whole-package floor and changed-code coverage gate remain enforced; supplemental
service coverage does not replace either. Two historical permission migrations now quote the active database
name when granting/revoking CONNECT, correcting cold-install targeting without
changing their schema or intended duties. This does not redefine historical
account-policy invariants.

See the [operator guide](../ops/gcp-native-identity.md) and
[implementation contract](../technical/platform_infrastructure/gcp-native-identity.md).
Local tests do not claim live credential renewal or effective deployment IAM;
deployment-specific qualification belongs to the operator's live testing session
and is not a source-publication gate.
