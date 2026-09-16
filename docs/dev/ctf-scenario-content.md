# Native CTF scenario content

Shifter can populate a native CTF event from a private, digest-pinned content
bundle when the event's scenario is selected. The platform creates the
challenges, flags, hints, and prerequisite graph in the same database
transaction as the event. No content import or plugin is required.

This is an operator publication flow. Shifter deliberately does not expose an
upload API for challenge bodies or flag material.

## Contracts

The deployment reference catalog uses
`shifter-ctf-content-references/v1`:

```json
{
  "contract": "shifter-ctf-content-references/v1",
  "references": [
    {
      "scenario_id": "example-lab",
      "object_key": "ctf/content-bundles/example-lab/sha256-digest.json",
      "digest": "sha256:0000000000000000000000000000000000000000000000000000000000000000"
    }
  ]
}
```

The referenced object uses `shifter-ctf-content/v1`:

```json
{
  "contract": "shifter-ctf-content/v1",
  "scenario_id": "example-lab",
  "challenges": [
    {
      "id": "challenge-001",
      "name": "Example challenge",
      "description": "Participant-facing task.",
      "category": "Discovery",
      "points": 100,
      "difficulty": "easy",
      "order": 1,
      "flags": [
        {
          "type": "http",
          "url": "https://validator.internal.example/verify",
          "method": "POST",
          "timeout": 5,
          "headers": {},
          "case_sensitive": true,
          "order": 0
        }
      ],
      "hints": [],
      "prerequisites": []
    }
  ]
}
```

The parser rejects unknown fields, duplicate JSON keys and identities, unsafe
regular expressions or HTTP validators, malformed prerequisite graphs, and
content over the configured bounds. Bundle challenge IDs are stable,
bundle-local identifiers; prerequisite entries refer to those IDs.

Receipt-capable deployments may instead select an operator-registered verifier
profile without placing its endpoint or credential in the bundle:

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

The profile and objective must already be installed and approved, and a
profile/objective pair may belong to only one active challenge in the event.
See [Signed-receipt CTF validators](ctf-signed-receipt-validators.md) for the
deployment profile, callback, key lifecycle, replay, and failure contracts.

## Publish an immutable object

1. Produce UTF-8 JSON using the bundle contract. Keep the source and generated
   object outside the Shifter repository when it contains private content.
2. Compute the SHA-256 digest over the exact bytes that will be uploaded.
3. Put the digest in the object name and in the deployment reference.
4. Upload with the provider's create-only generation/version precondition.
   Never overwrite a referenced key.
5. Retain the provider object identity and digest in the deployment change
   record.

The portal workload needs read access only:

- GCP: set `ctf_content_bucket_name` on the `gcp-dev` Terraform root. The
  portal workload identity receives `roles/storage.objectViewer` on that
  bucket.
- AWS EC2: set `ctf_content_bucket_arn`, `ctf_content_prefix`, and optionally
  `ctf_content_max_bytes` in the portal environment overlay.
- AWS EKS: set `ctf_content_bucket_arn` and `ctf_content_prefix` in the EKS
  environment overlay and set the bucket, prefix, and maximum bytes in the
  portal workload's `runtime_env`.

The IAM grant is provider identity based. Do not create static storage keys.

## Bind a scenario

Store the complete reference catalog as the
`ctf_content_references` object in the existing application secret. The
entrypoint serializes that field into
`SHIFTER_CTF_CONTENT_REFERENCES_JSON` at process startup. A deployment may
instead inject that environment variable from a private secret, but it must
not put the catalog in a ConfigMap, Terraform output, command argument, or
checked-in file.

The non-secret runtime settings are:

| Setting | Purpose | Default |
|---|---|---|
| `SHIFTER_CTF_CONTENT_BUCKET` | Private object bucket | unset |
| `SHIFTER_CTF_CONTENT_PREFIX` | Contained object-key prefix | `ctf/content-bundles` |
| `SHIFTER_CTF_CONTENT_MAX_BYTES` | Maximum accepted object bytes | `8388608` |

Restart or redeploy the portal and its workers after changing runtime
configuration or the application secret. Startup fails if a reference catalog
is malformed or references are configured without a bucket.

## Create and verify an event

Create an event normally and select the bound scenario. Before the database
transaction starts, Shifter reads the object with a provider identity
precondition, checks its size and declared SHA-256 digest, and validates the
complete bundle. The event, native challenge graph, and hydration receipt then
commit atomically.

Verify:

1. The organizer challenge list has the expected challenge and hint counts.
2. Prerequisite-locked challenges have the expected graph.
3. The audit stream contains a `ctf_content_hydration` create record with the
   digest and bounded counts.
4. Opening registration and activating the event succeeds.

Creating an event for a scenario with no reference is unchanged. A referenced
scenario fails event creation rather than creating partial content when
storage, integrity, validation, native writes, or strict audit recording fails.

## Drift, retry, and rotation

An exact retry against a pristine receipt is a no-op. Any organizer mutation
of managed challenges, flags, hints, or prerequisites marks the receipt
drifted. Activation then fails closed. Shifter never silently merges,
overwrites, or restores drifted content.

To publish a revision:

1. Publish a new immutable object under a new digest key.
2. Update the deployment reference and restart the portal.
3. Either create a new event, or refresh an existing managed event to the new
   revision (see below).

## Refresh an event to the configured revision

An organizer may reconcile a managed event to the currently configured,
digest-pinned revision of its own scenario in place, without tearing the event
down. This corrects a stale challenge title or flag while preserving challenge
identity and every historical scoring row (submissions, hint usage, ratings).
It is an explicit, owner-only content operation, never an automatic sync.

- Endpoint: `POST /api/v1/ctf/events/<event_id>/content/refresh/` with body
  `{"expected_current_digest": "sha256:<64 hex>"}`. The organizer supplies only
  the digest they currently see as an optimistic concurrency fence; the
  server-configured bundle is the target. No object key, URL, bundle body,
  flag, validator configuration, or target digest is caller-controlled. The
  event detail projection exposes the current digest and drift state under
  `managed_content` for the organizer UI.
- Matching is by `(event_id, source_id)`. Matched challenges keep their UUID, so
  submissions, ratings, attachments, and score history stay attached.
- `DRAFT` and `REGISTRATION` events (no scoring ledger yet) may reconcile the
  complete managed graph, including challenge additions/removals and
  hint/prerequisite changes. A refresh is refused if participant history already
  exists.
- `ACTIVE` and `PAUSED` events may refresh only presentation and verification
  fields, including challenge title/content and the complete flag/validator set.
  A revision that adds/removes/renames a `source_id`, changes hints or
  prerequisites, or changes `points`, `minimum_points`, `decay_function`,
  `decay_solve_count`, or `max_attempts` is rejected atomically. Pausing does
  not make those changes safe; create a new event instead.
- `ENDED`, `CANCELLED`, and `ARCHIVED` content is historical evidence and is not
  refreshable.
- Existing submissions and hint usage are never revalidated, rewritten, or
  rescored. A refresh changes only which proof future attempts accept.
- On success the receipt is updated to the target evidence and returns to
  `PRISTINE`; an explicit refresh can therefore also restore drifted managed
  content from its configured bundle. The audit stream records a
  `ctf_content_refresh` event with the previous and target digests, bounded
  counts, and changed-field categories, never content values.

Every path back to `ACTIVE`, including resuming a paused event, re-enforces
managed-content hydration readiness under the event lock, so a paused event
whose configured content has been revised cannot silently resume against stale
flags: restore or refresh it first.

## Failure codes

The organizer/API error remains intentionally generic. Server-side reason
codes distinguish the main operator actions:

| Code | Operator action |
|---|---|
| `CTF_CONTENT_NOT_CONFIGURED` | Set the bucket/runtime configuration. |
| `CTF_CONTENT_RESOLUTION_FAILED` | Check object existence and portal read IAM. |
| `CTF_CONTENT_CHANGED` | Publish and reference one stable object generation. |
| `CTF_CONTENT_DIGEST_MISMATCH` | Recompute the digest over the uploaded bytes. |
| `CTF_CONTENT_INVALID` | Validate the bundle contract and native flag policy. |
| `CTF_CONTENT_SCENARIO_MISMATCH` | Align the reference, bundle, and scenario IDs. |
| `CTF_CONTENT_DRIFT` | Refresh or create a fresh event; do not overwrite managed state. |
| `CTF_CONTENT_NOT_READY` | Restore the configured reference, refresh, or create a fresh event. |
| `CTF_CONTENT_REFRESH_CONFLICT` | Reload the event; the revision changed under you. |
| `CTF_CONTENT_REFRESH_UNSAFE` | Live refresh cannot change scoring/structure; create a new event. |
| `CTF_CONTENT_REFRESH_STATE` | Event state or history does not permit a refresh. |

Object keys, validator configuration, flag material, and provider exception
text are not included in public errors or audit records.
