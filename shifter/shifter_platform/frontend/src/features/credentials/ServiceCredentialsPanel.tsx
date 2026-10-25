import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useServiceCredentials, type ServiceCommand } from "@/api/access-credentials";
import { useAuthorizationCatalog } from "@/api/authorization";
import { apiFetch } from "@/api/client";
import { describeMutationError } from "@/api/errors";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function ServiceCredentialsPanel() {
  const [offset, setOffset] = useState(0);
  const credentials = useServiceCredentials(offset);
  const catalog = useAuthorizationCatalog();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [subject, setSubject] = useState("");
  const [principal, setPrincipal] = useState("");
  const [action, setAction] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [contacts, setContacts] = useState<Record<string, string>>({});
  const queryError = describeMutationError(credentials.error, "Service credential administration requires explicit authority.");
  async function mutate(path: string, body: unknown) {
    setBusy(true); setError("");
    try {
      await apiFetch(path, { method: "POST", body });
      await queryClient.invalidateQueries({ queryKey: ["access-credentials", "services"] });
    } catch (error_) { setError(describeMutationError(error_, "Service credential operation denied.") ?? "Service credential operation denied."); }
    finally { setBusy(false); }
  }
  function create() {
    const body: ServiceCommand = { name, subject, principal_uuid: principal || null, scopes: [`authorization:${action}` as ServiceCommand["scopes"][number]] };
    return mutate("/credentials/services/", body);
  }
  return <section aria-labelledby="service-credentials" className="space-y-4">
    <h2 id="service-credentials" className="text-xl font-semibold">Service identities</h2>
    <p>Register the Google service account’s immutable numeric unique ID, not its email. Admission grants no application policy or cloud IAM roles. Assign those separately. Services remain independent of their creator.</p>
    <p>Use the supported shifter-client transport with attached workload identity, local impersonation, or external-account federation. No static service-account key upload is supported.</p>
    {error || queryError ? <p role="alert">{error || queryError}</p> : null}
    {credentials.isPending ? <output>Loading service identities…</output> : null}
    {credentials.isSuccess ? <>
      <form className="grid gap-3 max-w-xl" onSubmit={event => { event.preventDefault(); void create(); }}>
        <Label htmlFor="service-name">Service name</Label><Input id="service-name" value={name} onChange={event => setName(event.target.value)} required maxLength={200} />
        <Label htmlFor="service-subject">Google service account unique ID</Label><Input id="service-subject" value={subject} onChange={event => setSubject(event.target.value)} required pattern="[0-9]{10,32}" />
        <Label htmlFor="service-principal">Existing service principal UUID (optional)</Label><Input id="service-principal" value={principal} onChange={event => setPrincipal(event.target.value)} />
        <Label htmlFor="service-action">Service credential action ceiling</Label><select id="service-action" className="rounded border bg-background p-2" value={action} onChange={event => setAction(event.target.value)} required><option value="">Select an action</option>{catalog.data?.map(item => <option key={item.code} value={item.code}>{item.code}</option>)}</select>
        <Button disabled={busy || !action} type="submit">Register service admission</Button>
      </form>
      <ul className="space-y-3">{credentials.data.results.map(service => <li key={service.credential_uuid} className="rounded border p-3">
        <h3>{service.name}</h3><p className="break-all">Principal: {service.principal_uuid}</p><p>Google ID: {service.subject}</p><p>Audience: {service.audience}</p><p>{service.scopes.join(", ")}</p><p>{service.is_active ? "Active admission" : "Disabled"}</p>
        <div className="flex gap-2"><Button variant="outline" disabled={busy || !service.admission_active} onClick={() => void mutate(`/credentials/services/${service.credential_uuid}/disable/`, {})}>Disable admission</Button>
        <Button variant="outline" disabled={busy} onClick={() => void mutate(`/credentials/services/principals/${service.principal_uuid}/`, { is_active: !service.principal_active })}>{service.principal_active ? "Disable principal" : "Enable principal"}</Button></div>
        <form className="mt-3 flex flex-wrap items-end gap-2" onSubmit={event => {
          event.preventDefault();
          const contact = contacts[service.credential_uuid] ?? String(service.responsible_user_id ?? "");
          void mutate(`/credentials/services/principals/${service.principal_uuid}/`, { is_active: service.principal_active, responsible_user_id: contact ? Number(contact) : null });
        }}>
          <div><Label htmlFor={`contact-${service.credential_uuid}`}>Responsible user ID (optional contact only)</Label><Input id={`contact-${service.credential_uuid}`} type="number" min={1} value={contacts[service.credential_uuid] ?? String(service.responsible_user_id ?? "")} onChange={event => setContacts(current => ({ ...current, [service.credential_uuid]: event.target.value }))} /></div>
          <Button variant="outline" disabled={busy} type="submit">Save contact</Button>
        </form>
      </li>)}</ul>
      <nav aria-label="Service credential pages" className="flex gap-2"><Button variant="outline" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous services</Button><Button variant="outline" disabled={credentials.data.next_offset == null} onClick={() => setOffset(credentials.data.next_offset ?? offset)}>Next services</Button></nav>
    </> : null}
  </section>;
}
