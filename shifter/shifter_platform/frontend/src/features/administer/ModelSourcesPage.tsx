import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { describeMutationError } from "@/api/errors";
import { retireModelSourceCredentials, saveModelSource, sourceKey, useModelSources, type ModelSource } from "@/api/model-sources";
import { useAdministrableOrganizations } from "@/api/organization";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";

import { RangeModelSources } from "./RangeModelSources";

import { ModelSourceForm } from "./ModelSourceForm";

export function ModelSourcesPage() {
  const [page, setPage] = useState(1);
  const organizations = useAdministrableOrganizations(page);
  const [selected, setSelected] = useState("");
  const rows = organizations.data?.results ?? [];
  const organization = rows.find((row) => row.uuid === selected)?.uuid ?? rows[0]?.uuid ?? "";
  return <>
    <PageHeader title="Model sources" description="Connect model accounts and choose who may use them in scenarios and CTFs." />
    {organizations.error ? <Alert variant="destructive"><AlertDescription>{describeMutationError(organizations.error, "Organizations could not be loaded.")}</AlertDescription></Alert> : null}
    {organizations.isPending ? <output>Loading organizations…</output> : null}
    {organizations.isSuccess && !rows.length ? <p>Organization administrator access is required to manage sources.</p> : null}
    {rows.length ? <div className="mb-4 space-y-2">
      <Label htmlFor="model-source-organization">Organization</Label>
      <select id="model-source-organization" className="block rounded border bg-background p-2" value={organization} onChange={(event) => setSelected(event.target.value)}>
        {rows.map((row) => <option key={row.uuid} value={row.uuid}>{row.name}</option>)}
      </select>
      {organizations.data?.previous || organizations.data?.next ? <nav aria-label="Organization pages" className="flex gap-2">
        <Button disabled={!organizations.data.previous} onClick={() => setPage(page - 1)}>Previous organizations</Button>
        <Button disabled={!organizations.data.next} onClick={() => setPage(page + 1)}>Next organizations</Button>
      </nav> : null}
    </div> : null}
    {organization ? <div key={organization} className="space-y-8"><SourceList organization={organization} /><RangeModelSources organization={organization} /></div> : null}
  </>;
}

function SourceList({ organization }: Readonly<{ organization: string }>) {
  const client = useQueryClient();
  const query = useModelSources(organization);
  const [editing, setEditing] = useState<ModelSource | "new" | null>(null);
  const [changing, setChanging] = useState<ModelSource | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [cleanup, setCleanup] = useState<ModelSource | null>(null);
  const [cleanupResult, setCleanupResult] = useState("");
  async function retireCredentials() {
    if (!cleanup || pending) return;
    setPending(true); setError(null); setCleanupResult("");
    try {
      const result = await retireModelSourceCredentials(organization, cleanup.id);
      setCleanupResult(result.retired ? `Retired ${result.retired} unused credential versions.` : "No unused credentials are eligible yet. Active ranges, outstanding usage and recently stored credentials are retained.");
      setCleanup(null);
    } catch (error_) { setError(error_); } finally { setPending(false); }
  }
  async function changeState() {
    if (!changing || pending) return;
    setPending(true); setError(null);
    try {
      await saveModelSource(organization, { configuration: changing.configuration }, { ...changing, enabled: !changing.enabled });
      await Promise.all([client.invalidateQueries({ queryKey: sourceKey(organization) }), client.invalidateQueries({ queryKey: ["model-source-options"] })]); setChanging(null);
    } catch (error_) { setError(error_); } finally { setPending(false); }
  }
  return <div className="space-y-4">
    {cleanupResult ? <output>{cleanupResult}</output> : null}
    {query.isPending ? <output>Loading model sources…</output> : null}
    {query.error ? <Alert variant="destructive"><AlertDescription>{describeMutationError(query.error, "Sources could not be loaded.")}</AlertDescription></Alert> : null}
    {query.isSuccess ? <>
      <Button onClick={() => setEditing("new")}>Add model source</Button>
      {editing ? <ModelSourceForm key={editing === "new" ? "new" : `${editing.id}-${editing.revision}`} organization={organization}
        source={editedSource(editing)} onSaved={() => setEditing(null)} /> : null}
      {query.data.results.length === 0 ? <p>No model sources are configured.</p> : null}
      {query.data.results.map((source) => <SourceCard key={source.id} source={source}
        onEdit={() => setEditing(source)} onToggle={() => { setError(null); setChanging(source); }}
        onRetire={() => { setError(null); setCleanup(source); }} />)}
    </> : null}
    <ConfirmDialog open={changing !== null} onOpenChange={(open) => { if (!open && !pending) setChanging(null); }}
      title={`${changing?.enabled ? "Disable" : "Enable"} model source?`} confirmLabel="Confirm source change" pending={pending} error={error}
      destructive={changing?.enabled} onConfirm={() => void changeState()}>
      {changing?.enabled ? "Requests using this source will be fenced. Existing usage and outstanding charges are retained." : "Authorized users will be able to select this source again."}
    </ConfirmDialog>
    <ConfirmDialog open={cleanup !== null} onOpenChange={(open) => { if (!open && !pending) setCleanup(null); }}
      title="Retire unused credentials?" confirmLabel="Retire unused credentials" pending={pending} error={error}
      destructive onConfirm={() => void retireCredentials()}>
      Deletes obsolete stored credentials after their grace period. Current credentials and versions needed by active ranges or outstanding usage are retained. A failed cleanup can be retried here.
    </ConfirmDialog>
  </div>;
}

function editedSource(editing: ModelSource | "new"): ModelSource | undefined {
  return editing === "new" ? undefined : editing;
}


function SourceCard({ source, onEdit, onToggle, onRetire }: Readonly<{
  source: ModelSource; onEdit: () => void; onToggle: () => void; onRetire: () => void;
}>) {
  return <article className="space-y-2 rounded border p-4">
        <h2 className="font-semibold">{source.configuration.name}</h2>
        <p>{source.configuration.model} · {source.configuration.region} · Revision {source.revision}</p>
        <p>{source.state === "ready" ? "Configured" : source.state}. {source.configuration.allow_organization_members ? "Organization members may use this source." : "Use is restricted to explicitly authorized users."}</p>
        <div className="flex gap-2"><Button variant="outline" onClick={onEdit}>Edit {source.configuration.name}</Button>
          <Button variant="outline" onClick={onToggle}>{source.enabled ? "Disable" : "Enable"} {source.configuration.name}</Button>
          <Button variant="outline" onClick={onRetire}>Retire unused credentials for {source.configuration.name}</Button></div>
      </article>;
}
