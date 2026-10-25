# Authorization policies and groups

Shifter administrators can define reusable authorization groups and policies for a workspace from **Administer → Policies and groups**.

## Concepts

- A **group** collects human or service principals. Adding a service principal uses the same public principal UUID and policy coverage as adding a human.
- A **policy** collects explicit Shifter actions such as workspace read or workspace authorization administration.
- A **policy assignment** attaches a policy to a principal or group.
- A **direct assignment** attaches one action directly to a principal or group.
- A **predefined policy** is a built-in administrator/operator policy with a matching assignment group. The workspace surface provisions the Workspace Administrator display identities; the full catalog also defines installation, account, organization and event administrators.

Every grant and revoke returns an operation state:

- `requested`: Shifter recorded the intent and is applying it.
- `confirmed`: OpenFGA primary-backed readback matches the requested state.
- `denied`: the actor, credential or scope could not delegate the requested authority.
- `unresolved`: the external outcome is uncertain. Shifter blocks a conflicting edit until reconciliation confirms it.

An accepted HTTP request is not itself proof that permission changed. Use the operation status shown by the page. Status refreshes are observational; for a `requested` or `unresolved` operation, use **Reconcile status** to explicitly retry authoritative readback. The UI deliberately does not retry mutations automatically.

If a response is lost before an operation ID reaches the page, use **Retry original command**. The page retains the original destination, payload and idempotency key and locks those inputs until a response is obtained. Retrying recovers the recorded operation rather than creating a conflicting edit.

## Safety rules

Authority can be delegated only within both the signed-in actor's current grant and the admitted credential's exact action ceiling. Shifter rejects self-add, cross-account references, unknown actions, policy/group amplification beyond that ceiling, invalid ancestry and unavailable evaluators. Removing a grant establishes an exclusion fence before deleting the positive relationship, so delayed older work cannot restore a completed revocation.

This feature is the S2 administration slice. Existing Shifter application permission surfaces are migrated in the separate S8 cutover; an old permission check never overrides a denial from this service.
