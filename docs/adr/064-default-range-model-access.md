# ADR-064: Range guests get default-on, keyless model access

## Status

Accepted for [#2275](https://github.com/Brad-Edwards/shifter/issues/2275),
2026-09-19. Supersedes ADR-059's "no-service-account guest default" decision
(ADR-059-R3) for GCP. Restores the default-on model-access enablement removed
by the ADR-059 direct guest-credential retirement, without reintroducing
guest-held provider keys.

## Context

ADR-059 introduced the deployment-owned model broker and, in migration, retired
the direct guest model-access path: the range guest Vertex service-account role
and the AWS guest Bedrock authority were removed, and both GCE plan builders set
`attach_service_account: False`.

The broker is the right control where mandatory spend, rate and request
enforcement is required, but it is not turnkey. Enabling it requires
operator-supplied TLS (broker and control secrets), a CA trust bundle, a private
VIP and DNS hostname, a KMS fingerprint signing key, a v3 priced catalog, and a
provider inventory, and it is disabled by default. The net effect of the
retirement was that a fresh tenant has **no** model access at all until a
heavyweight broker bring-up is completed, and range model-access *enablement*
became coupled to whether a specific scenario declared a model need.

That coupling is wrong. Whether a scenario uses a model is independent of whether
a deployment's ranges are *able* to reach one. Most deployments expect their own
project's Vertex (or AWS Bedrock) to be reachable by ranges by default, with only
per-model enablement in the provider console left as a manual step, the posture
that existed before the retirement.

## Decision

Range guests receive a **default-on, keyless** model-invocation identity,
decoupled from scenario model-need.

On GCP, the range host service account carries a predict-only Vertex custom role
(`aiplatform.endpoints.predict`) in the platform project (same-project by
default), and the provisioner attaches it to range guests through Workload
Identity. The guest obtains short-lived tokens from the metadata server; **no key
material is created, minted, or delivered to the guest.** This resolves the
original ADR-059 concern (Vertex keys placed in the guest, many keys
authenticating one principal) while restoring reachability.
`aiplatform.googleapis.com` is enabled by default. Enabling a specific model (for
example Claude in Vertex Model Garden) remains the only manual, provider-console
step.

On AWS, the range instance role mirrors this with default-on Bedrock invoke
(`bedrock:InvokeModel`, `bedrock:InvokeModelWithResponseStream`); enabling a
specific model in the Bedrock console remains manual. AWS is delivered
separately and requires its own qualification, per ADR-059.

Direct default-on access and the ADR-059 broker are **mutually exclusive per
range**. When the broker is the guest model path (`MODEL_BROKER_GUEST_VIP` set),
the provisioner leaves guests identity-less and model access crosses the broker
only, preserving its source-preserving keyless isolated egress. When no broker
guest path is configured, the keyless guest identity is attached.

## Alternatives

| Alternative | Disposition |
| --- | --- |
| Keep model access broker-only, off by default | Reject: leaves every fresh tenant with no model access and couples enablement to a heavyweight per-tenant TLS/DNS/KMS/catalog bring-up. |
| Restore per-range Vertex **keys** (the retired path) | Reject: reintroduces guest-held key material and the 10-key-per-principal / 24-slot limit. Keyless Workload Identity attachment gives the same reachability without keys. |
| Make the broker turnkey and default-on | Not selected now: the broker's required TLS, CA, VIP/DNS, fingerprint KMS and priced catalog cannot be sensibly auto-defaulted. The strategic turnkey path is the AI-gateway work (milestone: AI Gateway, [#2274](https://github.com/Brad-Edwards/shifter/issues/2274)). |

## Consequences

Range guests reach approved models by default with no key material and least
privilege (predict-only invocation plus telemetry writes). A compromised guest
can call approved models directly under this identity: direct-path invocations
are **not** subject to the broker's mandatory request/spend/rate enforcement.
Deployments that require that enforcement enable the broker, which switches
ranges to the mediated, identity-less path. This is the deliberate tradeoff:
reachable by default for the common case, broker-mediated where enforcement is
required.

Network reachability (Private Google Access or external egress) is the operator's
unchanged range egress posture and is orthogonal to identity: the old key path
needed the same reachability.

The workload IAM scope guard is unchanged. The range host identity still holds no
project storage or secret roles; only predict-only model invocation and
logging/monitoring writes are added, so participant-reachable guests gain no
project storage, secret, or cross-tenant access.

## Audit telemetry clarification (#2535)

The [GCP range telemetry preflight](../architecture/gcp-range-audit-telemetry-preflight-2535.md)
records the intended default-on network and Vertex Data Access logging boundary.
Provider audit configuration belongs to deployment Terraform in the model target
project; guest subnet/NAT settings belong to their existing infrastructure owner.
Logging grants no new guest model permission, project IAM authority or log-read
access, and does not enforce spending or identify a human behind a shared guest
principal. Cloud Logging routing/retention remains project-operator policy.
The broker stays parked under ADR-068. This clarification is design guidance;
rendered configuration and live record evidence remain #2535 delivery work.
