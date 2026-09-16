# Artifact preparation implementation

This profile passed qualification on `gcp-dev` for #1583. The isolated GCE build,
independent disk scan, boot probe and cleanup passed, followed by private-pack
preparation, inventory admission, reuse, ordinary range launch and destruction.
Independent readback matched the range's boot-disk image identity to admission
and observed the prepared HTTP service answering a fresh challenge.

The normative mechanism contract is [PROFILE.md](PROFILE.md). Its digest does
not include this implementation status or qualification record.
The live cloud procedure and current findings are recorded in
[QUALIFICATION.md](QUALIFICATION.md).

Local tests currently cover the contained recipe and verifier, HTTP behavior,
raw-byte identity, scope checks, closed transport, source-name replacement, and
credentialless VM request construction. Provider transport tests use simulated
GCE responses. Tenant Job admission, private pack and adapter registration,
input verification, controller upgrades and failed-operation cleanup have also
passed live checks. The complete prepare-to-launch demonstration remains
required before claiming the capability qualified.

The GCE transport follows the official
[instance creation contract](https://docs.cloud.google.com/compute/docs/reference/rest/v1/instances/insert),
[serial output contract](https://docs.cloud.google.com/compute/docs/reference/rest/v1/instances/getSerialPortOutput),
and [image creation contract](https://docs.cloud.google.com/compute/docs/reference/rest/v1/images/insert).

Qualification uses `gcp-dev`. Branch synchronization is strictly
`origin/dev` → `gcp-dev`; delivery changes go through a PR to `dev`.
The preparation guests use an isolated private network, without public IPs or
service accounts. A disposable probe runs inside that network, so verification
does not require opening the tenant's platform network to preparation guests.
