# Unified credential boundary

Issue #2316 delivers ADR-066 S3 source for the coordinated S8 cutover. Do not
deploy it alone into a mixed-authority production fleet. S4–S6 own the named
domain enforcement conversions; S7 owns deployed IAM; S8 qualifies and activates
the complete parent design. This change does not deploy cloud resources or grant
cloud roles.

## Admission and ownership

`shared.credentials.CredentialContext` carries an immutable principal, credential
kind, safe identifier and exact action ceiling. One bearer-first DRF authenticator
dispatches to public Knox or google-auth verification. Invalid bearer proof raises
401 even beside a valid session. Legacy human-only consumers reject services;
they never impersonate the service's creator. OpenFGA administration consumes the
neutral context directly.

Management owns principal/binding/admission lifecycle. Provider tuples are immutable
and unique. Native service admissions have immutable audience/scopes and irreversible
disable; a replacement row preserves the principal. SQL guards cover ORM bulk writes
on both SQLite and PostgreSQL. Credential operations and strict audit records commit
together. No network policy/provider call occurs under their database row locks.

User saves idempotently reconcile the profile and human principal in one transaction.
If creation ran in autocommit and identity/audit persistence failed after the user
insert, authentication remains denied until a later user save repairs the missing
rows. Retry that save after restoring audit persistence; reconciliation emits one
principal-creation audit record and grants no authority.

Authorized credential administration and service participation record the caller
in the canonical `actor_principal_uuid` audit field, including nested principal
and provider-binding creation. Workspace authorization request context and its
durable mutation journal carry the same UUID through confirmation/reconciliation.
Audit canonicalization v2 hashes that field; historical v1 records are preserved
unchanged. See [audit architecture](../../architecture/audit-system-architecture.md)
for the append-profile migration and the prohibition on mixed-version writers.

Knox owns all personal-token generation, hashing and verification. Metadata retains
scope, exact issuance target, principal, expiry, ownership and audit identity. Native proof expiry cannot
extend metadata expiry. Historical rows receive deterministic public credential IDs
and exact owner-principal mappings but no new secret. `requires_reissue` identifies
unrevoked historical rows. Orphaned rows remain unusable; no email-based repair occurs.

Issuance requires a human session with CSRF, a live token-use grant and a live policy
check for every requested action under SQL-resolved target ancestry. Canonical new
scopes are `authorization:<action-code>`. Legacy HTTP scope aliases cannot be newly
issued through the management API. The exact target type/UUID is persisted and
SQL-immutable, reconstructed into the credential ceiling, and checked by every
`AuthorizationRequest`; even another resource the owner can access is denied.
At use time credential ceilings restrict actions and targets;
live application policy and domain lifecycle remain independently required.

## Human and temporary sessions

The obsolete PLAT-101/CTF-608 magic-link flow was removed in CTF migration 0033
(#1206). The maintainer explicitly confirmed preserving current isolated-account
login and recovery for #2316, not restoring that retired protocol.

Firebase Admin verifies signature, revocation, exact project audience/issuer and
configured tenant. Enrollment alone is not MFA assurance: the verified token must
show a `totp` or `phone` second-factor sign-in. Provider account lookup independently
requires verified email and enrollment. The management binding facade rejects
collisions and temporary accounts; it synchronizes the immutable principal binding.

Only non-secret identity/timing evidence enters Django sessions. HTTP and Channels
share local-principal checks and bounded Firebase user-state revalidation. Provider
outage fails closed when revalidation is due. WebSockets reload the stored Django
session before admission and each received/sent message, so logout and password
invalidation do not leave a cached authenticated socket. No raw ID token is retained.

Temporary email-free accounts keep their existing Django login, password-change and
event lifecycle gates. Their neutral credential context names one live event and
permits only `event.read`/`event.participate`, never administration, provider binding
or personal-token issuance. Existing CTF HTTP/socket boundaries remain in force.
The canonical ceiling binds the exact event target, and the context rejects any
disagreement between that target and its event UUID.
Participant principal UUIDs are scalar projections on the existing participation
record, not a second authority store. Ordinary QA services use the same participation
record and live policy plus event/status predicates.

An actor with live `event.manage_participants` authority can POST
`/api/v1/ctf/events/{event_uuid}/principal-participants/` with an existing service's
`principal_uuid` and display `name`. This creates no Django user or credential and
grants no OpenFGA action. With separate `event.participate` authority and admission,
that service can GET `/api/v1/ctf/me/events/{event_uuid}/participant/` using its native
ID token. The response is the existing participant-safe current-event projection;
canonical registration/status eligibility, exact event and live principal/policy
checks remain mandatory. This is the ordinary principal boundary, not a QA role or
service-name exception.

## Configuration

| Setting | Default | Enforced policy |
|---|---|---|
| `GCP_SERVICE_TOKEN_AUDIENCE` | empty outside GCP renderer | Exact HTTPS portal audience; empty disables native bearer admission |
| `IDENTITY_PLATFORM_TENANT_ID` | empty | Exact configured tenant, including rejection of unexpected tenancy |
| `IDENTITY_SESSION_ABSOLUTE_SECONDS` | 28800 | 60–86400; measured from provider authentication |
| `IDENTITY_SESSION_IDLE_SECONDS` | 1800 | 60–3600 |
| `IDENTITY_SESSION_RECHECK_SECONDS` | 300 | 1–300; maximum provider-state staleness |
| `API_TOKEN_MAX_TTL_DAYS` | 365 | 1–365; finite and immutable at issue time |

The GCP runtime renderer derives audience from `SITE_URL` and forwards the tenant and
session bounds from its environment. The portal manifest and installer runtime
inventory/published contract declare these values. Invalid bounds fail startup.
Tenant configuration must match the provider, browser and server; changing the
provider project/tenant invalidates existing human-session evidence.

## Supported renewable client

Install the repository-owned package (Python 3.12+):

```bash
python -m pip install ./shifter/shifter_client
```

The client composes Google's `Credentials`, `IDTokenCredentials` and
`AuthorizedSession`. The official library refreshes before requests as proof expires;
there is no renewal daemon, custom JWT issuer, password protocol or static-key flow.
Application ID tokens and cloud OAuth access tokens use separate transport instances.
Native APIs and refresh behavior are documented by
[google-auth](https://google-auth.readthedocs.io/en/latest/reference/google.auth.impersonated_credentials.html)
and [AuthorizedSession](https://google-auth.readthedocs.io/en/latest/reference/google.auth.transport.requests.html).

```python
from shifter_client import ServiceClient

client = ServiceClient.from_adc(
    "https://portal.example.test",
    target_principal="agent@synthetic-project.iam.gserviceaccount.com",
)
try:
    response = client.request("GET", "/api/v1/bootstrap/")
    response.raise_for_status()
    # Cloud IAM remains independently authoritative. Never send the app token here.
    cloud_response = client.cloud.get(
        "https://storage.googleapis.com/storage/v1/b/synthetic-bucket", timeout=30
    )
    cloud_response.raise_for_status()
finally:
    client.close()
```

Source credential options:

- **Attached workload:** run under an attached Google service account whose metadata
  identity endpoint emits its Google ID token with email. Omit `target_principal`.
  Direct federated Kubernetes principal subjects are not service-account numeric IDs;
  configure service-account impersonation when the metadata endpoint does not expose
  the registered identity. See [attached ADC](https://cloud.google.com/docs/authentication/set-up-adc-attached-service-account).
- **Local impersonation:** use `gcloud auth application-default login`, then provide
  the explicit target service-account email above. The source needs permission to
  generate ID/access tokens on that account (normally Service Account Token Creator),
  and IAM Credentials API must be enabled. Alternatively, Python supports ADC created
  by `gcloud auth application-default login --impersonate-service-account=...`; omit
  the target argument to use that configured impersonation. User ADC is renewable
  only while its refresh authorization remains valid. See [local ADC](https://docs.cloud.google.com/docs/authentication/set-up-adc-local-dev-environment).
- **External federation:** use an administrator-generated, trusted external-account
  ADC configuration through `GOOGLE_APPLICATION_CREDENTIALS` and an explicit target
  service account. The external provider must keep supplying fresh subject proof,
  and IAM must permit the configured impersonation chain. A file containing a single
  expiring subject token is not indefinitely renewable; its producer must refresh it.
  Do not accept untrusted credential configuration or executable suppliers. See
  [auth-library federation](https://docs.cloud.google.com/iam/docs/authenticate-with-auth-libraries).

Long-running success depends on a renewable source, valid IAM, available provider
endpoints and live Shifter admission/policy. A pasted bearer or revoked local refresh
token cannot renew. The app transport rejects foreign-origin URLs and redirects and
does not replay mutations on 401. Handle transient errors with the operation's
documented idempotency contract, not indiscriminate retries. Do not log headers,
credential objects, token responses or secrets.

## Verification and enforcement

Focused tests cover real Knox storage/verification, live grant loss, owner revocation,
MFA assurance and substitution, service independence, native refresh across expiry,
session/logout checks, SQL immutability and PostgreSQL concurrent rotation. The UI's
one-time response bypasses query/mutation caches. The client package belongs to the
platform quality unit; its tests run in the platform environment without importing
Django. Config's sanctioned workspace edge adds only `hierarchy_target_scope`, a
read-only ancestry projection. No layer gains access to another domain's models.

## Issue #2316 acceptance mapping

Paths below are relative to `shifter/shifter_platform/` except the standalone client.

- [x] Human SDK assurance, exact identity and bounded revocation:
  `config/identity_platform.py:198`, `config/session_credentials.py:17` and
  `config/websocket_auth.py:17`; assurance/session tests include factor-only
  enrollment rejection, wrong issuer/audience/tenant, logout, expiry and outage.
- [x] Invalid bearer never falls through; substitution, binding collision and
  disabled principals deny: `shared/api_tokens/authentication.py:38`,
  `config/service_identity.py:13`, `management/principals.py:106`;
  `tests/config/test_service_identity.py`, `tests/management/test_principals.py`
  and `tests/config/test_session_credentials.py`.
- [x] Live-granted personal issue/use, action ceiling, finite immutable expiry,
  no recursive minting and own revocation after grant loss:
  `management/personal_credentials.py:23`, `shared/api_tokens/policy.py:1` and
  `shared/api_tokens/models.py:26`; personal-service, API, SQL-guard and
  PostgreSQL concurrent-rotation tests cover the lifecycle.
- [x] Independent service identity/contact/lifecycle, separate application and
  cloud authority: `management/service_credentials.py:1`,
  `management/principals.py:106`, `shared/api/principals.py:31` and
  `shifter/shifter_client/__init__.py:16` (repository-root path).
  `tests/management/test_service_admission.py` verifies creator independence.
- [x] Supported native renewal across three ID/access token expiry cycles,
  attached metadata and external federation/impersonation:
  `shifter/shifter_client/__init__.py:16` (repository-root path), verified by
  `tests/config/test_service_client.py`; source-renewability limits and all
  three setup paths are documented above.
- [x] Email-free event-confined authentication and ordinary QA service
  participation: `config/credential_scope.py:1`, `shared/credentials.py:15`
  and `ctf/services/principal_participation.py:18`;
  `tests/ctf/test_service_participation.py`, the existing participant-account
  and authentication tests, and `tests/shared/test_credential_context.py`.
  Current login/recovery is preserved; the retired migration-0033 magic-link
  flow stays retired, as explicitly confirmed by the maintainer.
- [x] Credential/service management API/UI, one-time secret presentation and
  safe pagination: `management/api/credential_views.py:1`,
  `frontend/src/features/credentials/AccessCredentialsPage.tsx:1` and
  `frontend/src/features/credentials/ServiceCredentialsPanel.tsx:1`;
  `tests/management/test_credential_api.py` and the page's component test.
- [x] Deterministic S8 reissue mapping with no legacy proof verification:
  `shared/migrations/0027_personal_credential_metadata.py:10`,
  `shared/api_tokens/models.py:26`, verified by
  `tests/shared/test_personal_credentials.py`. Knox and Google public library
  interfaces own proof generation/verification/refresh; no custom protocol or
  renewal daemon is added.

PLAT-102/106 and CTF-006 retain active contracts with reconciled traceability;
PLAT-101/CTF-608 retain their historical statements marked deprecated, documenting
the already-retired magic-link flow rather than claiming a new implementation.
