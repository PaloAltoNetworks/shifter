# ADR-067: Model-access enforcement is optional; keyless-direct is the default; adopt a mature LLM gateway for enforcement

## Status

**Superseded by [ADR-068](068-model-access-broker-parked.md) (2026-10-05).** Its third-party gateway selection and its rejection of a no-limit mode do not reflect the intended default of no controls. ADR-068 parks the broker, keeps keyless-direct as the only live path, and requires any future control path to default to no controls.

Accepted for [#2411](https://github.com/Brad-Edwards/shifter/issues/2411), 2026-09-30,
and relates to the AI Gateway milestone
[#2274](https://github.com/Brad-Edwards/shifter/issues/2274). Supersedes the
mandatory-enforcement posture of ADR-059 (the requirement that model access cross
the broker) and complements ADR-064 (keyless-direct default). The bespoke broker
is retained as a compatibility and opt-in path pending the gateway migration; it
is no longer the strategic enforcement mechanism.

## Context

The deployment-owned "model broker" is, in substance, an LLM gateway built
entirely in-house: a reverse proxy in front of Vertex, Bedrock, Anthropic,
OpenAI, and OpenRouter that authenticates callers, enforces per-caller spend,
rate, concurrency, and token limits, tracks billing, and issues short-lived
rotating credentials, backed by a bespoke control plane, a membership, quota, and
effective-policy engine, and an enrollment and exchange credential protocol.

ADR-059 introduced the broker with enforcement as a requirement: when the broker
is the guest model path, range guests are identity-less and model access crosses
the broker only. ADR-064 restored keyless Workload Identity direct access as the
default (model access reachable without the broker) and deferred a turnkey
enforcement path to the AI Gateway milestone (#2274).

Operating the bespoke broker has proven high-friction. Mandatory enforcement
couples in a membership projection, an approximately five-minute membership
freshness window that capped credential lifetime below the time a GCE range needs
to boot and enroll, an enrollment and exchange handshake, quota-observation
seeding that is not wired into the runtime, and per-event sharing bindings. None
of that is intrinsic to letting a range call a model. It is intrinsic to metering
every call under a hand-rolled per-subject authorization system.

Two conclusions follow. First, the original intent of the broker was to offer the
capability to enforce controls (and later detections), not to require enforcement
on every deployment; the mandatory posture, together with a bespoke zero-trust
rotating-credential model, is the source of the friction. Second, LLM gateways are
a mature product category, and building one from scratch reinvented budget,
rate-limit, multi-provider, and observability capabilities that mature,
self-hostable projects already provide.

## Decision

1. Model-access enforcement (spend, rate, and request metering, and future
   detections) is an optional capability, not a requirement. No deployment must
   run an enforcing gateway to give ranges model access.
2. Keyless Workload Identity direct access (ADR-064) is the default operating path
   for all ranges, including CTF ranges. Ranges reach approved models through the
   keyless, least-privilege, predict-only identity unless a deployment opts into
   enforcement.
3. The bespoke broker is not the strategic enforcement mechanism. Further
   investment in hardening its mandatory-enforcement, freshness, and membership
   machinery stops. It is retained only as a compatibility and opt-in path until
   the gateway migration lands.
4. The strategic optional-enforcement path is a mature, self-hosted LLM gateway,
   with LiteLLM as the primary evaluation candidate, adopted under #2411 as part
   of the AI Gateway milestone (#2274). Enforcement is off by default and opt-in
   where budgets, rate limits, or detections are wanted.

## Alternatives

| Alternative | Disposition |
| --- | --- |
| Keep the bespoke broker as the required model-access path | Reject. Mandatory enforcement plus bespoke zero-trust credentials block basic flows (GCE provisioning exceeds the freshness window; capacity, enrollment, and bindings are not turnkey) and reinvent a mature category. |
| Keep the broker but make enforcement optional (fix credential lifetime, add a no-limit mode) | Partial. Unblocks the short term but keeps the bespoke complexity permanently. Superseded by adopting a mature gateway. |
| Adopt a mature LLM gateway for optional enforcement, keyless-direct as the default | Selected. Matches ADR-064 and the AI Gateway milestone, avoids reinventing a mature category, and restores the capability-not-requirement intent. |

## Consequences

CTF and standard ranges reach approved models by default through keyless Workload
Identity, with no broker on the path and none of its provisioning friction. A
compromised guest can call approved models under a least-privilege, predict-only
identity; direct-path invocations are not subject to spend or rate enforcement, so
a deployment that requires that enforcement opts into the gateway. Project-level
quotas and budgets bound the direct-path blast radius in the meantime.

The bespoke broker, its control plane, and the sharing, quota, and
effective-policy subsystems enter maintenance. The credential-lifetime fix (the
credential now lives for the range session rather than the membership freshness
window) remains valid for any deployment still running the broker during the
transition.

The gateway credential model is decided in #2411: mature gateways use scoped,
revocable virtual API keys, whereas the broker used rotating, subnet-bound tokens.
The direct-path default preserves a zero-trust posture through keyless Workload
Identity and least privilege regardless of that choice.
