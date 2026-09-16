# `/api/v1/` versioning and compatibility policy

Status: active

Issue: [#1329](https://github.com/Brad-Edwards/shifter/issues/1329)

Governing decision: [ADR-040](../adr/index.yaml)

This policy defines what may change inside `/api/v1/`, what forces a new major,
and how continuous integration enforces both. It is the operator-facing summary
of ADR-040; the architecture rationale lives in
[the publication preflight note](openapi-contract-publication-preflight-1329.md).

## Source of truth

The runtime Django REST Framework surface is the authoring source: URL routing
in `config/api_urls.py`, the DRF views and serializers, permission classes, and
drf-spectacular annotations. The committed OpenAPI artifact at
`shifter/shifter_platform/openapi/v1.json` is generated from that surface and is
the contract downstream consumers code against. The single-page application
types in `frontend/src/api/schema.d.ts` are a generated projection of the
committed artifact, never a second hand-written schema.

Regenerate the artifact and the derived types after any API change:

```bash
# Backend artifact (also validates and fails on any warning).
cd shifter/shifter_platform
uv run python manage.py api_contract

# Artifact plus the SPA TypeScript projection.
cd shifter/shifter_platform/frontend
npm run gen:api
```

## What `v1` means

`v1` is the public API major carried in the URL. It is not the Django package
version, the frontend package version, or the OpenAPI document patch version.
The URL namespace, `NamespaceVersioning`, `ALLOWED_VERSIONS`, the schema
`info.version`, and the committed artifact path all agree on that major.

## Backward-compatible changes (stay in `v1`)

These are additive and safe for existing consumers:

- a new path or operation that does not affect existing operations;
- a new optional request parameter or optional request-body property;
- a new optional response field (consumers must tolerate unknown fields);
- a wider set of accepted request values that preserves prior meanings;
- documentation, descriptions, examples, and deprecation markers that do not
  change machine-readable behavior.

## Breaking changes

These break an existing consumer and are prohibited in `v1`:

- removing or renaming a path, operation, parameter, request field, response
  field, component, or security scheme;
- making an input required, narrowing accepted input, or changing a parameter's
  location or serialization;
- widening a response type, making a response field optional or nullable, adding
  a value to a closed response union, or changing a field's meaning or units;
- changing success or error status codes, media types, pagination shape, the
  error-envelope shape, stable error codes, or operation identifiers;
- changing an operation from public to authenticated, removing an authentication
  alternative, or tightening a role or scope requirement;
- changing a default in a way that alters behavior for an omitted input.

A breaking change normally ships as a parallel `/api/v2/` surface with aligned
version metadata and a migration note. The existing `/api/v1/` stays available
through its documented migration window. A separately accepted ADR may remove
a complete product surface without retaining that product in another major; an
exact retirement manifest projects only those paths and response properties
from the trusted baseline before the compatibility comparison. Correcting an
inaccurate published schema is still a compatibility change for clients that
coded against it; resolve
generator inaccuracies before the first publication rather than treating a later
correction as routine drift.

A narrowly justified exception belongs in `docs/adr/exceptions.yaml` with an
owner, an expiry, the affected surface, and migration evidence. A pull-request
label, a commit-message token, or an `info.version` edit alone does not
authorize a break.

## Continuous integration gates

The `API contract (shifter_platform)` job in `.github/workflows/_quality.yml`
runs on every pull request that touches the platform:

- **Drift gate.** A fresh, hermetic generation must match the committed
  artifact byte for byte (`manage.py api_contract --check`). Generation fails on
  any warning, unresolved serializer, operation-id collision, or invalid
  document, so a graceful-fallback schema can never be published.
- **Single-page-application types gate.** Regenerating `schema.d.ts` from the
  committed artifact must produce no change, so the published contract and the
  shipped types cannot diverge.
- **Breaking-change gate.** A pinned, checksum-verified OpenAPI-aware checker
  (`oasdiff`) compares the committed artifact against the base branch's already
  published artifact, resolved from the trusted base commit that the same pull
  request cannot rewrite. A consumer-breaking change to `v1` fails the build
  unless its exact removed elements are covered by accepted whole-feature
  retirement metadata.

## Scope of the current contract

The committed `v1` artifact covers the surface consumed by the single-page
application: bootstrap, dashboard, CMS catalog and scenario editor, Mission
Control, and CTF. Endpoints without a single-page-application
consumer are excluded from generation until their consumer lands, at which point
their routes are added to the contract additively. The CTF surface is excluded
until its workspace ([#1372](https://github.com/Brad-Edwards/shifter/issues/1372))
is built. Exclusion affects only schema generation; runtime routing and behavior
are unchanged.
