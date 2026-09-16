# Range Instantiation Policy

Which range backend may realize a range, for which kind of launch.

Normal Shifter scenarios are live-fire: participants and agents run arbitrary
commands, exploit services, pivot, and attempt escape. ADR-030 decides that a
live-fire range must be contained by an approved boundary outside the Kubernetes
management plane, and that the retained Kubernetes/GDC plumbing may serve only
explicitly declared non-user modes. This policy is the control that enforces
that decision.

The policy lives in one Django-free module,
`shifter/shifter_platform/shared/range_instantiation_policy.py`, imported by
CMS, the Engine, and the standalone provisioner.

## The model

Three concepts, deliberately kept separate:

| Concept | What it is | What it is not |
|---|---|---|
| **Backend** | The substrate a range realizes on (`gce`, `gdc`), selected per deployment by `GCP_RANGE_BACKEND` | Not permission to use that substrate |
| **Purpose** | Trusted workflow authority describing what kind of launch this is | Not derived from provenance, scenario, role, or environment |
| **Admission** | The policy decision that this backend may serve this purpose | Not realizability, and not event-readiness evidence |

### Purposes

`InstantiationPurpose` is a closed set.

| Purpose | Meaning |
|---|---|
| `live_fire` | Every normal Mission Control and CTF range. The default. |
| `non_user_demo` | Deterministic product demo or breach-and-attack simulation. No participant workload. |
| `operator_validation` | Operator-run or image-build validation of the substrate itself. |
| `non_user_validation` | Legacy undifferentiated non-user value from issue #1348, retained so rows already persisted under it keep parsing. New workflows must not mint it. |

A purpose is server-derived trusted authority, exactly like `RangeSource`. It is
**never** inferred from `RangeSource`, a scenario's `scenario_type`, the user's
role, `ENVIRONMENT`, a feature flag, or the backend selector (ADR-030-R6). In
particular, an ordinary Mission Control demo scenario is still `live_fire`—the
user can execute arbitrary activity in it.

There is no request field, serializer field, query parameter, scenario YAML key,
`RangeSpec` field, or RAES plan field that carries a purpose. It cannot be
requested from outside the platform.

### Who can mint a non-user purpose

The generic product facades—`create_range`, `create_range_dispatch`, and
`create_raes_native_range`—take no instantiation-purpose argument at all. They
are permanently live-fire, so no in-process caller can escalate a normal launch
onto the retained substrate.

The only path to a non-user purpose is `cms.services.create_non_user_range`. It
requires operator authority on the calling user, then *derives* the purpose from
a declared `NonUserWorkflow` rather than accepting one:

| Workflow | Minted purpose |
|---|---|
| `product_demo` | `non_user_demo` |
| `breach_attack_simulation` | `non_user_demo` |
| `operator_validation` | `operator_validation` |
| `image_validation` | `operator_validation` |

Adding a workflow requires an explicit entry in that map. There is no default,
and no HTTP surface reaches the function.

### The backend registry

`RANGE_BACKENDS` is the single registration surface. Each entry names a backend
and enumerates the purposes it may serve.

| Backend | Provider | Permitted purposes |
|---|---|---|
| `gce` | `gcp` | `live_fire`, `non_user_demo`, `operator_validation`, `non_user_validation` |
| `gdc` | `gcp` | `non_user_demo`, `operator_validation`, `non_user_validation` |

Registration is **default-deny**. A backend admits only the purposes its entry
lists, enumerated one by one—never derived from every enum member, which would
silently admit every future purpose. A backend registered with an empty set can
launch nothing. The selector parser derives its valid values from this same
mapping, so an unregistered slug is unparseable and therefore unselectable.

`gdc` never permits `live_fire`. That is the ADR-030 decision expressed as data.

## Where it is enforced

Four layers, each independent:

1. **CMS service boundary**—`cms.services._range_backend_admission.assert_backend_admitted()`
   runs before the active-range reservation, Engine persistence, launch-intent
   creation, subnet allocation, secret access, or any cloud mutation. Both the
   cyberscript (`create_range`) and RAES (`create_raes_native_range`) create
   paths call it, so every product entry point funnels through one check. A CTF
   launch is additionally refused any non-live-fire purpose outright, and the
   operator gate on `create_non_user_range` runs before a purpose exists at all.
2. **Engine persistence**—`engine.services._range_backend_binding` re-evaluates
   the admitted pair before writing it to the write-once `Range.range_backend` /
   `Range.instantiation_purpose` columns. `BackendAdmission` is a constructible
   dataclass, so `admitted=True` from an arbitrary in-process caller is not by
   itself authority.
3. **Provisioner defense in depth**—`range_terraform_runner.apply_range()`
   evaluates the policy again before any GDC apply call. The purpose comes from
   the locked Engine row projected by `provisioner_db`, never from argv, the Job
   environment, or scenario content. A provision whose persisted binding no
   longer matches the deploy selector fails closed rather than re-routing.
4. **Adapter availability**—policy approval is not adapter support. RAES-native
   provisioning realizes GCE range cells only, so an RAES launch on any other
   admitted backend fails with `unsupported-capability` before dispatch.

Teardown is deliberately **not** gated by new-provision policy. An existing GDC
range is destroyed from its persisted ownership binding even though new
live-fire provisioning on that backend is forbidden; refusing cleanup would
strand billable resources.

## Failure codes

Denials carry a stable ADR-039 classification so retry and notification paths do
not parse prose.

| Code | Meaning | Retryable |
|---|---|---|
| `identity-or-policy` | The backend is not admitted for this purpose | No—permanent |
| `prerequisite` | The selector or persisted binding is missing, malformed, or no longer matches what was admitted | After operator correction |
| `unsupported-capability` | Policy permits the backend but no realization adapter exists | No |
| `conflict` | An idempotent re-create carries a different binding than the persisted one | No |

Denial messages name the denied pair and the backend's registered scope, so
deterministic demo infrastructure is never mistaken for the approved live-fire
backend (ADR-030-R3). They contain no configuration values, secrets, or raw
exception text.

## Registering a new range backend

Add the backend to `RANGE_BACKENDS` in
`shifter/shifter_platform/shared/range_instantiation_policy.py` with a stable
slug, its provider, and an explicit permitted-purpose set. Start with an empty
set—a backend is registered before it is approved.

Then:

- extend the selector normalization path for that provider, without changing the
  default away from an approved live-fire backend;
- implement the backend behind the existing range lifecycle router and satisfy
  ADR-039 lifecycle, error, and ownership conformance;
- for a `live_fire` allow, produce the ADR-030-R5 escape-validation evidence
  first—successful boot, network uniqueness, or namespace isolation is not
  containment evidence;
- advertise and check its realization capability separately, including legacy
  versus RAES support;
- persist and route from the same Engine binding; and
- add policy-matrix, service-boundary, Engine-binding, provisioner
  defense-in-depth, and cleanup tests.

A new **cloud provider** additionally belongs in
`installation.registry.BACKEND_BUNDLES`. A new **substrate within an existing
provider** does not—that registry selects deployment bundles, not per-range
realization.

## Related docs

- [GDC Provisioning](gdc-provisioning) - the retained non-user substrate
- [GCP Infrastructure](gcp-infrastructure) - GKE, Helm, and GCP services
- `docs/architecture/range-instantiation-policy-control-preflight-1354.md` - design rationale
- `docs/architecture/range-isolation-model.md` - containment model
