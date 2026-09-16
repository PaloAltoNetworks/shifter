# Per-range model access: planned behavior

This feature is being designed under
[#681](https://github.com/Brad-Edwards/shifter/issues/681). The general
capability described here is not yet available. Existing scenario-specific
model setup is not evidence that these controls are implemented.

An enabled scenario will request an approved model profile for each range.
The platform will allocate model capacity and configure the participant's
tool automatically. Participants will not need cloud accounts or provider
keys. Model use will consume explicit request, time and spend budgets.

An event organizer will select from profiles made available by the deployment
operator, declare the expected cohort and spare ranges, choose a permitted
allocation strategy and set limits within the delegated budget. The event
assessment will show whether the planned access is available before launch.
Organizers cannot add arbitrary models, accounts or external destinations.

Operators will choose which ranges share resources: selected CTF ranges,
an event or cohort, a user's ranges, a group's ranges, a named collection,
or all ranges in the deployment. They can share some or all of the provider
accounts, model assignments, capacity, spend, rate and concurrency allowances.
For example, all ranges can use one provider account with separate budgets,
or a user's ranges across several events can draw from one pooled budget.
The main and small model can have different sharing choices.

Collections can use a fixed membership snapshot or include future eligible
ranges automatically. A preview will show overlapping policies, pooled
balances and individual limits before publication. Hard limits still apply
across overlaps. Each range keeps separate access credentials, so revoking
one range need not interrupt others using the same shared resources.

A participant will see whether model access is ready, unavailable, suspended
or exhausted, along with an actionable reason and remaining permitted time
or usage where policy allows. A scenario requiring model access will not be
reported ready when that access failed. An explicitly optional capability
can be unavailable without stopping the rest of the range.

Pause, reset, expiry, event stop and access revocation will withdraw the old
model capability. Resume will check permission and remaining budget again;
it will not reset spend. A provider outage can interrupt a response. The
platform will not promise to resume a partially delivered response or repeat
a potentially billable request automatically.

Operators will manage approved provider projects/accounts, model aliases,
data regions, hard ceilings and allocation health. Usage and audit views
will contain metadata and amounts, not prompts or responses. Provider data
handling still applies to content sent to the selected model.

GCP/Vertex is the first planned release. Other model providers and external
tool APIs will appear only after their adapters and security evidence are
qualified. Access to a model does not grant access to platform administration
or privileged operator tools.

See the [design](https://github.com/Brad-Edwards/shifter/blob/dev/docs/architecture/model-access/index.md) and
[operations plan](../ops/model-access.md) for implementation and release scope.
