import { useState } from "react";
import { useModelSourceUsers } from "@/api/model-sources";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function SourceUserPicker({ organization, selected, onChange, disabled }: Readonly<{
  organization: string; selected: number[]; onChange: (ids: number[]) => void; disabled: boolean;
}>) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const query = useModelSourceUsers(organization, search, page);
  return <fieldset disabled={disabled} className="space-y-2 rounded border p-3">
    <legend>Authorize individual users</legend>
    <p>{selected.length} users selected.</p>
    <Label htmlFor="source-user-search">Find organization users</Label>
    <Input id="source-user-search" value={search} maxLength={100} onChange={(event) => { setPage(1); setSearch(event.target.value); }} />
    {query.isPending && <output>Loading users…</output>}
    {query.isError && <p role="alert">Users could not be loaded. Your current selection is retained.</p>}
    {query.data?.results.map((user) => <label key={user.id} className="flex gap-2">
      <input type="checkbox" checked={selected.includes(user.id)} disabled={!selected.includes(user.id) && selected.length >= 256}
        onChange={(event) => onChange(event.target.checked ? [...selected, user.id] : selected.filter((id) => id !== user.id))} />
      {user.name} ({user.username})
    </label>)}
    {query.data?.results.length === 0 && <p>No matching organization users.</p>}
    <div className="flex gap-2">
      <Button type="button" variant="outline" disabled={page === 1} onClick={() => setPage(page - 1)}>Previous users</Button>
      <Button type="button" variant="outline" disabled={!query.data?.has_next} onClick={() => setPage(page + 1)}>Next users</Button>
      {selected.length > 0 && <Button type="button" variant="outline" onClick={() => onChange([])}>Clear individual grants</Button>}
    </div>
  </fieldset>;
}
