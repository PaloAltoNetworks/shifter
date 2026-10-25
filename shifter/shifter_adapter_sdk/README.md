# Shifter adapter SDK

Public contracts for independently packaged Shifter adapters. The SDK contains
no scenario implementation and imports no Shifter application modules.

The verification API is available under
`shifter_adapter_sdk.verification`. Installations select a distribution version
and entry point explicitly; discovery does not execute adapter code.

The optional `preparation` extra provides the closed artifact preparation result
protocol under `shifter_adapter_sdk.preparation`. Successful receipts must carry
phase-specific evidence; a failure carries only a bounded reason code. Receipt
validation does not authorize execution or admit an artifact.

Build with `uv build`. Test installation in a separate environment against the
built wheel, without adding the Shifter checkout to `PYTHONPATH`.

The optional `runtime` extra provides the independent runtime-plugin protocol.
An author image installs this extra and its own distribution, exposing a
zero-argument factory in `shifter.runtime.plugins`. The returned object implements
`plan(RuntimeInput) -> RuntimePlan`. Its container entrypoint is
`python -m shifter_adapter_sdk.worker`; installation selects the exact distribution,
version and entry point and pins the image by digest.

The worker receives `SHIFTER_PLUGIN_INPUT`, checks packaging compatibility for an
`inspect` request, and otherwise emits a bounded guest-action plan. It needs no
network, cloud credentials, platform modules, root privileges, or writable root
filesystem. It runs as UID/GID 65532 and may write only to its bounded `/tmp` mount.
Plugin authors must build images that run under these constraints. Host callers
use `parse_result` with their original input to reject replay and undeclared
targets. Neither a plan nor a compatibility response proves guest readiness.

The RAES GCE and EC2 hosts ask for `validate`, `configure` and `verify` plans before
creating resources. These requests contain declared node identities and OS
families, not realized IP addresses, keys, provider credentials or secret URLs.
Validation cannot contain guest actions; verification must contain at least one.
The host executes configuration and verification against its own guest map and
uses exit status as evidence. Each binding currently targets exactly one guest.
Guest-only cleanup is performed by core range destruction, independently of the
image registry.

An action may request `runtime_values`, a map from local names to closed
`GuestValueReference(binding=..., field=...)` references. Supported fields are
`private_address` and `participant_ssh_public_key`. The host resolves these from
the exact realized guest bindings and supplies bounded base64 JSON in
`SHIFTER_RUNTIME_VALUES_B64` to that guest action. All references are checked
before the first action; participant keys require declared SSH access and a
verified account credential. The management key is never a fallback. The isolated
worker does not receive these values. Guest Python code can use the standard
library-only `shifter_adapter_sdk.guest.read_runtime_values()` helper when the SDK
is installed, or decode the documented JSON transport directly. Treat values as
data rather than interpolating them into shell source.

Other capabilities and runtime input projections require host
support; an author must not assume they are available merely because installation
compatibility passed.

See the repository's external scenario runtime design for supported integration
and remaining extraction work. This source tree is buildable; it is not evidence
that a package release has been published.

## Building SDK candidates

Local wheel builds are sufficient for independent adapter development and runtime
qualification. SDK publication is not a prerequisite. The release and distribution
model, its implementation and author documentation belong to
[issue #2241](https://github.com/Brad-Edwards/shifter/issues/2241).

Pull-request CI retains the tested wheel, source distribution and `SHA256SUMS`
in the `adapter-sdk-candidate-<revision>` artifact. Pack authors can build and test
their adapter against that exact wheel before Shifter merges. Download the
artifact from the successful run for the reviewed revision, verify it with
`sha256sum --check SHA256SUMS`, and install the wheel in an isolated environment.
Record the exact SDK wheel hash with the adapter build inputs and the
registry-resolved worker image digest before live qualification.

### Provisional publishing scaffold

The following scaffold is dormant pending the release-model decision in #2241.
Its presence does not select PyPI as the distribution model or require a release.

The SDK has its own version in `pyproject.toml`, independent of platform release
tags. The `Publish adapter SDK` workflow accepts that exact version from `main`,
runs the SDK checks, builds the wheel and source distribution, and verifies the
built wheel in a fresh environment. Its publishing job downloads the exact build
artifact by ID; it does not check out or rebuild source.

If the agreed model retains this scaffold, configure `shifter-adapter-sdk` with
the GitHub trusted publisher for `Brad-Edwards/shifter`, workflow
`adapter-sdk-release.yml`, environment `adapter-sdk-pypi`. Configure that GitHub
environment's release reviewers and restrict it to `main`. The workflow uses
short-lived OIDC authorization and has no package-index token fallback.

Only after agreeing the release model and merging an approved SDK version,
dispatch the workflow from `main` with
the exact committed version. A successful publication makes
`pip install 'shifter-adapter-sdk[runtime]==<version>'` available to pack authors.
Preparing this workflow does not create the publisher or publish a package.

### Guest model access

A plugin manifest may declare `model_bindings`, mapping workload roles such as
`participant` to names in `required_bindings`. Administrators choose the concrete
guest when assigning the adapter. The declaration does not grant model access:
Engine must separately admit that role's model intent, policy and budget.

For a mapped Linux guest, core enrolls the operation before adapter configuration.
`/run/shifter-model-access/<role>/session.json` contains broker access/refresh
capabilities and public TLS coordinates; it never contains a provider credential.
The sibling `helper.py` is a standalone standard-library program. A client can
obtain a short-lived token with `python3 helper.py token --state /absolute/path/session.json`.
Only this token command writes the credential to stdout, for consumption by the
client's token-helper interface; never log or interpolate its output into a command.

An adapter owns client/container setup. Move or mount the whole state directory
into the client environment, with directory mode 0700, files 0600 and ownership
matching the client's UID. Mounting a single session file breaks atomic refresh.
Keep the directory on tmpfs. Configure the client to use the broker URL and CA,
and disable direct provider authentication. Do not send session contents back to
the isolated worker. Re-enrollment invalidates the old credential family; expiry
or refresh failure must stop client model access.

The current delivery implementation requires trusted private SSH on Linux. It
rejects transports that would persist enrollment in a remote command service.
Client protocol compatibility and both cloud deployments require live qualification.
