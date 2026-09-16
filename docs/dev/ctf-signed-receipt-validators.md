# Signed-receipt CTF validators

Shifter supports participant/range-bound signed receipts through the closed
`receipt-v1` validator protocol. This protocol is deployment opt-in: an
installed Django app registers each verifier profile at startup, and a trusted
provisioning or activation integration enrolls the exact range assignment in
Engine. Organizer content can select only a registered profile and objective.

Legacy static, regex, programmable, installed-app, and HTTP validators retain
their existing contracts. A receipt-capable programmable or installed-app
validator must explicitly opt in to server context and return
`VerifiedReceiptEvidence`; returning a truthy Boolean is rejected.

## Deployment profile

Register profiles from installed application initialization, using protected
deployment configuration for real endpoints and secret references. The values
below are fake:

```python
from ctf.validators import ReceiptVerifierProfile, register_receipt_profile
from shared.receipt_validation import ReceiptKeyMode

register_receipt_profile(
    ReceiptVerifierProfile(
        profile_id="example-penr1",
        deployment_id="gcp-example",
        provider_contract="penr1-v1",
        endpoint_url="https://proof.example.invalid/v1/platform/receipts/verify",
        audience="https://proof.example.invalid",
        service_auth_secret_ref="projects/example/secrets/receipt-callback/versions/7",
        issuer_id="example-proof",
        allowed_key_modes=(ReceiptKeyMode.REMOTE_SYMMETRIC,),
        allowed_algorithms=("hmac-sha256",),
        permitted_objectives=("flag-agent-control",),
        total_timeout_seconds=5,
        max_addresses=2,
        max_request_bytes=8192,
        max_response_bytes=4096,
        max_receipt_ttl_seconds=900,
    )
)
```

The profile owns the HTTPS URL, audience, service-auth secret reference,
provider contract, issuer, algorithms, permitted objectives, and all transport
bounds. Participant and organizer input cannot provide a URL, header,
credential, issuer, key, algorithm, timeout, or arbitrary request template.
URLs must be public HTTPS without userinfo, query, or fragment. Runtime uses
DNS-pinned TLS 1.2 or later, preserves the original hostname for SNI and
certificate validation, follows no redirects, limits address fallback, and
applies one total deadline across secret lookup, DNS, connects, and reads.

## Organizer and content configuration

An HTTP receipt flag has exactly this validator selection:

```json
{
  "type": "http",
  "protocol": "receipt-v1",
  "profile_id": "example-penr1",
  "objective_id": "flag-agent-control",
  "case_sensitive": true,
  "order": 0
}
```

Interactive writes, content-bundle hydration, and runtime use the same closed
normalizer. Unknown members, unsupported protocols, missing profiles, and
unapproved objectives fail closed. Within one event, a profile/objective pair
must resolve to exactly one active challenge. This is checked before remote
verification and again under locks before scoring because provider objectives
need not contain Shifter challenge UUIDs.

Context-capable programmable validators put the same receipt selection under a
`receipt` member and register with `supports_server_context=True`. Installed
application validators use the direct selection and the same explicit option.
Legacy callables are never signature-probed or retried with a different shape.

## Trusted binding and provider response

The participant submits only the opaque receipt. Shifter derives the event,
participant, challenge, assigned CMS range, owner, lease, Engine
materialization, current assignment epoch, registration revision, provider
namespaces, reset generation, profile, issuer, key mode, algorithm, and key ID
through CTF → CMS → Engine services.

The receipt callback request is `POST` JSON with exact top-level members
`contract`, `provider_contract`, `audience`, `receipt`, and `binding`.
`contract` is `shifter-receipt-v1`. The binding contains event, provider
participant namespace, challenge, provider range namespace, materialization,
assignment epoch, registration revision, reset generation, and objective. The
request carries `X-Service-Token`, resolved from the profile's protected secret
reference. No cookie or participant session is sent.

An invalid receipt response is exactly `{"valid": false}`. A positive response
contains exactly `valid`, `receipt_id`, `issuer`, `expires_at`, and an exact echo
of `binding`. Shifter accepts only Boolean `true`, the registered issuer, an
unexpired bounded deadline, and byte-for-value-equivalent binding fields. The
stable issuer-scoped receipt identity is consumed transactionally and uniquely;
the raw callback body and receipt are never replay state.

## Registration and key lifecycle

Engine registration is generation-fenced:

```python
register_receipt_verifier(request_id, provisioning_operation_id, demand)
```

The caller must name the current provision or activation operation. Engine
locks the exact request-owned range and rejects stale operations, non-current
materializations, damaged rows, and conflicting retries. An exact retry is
idempotent. `ReceiptRegistrationDemand` binds the deployment/profile,
event/participant, permitted objective set, issuer, provider namespaces,
algorithm, key ID, reset generation, and one of these key modes:

- `remote_symmetric`: Engine stores only a protected secret-version reference.
  The portal and participant never receive the signing key; Shifter calls the
  isolated verifier.
- `asymmetric_public`: Engine stores bounded public verification material. The
  private key remains in the protected signer.

The active registration becomes unusable as soon as its operation generation
no longer matches the range. Reset/rebuild and activation enroll a fresh
assignment epoch after the old row is revoked. Reassignment revokes before
ownership changes. Cancel, teardown admission, failed dispatch/apply, and
terminal failed/destroyed results revoke within the lifecycle transaction.
Paused and expired ranges cannot project a binding. Provider reset and teardown
must independently advance/destroy protected verifier state; deleting a secret
is cleanup, not Shifter's authorization fence.

Registration and revocation write strict bounded audit evidence containing the
request, operation, registration revision, profile, key mode, algorithm, key ID,
reset generation, and status. It contains no receipt, participant namespace,
secret reference, key bytes, endpoint, or callback body.

## Scoring, replay, and failure behavior

Remote verification occurs before database locks. A positive result is only
provisional. The scoring transaction locks and reloads the participant and
challenge, repeats availability and objective-uniqueness checks, and confirms
the exact CMS/Engine registration before creating a solve and receipt
consumption. A revocation or reassignment racing the callback therefore prevents
commit. Rollback leaves the receipt retryable; committed consumption survives
submission soft deletion and rejects alternate encodings with the same provider
identity.

Receipt rejection, unavailable authentication, DNS/TLS/timeout errors,
non-200 responses, malformed JSON, oversized bodies, and invalid positive
evidence all fail closed and award no points. They retain the incumbent HTTP
validator behavior and create an incorrect attempt, so configured attempt and
cooldown policies still apply. A well-formed `{"valid": false}` is not logged as
an outage. Operators receive only fixed categories for unavailable auth,
unavailable provider, or invalid provider response. Logs never include the
receipt, service token, endpoint query, provider exception, response, claims, or
key material.

Authorized submission history stores a fixed signed-receipt redaction marker
for every context-capable verification attempt, whether the receipt succeeds,
is rejected, or cannot resolve an active binding. Legacy flag types retain their
existing submitted-value history. The separate receipt-consumption row stores
only a SHA-256 identity digest and bounded issuer/generation evidence for a
successful redemption.

## Qualification checklist

For every deployed profile, record non-secret evidence for:

1. exact provider contract/version, callback URL/audience, algorithm/key ID,
   immutable signer artifact, and operation-bound registration revision;
2. positive receipt submission and one score transaction;
3. foreign participant, range, challenge, materialization, epoch, objective,
   stale reset, expiry, malformed signature, and replay rejection;
4. callback authentication denial, timeout/error behavior, and log canaries;
5. reset/reassignment/teardown revocation and a distinct second generation;
6. denial of signer and service-auth material to the portal and participant
   guest.

Evidence may contain bounded UUIDs, opaque namespaces, digests, reason codes,
and timestamps. It must not contain credentials, receipt bytes, provider bodies,
proof claims, prompts, browser data, or IAM dumps.
