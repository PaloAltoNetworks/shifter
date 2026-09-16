# Shifter contained GCE build profile, version 1

The public RAE mechanism is `materialization-specification`, profile
`shifter-gce-contained-build`, version `1`. Its profile digest is the SHA-256 of
this document's exact UTF-8 bytes. The specification digest is the SHA-256 of
the canonical JSON list produced by `context.context_digest`: every contained
file contributes its relative path and SHA-256, sorted by path. Extra files
change the identity. Links, special files, unsafe paths and unbounded contexts
are rejected. This version delivers at most 96 KiB of contained bytes through
the build VM's private startup metadata.

Every context must contain `build.sh`, `verify.sh` and `verify_boot.py`; missing
entrypoints are rejected before acquiring cloud credentials or creating cloud
resources. The builder executes `build.sh` inside the disposable build guest.
The independent scanner executes `verify.sh` against the read-only candidate
mount. The independently installed `verify_boot.py` must define
`probe_http(host: str, nonce: str) -> bool`: it runs in a separate probe guest,
returns true only after verifying the fresh challenge against the candidate's
service, and bounds its network requests and retries. Candidate-supplied code
cannot replace either verification entrypoint.

RAE remains the owner of the full requirement, profile, specification, fixed
inputs, constraints and permitted acquisition/timing. This profile requires a
constrained requirement explicitly permitting its full profile identity with
acquisition `none` and timing `backend-preparation`. It does not authorize a
fallback when an exact artifact, candidate or image alias is unavailable.

The initial specimen is `contexts/http-smoke`: Ubuntu 22.04, Python's standard
library HTTP service on port 8080, and a systemd unit. It downloads nothing while
building. Its installed files are measured independently, and its fresh HTTP
challenge is exercised separately from checking raw disk integrity. Shifter
maintains the recipe, profile, cloud implementation and verification material.
Private specimens can supply different contained material under an implemented
profile; their declarations must explicitly permit that profile and lock their
actual inputs.

## Cloud authority and private installation

An adapter registration identifies immutable worker and verifier OCI images.
Registry access grants permission to pull bytes; it does not grant permission to
execute them with cloud authority. A separate cloud operator must approve the
exact worker and verifier digests, service accounts, network and budgets in a
deployment-local grant. The verifier is approved independently of the builder.
Installing a pack or possessing content authoring permissions confers neither
executable installation nor cloud-grant authority.

These registrations and grants are installed after tenant setup, including for
private registries and private packs. They do not require publication upstream
or a platform rebuild. An incompatible profile or additional cloud authority
requires explicit operator admission. A new adapter version preserves earlier
immutable registrations, attempts, verification evidence and cleanup references.

The cloud operator's exact executable approval is a trust decision about code
that receives that role. Kubernetes isolation is not a sandbox for arbitrary
unapproved code holding cloud credentials. Builder, verifier and cleanup roles
are separate; the build guest and independent scanner guest have no service
account, external IP or inherited project SSH keys. All cloud names derive from
operation and attempt UUIDs. Candidate creation does not update image inventory.

## Construction and verification

The builder checks the concrete locked base image ID, creates a disposable VM
from that image, and checks the created disk's actual `sourceImageId`. A changed
image under the same name is rejected before candidate image creation. The VM
installs the contained material, removes build staging and host identity, flushes
its disk and shuts down. Private startup metadata is removed before creating
the candidate. The resulting image's actual `sourceDiskId` must match the build
disk. Provider calls are scoped, deadline bounded and refuse redirects; retry
conflicts require ownership readback.

The independent verifier must create a read-only disk from the candidate and
bind that disk to the candidate's actual provider ID. An approved scanner image
reads the complete raw block device, including zero-filled regions. It mounts
the candidate read-only with `noexec`, `nosuid` and `nodev`; verification code
comes from the independently approved verifier context, never the candidate.
The initial profile checks exact service bytes, Ubuntu 22.04, fresh machine and
SSH host identities, and absence of root/home SSH material and private build
staging. A separate disposable boot probe must exercise the prepared service.

The platform must re-read provider ownership and lineage outside its database
transaction, then lock and recheck grant, operation, current attempt and input
identity before admitting verified output. The upstream satisfaction disclosure
must carry the admitted output identity, specification and full verified facts.
Ordinary launch consumes that inventory entry and never invokes construction.
