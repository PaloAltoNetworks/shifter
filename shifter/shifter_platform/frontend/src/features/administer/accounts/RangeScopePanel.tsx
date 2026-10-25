import { useState } from "react";

import { useAdministrationMutation, useAdministrationQuery, type AdministrationSchemas } from "@/api/account-administration";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AdministrationError, AdministrationSection } from "./AdministrationForms";

export function RangeScopePanel({ workspaceUuid }: Readonly<{ workspaceUuid: string }>) {
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<AdministrationSchemas["RangeScopeBinding"] | null>(null);
  const [destination, setDestination] = useState("");
  const rows = useAdministrationQuery<AdministrationSchemas["PaginatedRangeScopeBindingList"]>(`/cms/workspaces/${workspaceUuid}/range-scoping/`, { page });
  const move = useAdministrationMutation<AdministrationSchemas["RangeWorkspaceRebindResult"], AdministrationSchemas["PolicyRangeWorkspaceCommand"]>(`/cms/ranges/${selected?.request_id ?? ""}/workspace/`);
  return <AdministrationSection title="Range scoping">
    <AdministrationError error={rows.error ?? move.error} />
    {rows.isPending ? <p>Loading ranges…</p> : null}
    {rows.isSuccess ? <>
      <p>{rows.data.count} ranges</p>
      <ul>{rows.data.results.map(row => <li key={row.request_id ?? row.scenario_id} className="space-y-2">
        <p>{row.scenario_id} · {row.status} · Owner {row.owner_id}</p>
        <Button disabled={!row.is_reassignable || !row.request_id || move.isPending} onClick={() => { move.reset(); setSelected(row); setDestination(""); }}>Move {row.scenario_id}</Button>
      </li>)}</ul>
      <nav aria-label="Range pages"><Button disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous ranges</Button><Button disabled={!rows.data.next} onClick={() => setPage(page + 1)}>Next ranges</Button></nav>
    </> : null}
    {selected ? <form className="space-y-3" onSubmit={event => {
      event.preventDefault();
      move.mutate({ target_workspace_uuid: destination }, { onSuccess: () => setSelected(null) });
    }}>
      <p>Move {selected.scenario_id}? Its owner must be a member of the destination. Destination quota also applies.</p>
      <Label htmlFor="range-destination">Destination workspace UUID</Label><Input id="range-destination" required value={destination} onChange={event => setDestination(event.target.value)} />
      <Button type="submit" disabled={!destination || move.isPending}>Confirm range move</Button><Button type="button" variant="outline" disabled={move.isPending} onClick={() => setSelected(null)}>Cancel</Button>
    </form> : null}
  </AdministrationSection>;
}
