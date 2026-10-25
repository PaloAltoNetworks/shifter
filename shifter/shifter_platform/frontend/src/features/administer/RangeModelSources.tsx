import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { describeMutationError } from "@/api/errors";
import { revokeRangeModelAccess } from "@/api/model-access";
import { rangeSourceKey, saveRangeModelSources, useModelRanges, useRangeModelSources,
  type ModelSourceSelection, type RangeModelSources as RangePolicy } from "@/api/model-sources";
import { ModelSourcePicker } from "@/components/ModelSourcePicker";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

const runtimeMessages = {
  active: "Model access is active.",
  refresh_pending: "Waiting for the guest to refresh its model access.",
  unavailable: "Model access is unavailable.",
};

export function RangeModelSources({ organization }: Readonly<{ organization: string }>) {
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState("");
  const ranges = useModelRanges(organization, page);
  return <section aria-label="Range model sources" className="space-y-4 border-t pt-6">
    <h2 className="text-lg font-semibold">Existing ranges</h2>
    <p>Change a running range’s model sources. New requests pause until its guest adopts the replacement grant. Existing usage and outstanding charges remain accounted for.</p>
    {ranges.isPending && <output>Loading ranges…</output>}
    {ranges.error && <Alert variant="destructive"><AlertDescription>{describeMutationError(ranges.error, "Ranges could not be loaded.")}</AlertDescription></Alert>}
    {ranges.data?.results.length === 0 && <p>No ranges are available in this organization.</p>}
    {ranges.data?.results.map((range) => <article key={range.request_id} className="space-y-2 rounded border p-3">
      <h3 className="font-medium">{range.scenario} <span className="font-mono text-sm">{range.request_id.slice(0, 8)}</span></h3>
      <p>{range.status} · Model policy revision {range.revision}</p>
      {range.error && <output>Model access needs attention.</output>}
      <Button variant="outline" onClick={() => setEditing(range.request_id)}>Manage model sources</Button>
      {editing === range.request_id && <RangeEditor request={range.request_id} onClose={() => setEditing("")} />}
    </article>)}
    {ranges.data && (page > 1 || ranges.data.has_next) && <nav aria-label="Model range pages" className="flex gap-2">
      <Button disabled={page === 1} onClick={() => { setEditing(""); setPage(page - 1); }}>Previous ranges</Button>
      <Button disabled={!ranges.data.has_next} onClick={() => { setEditing(""); setPage(page + 1); }}>Next ranges</Button>
    </nav>}
  </section>;
}

function RangeEditor({ request, onClose }: Readonly<{ request: string; onClose: () => void }>) {
  const query = useRangeModelSources(request);
  if (query.isPending) return <output>Loading current model policy…</output>;
  if (query.error) return <Alert variant="destructive"><AlertDescription>{describeMutationError(query.error, "The range's model policy could not be loaded.")}</AlertDescription></Alert>;
  if (!query.data) return null;
  return <PolicyForm key={query.data.revision} policy={query.data} onClose={onClose} />;
}

function PolicyForm({ policy, onClose }: Readonly<{ policy: RangePolicy; onClose: () => void }>) {
  const client = useQueryClient();
  const [selection, setSelection] = useState<ModelSourceSelection>(policy.selection);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function save() {
    if (pending) return;
    setPending(true); setError(null);
    try {
      const result = await saveRangeModelSources(policy.request_id, policy.revision, selection);
      client.setQueryData(rangeSourceKey(policy.request_id), result);
      await client.invalidateQueries({ queryKey: ["model-ranges"] });
    } catch (error_) { setError(error_); } finally { setPending(false); }
  }
  async function revoke() {
    if (pending) return;
    setPending(true); setError(null);
    try {
      // Fences the current grants and dispatch leases. Outstanding usage stays
      // accounted for; this does not refund spend or cancel a billable request.
      const result = await revokeRangeModelAccess(policy.request_id);
      client.setQueryData(rangeSourceKey(policy.request_id), result);
      await client.invalidateQueries({ queryKey: ["model-ranges"] });
    } catch (error_) { setError(error_); } finally { setPending(false); }
  }
  return <form aria-label="Edit range model sources" className="space-y-4" onSubmit={(event) => { event.preventDefault(); void save(); }}>
    {Boolean(error) && <Alert variant="destructive"><AlertDescription>{describeMutationError(error, "The source change could not be saved. Reload the policy before retrying.")}</AlertDescription></Alert>}
    <output>{runtimeMessages[policy.runtime.state]}</output>
    {policy.error && <p role="alert">The selected policy could not be admitted. Correct the sources or their limits and retry. The old grant remains revoked.</p>}
    {policy.runtime.assignments.map((item) => <p key={`${item.workload}-${item.logical_alias}`} className="text-sm">{item.workload} / {item.logical_alias}: {item.provider} · {item.model} · {item.region}</p>)}
    <ModelSourcePicker scenario={policy.scenario} workspace={policy.workspace} purpose="admin" value={selection} onChange={setSelection} disabled={pending} />
    <div className="flex gap-2">
      <Button type="submit" disabled={pending}>{pending ? "Applying…" : "Apply source policy"}</Button>
      <Button type="button" variant="destructive" disabled={pending} onClick={() => void revoke()}>Revoke model access</Button>
      <Button type="button" variant="outline" disabled={pending} onClick={() => void client.invalidateQueries({ queryKey: rangeSourceKey(policy.request_id) })}>Reload policy</Button>
      <Button type="button" variant="outline" disabled={pending} onClick={onClose}>Close editor</Button>
    </div>
  </form>;
}
