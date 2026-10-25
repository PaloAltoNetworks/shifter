# Model sources for scenarios and CTFs

Current support: [ADR-068](../adr/068-model-access-broker-parked.md) parks the
broker and its controls. Keyless-direct is the supported guest model path.
The broker-dependent user flows below describe retained implementation, not an
available supported service. The
[replacement evaluation](../architecture/model-access/gateway-replacement-evaluation-2274.md)
records the selected LiteLLM OSS replacement with deployment-owned rotation;
it does not enable these controls.

A model source connects an approved model to an account that pays for its use.
It is independent of where the range or Shifter runs. A Vertex source may use
Shifter's own GCP project, another GCP project, or a model account elsewhere.
The broker handles provider authentication; participants receive only scoped,
revocable access for their range.

These controls require an enabled model broker and an approved scenario model
profile. A source marked **Configured** has been stored successfully; that label
is not a live provider test or a guarantee of quota. Deployment qualification
is tracked separately in the [operations guide](../ops/model-access.md).

## Connect a source

Organization administrators open **Administer → Model sources**, choose an
organization, and select **Add model source**. Choose the provider, model and
account identity, then enter the context limit, application token ceiling,
prices and price expiry. Cloud sources also require their explicit region and
invocation identity. Workload identity uses the broker's approved cloud grants;
otherwise supply a provider credential in the form. Secrets are write-only and
are cleared after every attempted submission. An edit without new credentials
retains the current credential.

Source registration does not give anyone permission to spend. Explicitly allow
organization members or select individual users. A source is selectable only
while the user also belongs to that tenant. Administering sources and being
allowed to use their funds are separate permissions.

| Source | Configuration and behavior |
| --- | --- |
| Vertex | Approved project, service account, model, invocation region and counting region. The platform project is a valid choice. |
| Bedrock | Approved AWS invocation role, model and region. The hosting cloud need not be AWS. |
| Direct Anthropic | API key and pinned model at the provider's fixed API origin. |
| OpenAI | API key and pinned model; the broker translates the supported text and local-tool protocol to Responses. |
| OpenRouter | API key, model and one explicit upstream provider; automatic provider fallback is disabled. |

Direct API sources use **provider-managed** geography; they do not promise a
cloud region. Both deployment policy and the scenario must allow that geography.
OpenRouter does not expose token counting through this integration. It requires
a scenario input allowance covering the source's full context window; scenarios
requiring token counting cannot use it. Unsupported choices are omitted from the
scenario picker. Hosted provider tools, arbitrary API URLs and platform
administration tools are not granted by selecting a model source.

The token ceiling is an application limit, not purchased provider quota.
Sources using the same cloud account and region share capacity accounting;
renaming them does not create capacity. For direct providers, use the same quota
identity for sources that share a provider quota. Prices use micro-units of the
selected currency per million tokens. A zero price explicitly means no monetary
charge is reserved for that component; it does not disable token or rate limits.
An expired price prevents new admission.

## Choose sources at launch

Select a workspace and scenario in the range launch form. For each model alias,
keep the deployment default or select an authorized source. Where the scenario
and deployment allow weighted allocation, select several sources and their
relative weights. For example, weights 2 and 1 express a preferred two-to-one
distribution across many allocations, not an exact participant count.

Allocation checks capacity and policy before launch. Source choices do not
replace shared event/user budgets, per-range limits, allowed regions or provider
pool restrictions. A retry preserves the original launch intent. The broker
never retries a potentially billed request on another source automatically.

## Configure a CTF

The event create/edit form provides the same model-source picker. An organizer
with event configuration permission and source-use authority selects sources
for the event's aliases. Participants use this event sponsorship without
receiving the organizer's credentials or source administration permission.
If no explicit model-demand declaration is supplied, admission derives it from
the scenario's verified needs and the event's participant ceiling.

With independent weighted routing, the event reserves capacity across the
selected accounts in proportion to their weights, rounded to whole participants.
Every account's share must fit before the first launch. Accounts sharing the
same provider quota still count against that single limit. A policy that keeps
the whole group on one source requires that source to support the whole group.

Changing event defaults applies to subsequent preparation and fences affected
authority. It does not silently rewrite allocations already running. Use the
range administration controls for explicit changes to existing ranges. The
event's workspace remains fixed after creation.

The event detail page shows a **model-access capacity** summary: the assessed
outcome, whether it blocks admission, and bounded reason codes. This is planning
information only—raw quotas, usage figures and account identifiers stay
operator-only, and an unavailable assessment is shown as such rather than as a
positive decision.

## Share model access across ranges

Operators and organizers open **Administer → Model-access sharing** to share a
model profile, provider identity, capacity or budget across more than one range.
Choose separately *which ranges* a binding covers—explicit ranges, an
event/cohort/team, a user's ranges, a group, workspace or organization, a named
collection, or (operators only) every range—and *which facets* to share. Each
unshared facet stays per-range. Membership can be a fixed snapshot or dynamic.

Preview reports the matched ranges before anything is published; the effective
policy preview shows overlapping bindings, their revisions and any priority
conflict for a range. Publishing compares an expected definition revision: if the
binding changed since it was loaded, the save is rejected and the form asks for a
reload. Publication re-resolves membership and authority on the server, records
the real publisher, and issues a distinct revocable grant per range—sharing a
provider account never hands every participant the same token. Draining a binding
stops new use and advances its fence; it never refunds spend, resets an account
or cancels a billable request.

These controls express configurations such as:

| Intent | Result |
| --- | --- |
| Every range uses one provider account, with individual spend limits | Shared provider identity; per-range spend accounting. |
| A set of ranges shares everything | One profile, shared assignment, provider identity, capacity and spend/rate/concurrency; distinct revocable grants. |
| One user's ranges share a budget across two events | One persistent user budget applies to every qualifying range; each event's own limits also apply. |
| A group shares its main model but keeps separate small-model budgets | Shared assignment for the main alias; per-range assignment and budget for the small alias. |
| A cohort shares capacity and spend, with individual concurrency caps | One cohort capacity/spend pool plus separate concurrency ceilings. |
| Two events share a model pool but keep their own budgets | Both bindings reference the same routing/provider pool; each event's budget stays distinct. |

Publishing a binding requires authority over the whole selection; it never grants
new IAM, event or workspace authority, and it cannot fund a group the publisher
does not already control.

## What participants see

A participant's range page shows only its own model access: an availability state
(active, refreshing, or not available) and the logical model aliases the range
may use. It never shows provider or account identifiers, regions, source
coordinates, rosters, other members' usage, or shared-pool balances.

## Change an existing range

Under **Model sources → Range model sources**, choose the range and edit its
assignments. Save compares the revision displayed in the form; if another
administrator changed it, reload before trying again.

The change revokes old grants before attempting replacement admission. Existing
spend and unresolved provider charges remain. A successful admission reports
refresh pending until the guest exchanges its refresh credential. It keeps the
original range operation and hard expiry. If admission fails, the range remains
blocked and the page displays the reason; retry after correcting the source or
capacity. Failure does not reactivate the old grant.

**Revoke model access** fences the range's current grants and dispatch leases
without changing its source selection. It is the immediate control when access
must stop. Revocation records the acting administrator, and outstanding usage and
unresolved charges stay accounted for under their original prices; it does not
refund spend or prove the provider stopped a request already in flight.
Re-enrolment is the ordinary source change (renew) above, which delivers a fresh
grant to the guest over the range's existing operation path—a credential is
never returned to the browser.

Disabling or rotating a source fences dependent grants too. **Retire unused
credentials** deletes obsolete stored versions only after the grace period and
when no active allocation or unresolved usage needs them. Current credentials
remain, including for a disabled source that may be re-enabled. Failed cleanup
can be retried from the same tenant page.

For identity, accounting and provider extension details, see
[tenant source management](../architecture/model-access/source-management.md).
