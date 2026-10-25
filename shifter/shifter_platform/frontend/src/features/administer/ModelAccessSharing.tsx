import { useState } from "react";

import { describeMutationError } from "@/api/errors";
import {
  drainBinding,
  previewEffectivePolicy,
  previewSelector,
  publishBinding,
  validateBinding,
  type BindingRevision,
  type EffectivePolicyPreview,
  type SelectorPreview,
} from "@/api/model-access";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";

/** Which ranges a binding covers. */
const SELECTOR_KINDS = [
  "all_ranges",
  "selected_ranges",
  "ctf_event",
  "ctf_cohort",
  "ctf_team",
  "user",
  "auth_group",
  "workspace",
  "organization",
] as const;

/** Which facets are shared. Unchecked facets stay per-range/individual. */
const FACETS = ["profile", "provider_identity", "routing", "capacity", "spend", "rate", "concurrency"] as const;

type SelectorKind = (typeof SELECTOR_KINDS)[number];
type FacetName = (typeof FACETS)[number];
type FacetState = Record<FacetName, boolean>;

const EMPTY_FACETS: FacetState = {
  profile: false,
  provider_identity: false,
  routing: false,
  capacity: false,
  spend: false,
  rate: false,
  concurrency: false,
};

function splitIds(value: string): string[] {
  return value
    .split(/[\s,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

/** Compose state (which ranges / which facets) and the request payload builders. */
function useSharingForm() {
  const [kind, setKind] = useState<SelectorKind>("all_ranges");
  const [ids, setIds] = useState("");
  const [includeSpares, setIncludeSpares] = useState(false);
  const [facets, setFacets] = useState<FacetState>(EMPTY_FACETS);
  const [membershipMode, setMembershipMode] = useState<"snapshot" | "dynamic">("dynamic");
  const [bindingId, setBindingId] = useState("");
  const [poolId, setPoolId] = useState("");
  const [profileId, setProfileId] = useState("");
  const [priority, setPriority] = useState(0);
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [effectiveUntil, setEffectiveUntil] = useState("");
  const [routingRevision, setRoutingRevision] = useState(1);
  const [providerPoolRef, setProviderPoolRef] = useState("");
  const [spendAccount, setSpendAccount] = useState("");
  const [expectedRevision, setExpectedRevision] = useState(0);

  const selectorPayload = () => ({ kind, ids: splitIds(ids), include_spares: includeSpares });
  const bindingPayload = () => ({
    sharing_binding_id: bindingId,
    selector: selectorPayload(),
    membership_mode: membershipMode,
    profile_id: profileId || null,
    sharing_pool_id: poolId,
    facets: FACETS.filter((facet) => facets[facet]),
    priority,
    effective_from: effectiveFrom,
    effective_until: effectiveUntil,
  });
  const poolPayload = () => ({
    sharing_pool_id: poolId,
    routing_revision: routingRevision,
    provider_pool_ref: providerPoolRef || null,
    spend_account_refs: spendAccount ? [spendAccount] : [],
  });

  return {
    kind, setKind, ids, setIds, includeSpares, setIncludeSpares, facets, setFacets, membershipMode, setMembershipMode,
    bindingId, setBindingId, poolId, setPoolId, profileId, setProfileId, priority, setPriority,
    effectiveFrom, setEffectiveFrom, effectiveUntil, setEffectiveUntil, routingRevision, setRoutingRevision,
    providerPoolRef, setProviderPoolRef, spendAccount, setSpendAccount, expectedRevision, setExpectedRevision,
    selectorPayload, bindingPayload, poolPayload,
  };
}

type SharingForm = ReturnType<typeof useSharingForm>;

/**
 * The sharing actions (preview / validate / policy-preview / publish / drain).
 *
 * Each resolves server-side; a stale (409) publish/drain sets the reload prompt.
 */
function useSharingActions(form: SharingForm) {
  const [subjectRef, setSubjectRef] = useState("");
  const [preview, setPreview] = useState<SelectorPreview | null>(null);
  const [valid, setValid] = useState<boolean | null>(null);
  const [policy, setPolicy] = useState<EffectivePolicyPreview | null>(null);
  const [revision, setRevision] = useState<BindingRevision | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [stale, setStale] = useState(false);
  const [pending, setPending] = useState(false);

  function fail(error_: unknown) {
    if ((error_ as { status?: number })?.status === 409) setStale(true);
    else setError(error_);
  }

  async function run(action: () => Promise<void>) {
    setError(null);
    setStale(false);
    setPending(true);
    try {
      await action();
    } catch (error_) {
      fail(error_);
    } finally {
      setPending(false);
    }
  }

  const runPreview = () =>
    run(async () => {
      setPreview(null);
      setPreview(await previewSelector(form.selectorPayload()));
    });
  const runValidate = () =>
    run(async () => {
      setValid(null);
      try {
        await validateBinding(form.bindingPayload(), form.poolPayload());
        setValid(true);
      } catch (error_) {
        setValid(false);
        throw error_;
      }
    });
  const runPolicyPreview = () =>
    run(async () => {
      setPolicy(null);
      setPolicy(await previewEffectivePolicy({ owner: "deployment", reference: subjectRef }));
    });
  const runPublish = () =>
    run(async () => {
      setRevision(null);
      setRevision(await publishBinding(form.bindingPayload(), form.poolPayload(), form.expectedRevision));
    });
  const runDrain = () =>
    run(async () => {
      setRevision(null);
      setRevision(await drainBinding(form.bindingId, form.expectedRevision));
    });

  return {
    subjectRef, setSubjectRef, preview, valid, policy, revision, error, stale, pending,
    runPreview, runValidate, runPolicyPreview, runPublish, runDrain,
  };
}

/** Advisory effective-policy preview: overlapping bindings, conflicts, facets. */
function PolicyPreviewResult({ policy }: Readonly<{ policy: EffectivePolicyPreview }>) {
  return (
    <div className="space-y-1 text-sm">
      <p>
        {policy.is_admissible ? "Admissible" : "Not admissible"}
        {policy.stale ? " · stale membership" : ""}.
      </p>
      {policy.conflicts.length ? (
        <p role="alert">Priority conflicts: {policy.conflicts.map((conflict) => conflict.code).join(", ")}.</p>
      ) : (
        <p>No priority conflicts.</p>
      )}
      <ul className="list-disc pl-5">
        {policy.contributions.map((contribution) => (
          <li key={contribution.sharing_binding_id}>
            <span>{contribution.sharing_binding_id}</span> (revision {contribution.membership_revision}, priority{" "}
            {contribution.priority}): {contribution.facets.join(", ")}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Operator/organizer model-access sharing management (M09, #2126 / PLAT-202).
 *
 * Compose which ranges and which facets to share, preview the matched members and
 * effective-policy conflicts, then validate, publish or drain a binding under an
 * optimistic definition-revision fence. Publication re-resolves membership and
 * authority server-side; a stale revision returns 409 and requires a reload. The
 * six sharing.md examples are expressed as combinations of these controls.
 */
export function ModelAccessSharing() {
  const form = useSharingForm();
  const actions = useSharingActions(form);
  const f = { ...form, ...actions };
  return (
    <section className="space-y-6" aria-labelledby="model-access-sharing-heading">
      <PageHeader
        title="Model-access sharing"
        description="Share model profiles, provider identity, capacity and budgets across selected ranges, users, groups or collections."
      />
      <h2 id="model-access-sharing-heading" className="sr-only">
        Model-access sharing
      </h2>

      {f.stale ? (
        <Alert variant="destructive">
          <AlertDescription role="alert">Definition changed. Reload this binding before saving.</AlertDescription>
        </Alert>
      ) : null}
      {f.error ? (
        <Alert variant="destructive">
          <AlertDescription role="alert">
            {describeMutationError(f.error, "The sharing request could not be completed.")}
          </AlertDescription>
        </Alert>
      ) : null}

      <fieldset className="space-y-3">
        <legend className="font-medium">Which ranges</legend>
        <Label htmlFor="selector-kind">Scope</Label>
        <select
          id="selector-kind"
          className="block rounded border bg-background p-2"
          value={f.kind}
          onChange={(event) => f.setKind(event.target.value as SelectorKind)}
        >
          {SELECTOR_KINDS.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
        {f.kind === "all_ranges" ? null : (
          <>
            <Label htmlFor="selector-ids">Identifiers (comma or space separated)</Label>
            <textarea
              id="selector-ids"
              className="block w-full rounded border bg-background p-2"
              value={f.ids}
              onChange={(event) => f.setIds(event.target.value)}
            />
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={f.includeSpares} onChange={(event) => f.setIncludeSpares(event.target.checked)} />
              <span>Include spare ranges</span>
            </label>
          </>
        )}
      </fieldset>

      <fieldset className="space-y-2">
        <legend className="font-medium">Which facets to share</legend>
        {FACETS.map((facet) => (
          <label key={facet} className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={f.facets[facet]}
              onChange={(event) => f.setFacets({ ...f.facets, [facet]: event.target.checked })}
            />
            <span>{facet}</span>
          </label>
        ))}
        <Label htmlFor="membership-mode">Membership</Label>
        <select
          id="membership-mode"
          className="block rounded border bg-background p-2"
          value={f.membershipMode}
          onChange={(event) => f.setMembershipMode(event.target.value as "snapshot" | "dynamic")}
        >
          <option value="dynamic">dynamic</option>
          <option value="snapshot">snapshot</option>
        </select>
      </fieldset>

      <div>
        <Button type="button" onClick={f.runPreview} disabled={f.pending}>
          Preview matched ranges
        </Button>
        {f.preview ? (
          <output className="mt-2 block">
            Matched {f.preview.matched} range{f.preview.matched === 1 ? "" : "s"}.
          </output>
        ) : null}
      </div>

      <div>
        <Button type="button" onClick={f.runValidate} disabled={f.pending || !f.bindingId || !f.poolId}>
          Validate draft
        </Button>
        {f.valid === true ? <output className="mt-2 block">Draft is valid.</output> : null}
        {f.valid === false ? (
          <p role="alert" className="mt-2 text-sm">
            Draft is not valid. Correct the fields and retry.
          </p>
        ) : null}
      </div>

      <fieldset className="space-y-3">
        <legend className="font-medium">Preview effective policy for a range</legend>
        <Label htmlFor="subject-ref">Range reference</Label>
        <input
          id="subject-ref"
          className="block rounded border bg-background p-2"
          value={f.subjectRef}
          onChange={(event) => f.setSubjectRef(event.target.value)}
        />
        <Button type="button" onClick={f.runPolicyPreview} disabled={f.pending || !f.subjectRef}>
          Preview effective policy
        </Button>
        {f.policy ? <PolicyPreviewResult policy={f.policy} /> : null}
      </fieldset>

      <fieldset className="space-y-3">
        <legend className="font-medium">Publish</legend>
        <Label htmlFor="binding-id">Binding ID</Label>
        <input id="binding-id" className="block rounded border bg-background p-2" value={f.bindingId} onChange={(event) => f.setBindingId(event.target.value)} />
        <Label htmlFor="pool-id">Pool ID</Label>
        <input id="pool-id" className="block rounded border bg-background p-2" value={f.poolId} onChange={(event) => f.setPoolId(event.target.value)} />
        <Label htmlFor="profile-id">Profile (optional)</Label>
        <input id="profile-id" className="block rounded border bg-background p-2" value={f.profileId} onChange={(event) => f.setProfileId(event.target.value)} />
        <Label htmlFor="provider-pool-ref">Shared provider account (optional)</Label>
        <input id="provider-pool-ref" className="block rounded border bg-background p-2" value={f.providerPoolRef} onChange={(event) => f.setProviderPoolRef(event.target.value)} />
        <Label htmlFor="spend-account">Shared spend account (optional)</Label>
        <input id="spend-account" className="block rounded border bg-background p-2" value={f.spendAccount} onChange={(event) => f.setSpendAccount(event.target.value)} />
        <Label htmlFor="priority">Priority</Label>
        <input id="priority" type="number" className="block rounded border bg-background p-2" value={f.priority} onChange={(event) => f.setPriority(Number(event.target.value))} />
        <Label htmlFor="routing-revision">Routing revision</Label>
        <input id="routing-revision" type="number" className="block rounded border bg-background p-2" value={f.routingRevision} onChange={(event) => f.setRoutingRevision(Number(event.target.value))} />
        <Label htmlFor="effective-from">Effective from</Label>
        <input id="effective-from" className="block rounded border bg-background p-2" value={f.effectiveFrom} onChange={(event) => f.setEffectiveFrom(event.target.value)} />
        <Label htmlFor="effective-until">Effective until</Label>
        <input id="effective-until" className="block rounded border bg-background p-2" value={f.effectiveUntil} onChange={(event) => f.setEffectiveUntil(event.target.value)} />
        <Label htmlFor="expected-revision">Expected definition revision</Label>
        <input id="expected-revision" type="number" className="block rounded border bg-background p-2" value={f.expectedRevision} onChange={(event) => f.setExpectedRevision(Number(event.target.value))} />
        <div className="flex gap-2">
          <Button type="button" onClick={f.runPublish} disabled={f.pending || !f.bindingId || !f.poolId}>
            Publish binding
          </Button>
          <Button type="button" variant="destructive" onClick={f.runDrain} disabled={f.pending || !f.bindingId}>
            Drain binding
          </Button>
        </div>
        {f.revision ? (
          <output className="block">
            Binding {f.revision.sharing_binding_id} is now {f.revision.state} at revision {f.revision.definition_revision}.
          </output>
        ) : null}
      </fieldset>
    </section>
  );
}
