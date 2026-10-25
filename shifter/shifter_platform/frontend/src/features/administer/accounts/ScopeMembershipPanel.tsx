import { useState } from "react";

import { scopePath, useAdministrationMutation, useAdministrationQuery, type MembershipPage, type Scope } from "@/api/account-administration";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { AdministrationError, AdministrationPages, AdministrationSection } from "./AdministrationForms";

export function ScopeMembershipPanel({ scope }: Readonly<{ scope: Scope }>) {
  const [offset, setOffset] = useState(0);
  const [principal, setPrincipal] = useState("");
  const [kind, setKind] = useState<"human" | "service">("human");
  const [removing, setRemoving] = useState("");
  const path = `${scopePath(scope)}/memberships/`;
  const members = useAdministrationQuery<MembershipPage>(path, { offset, limit: 50 });
  const add = useAdministrationMutation(path);
  const remove = useAdministrationMutation(`${path}${encodeURIComponent(removing)}/`, "DELETE");
  return <AdministrationSection title="Members">
    <p>Membership records who belongs here. Assign permissions separately under Policies and groups.</p>
    {members.isPending ? <p>Loading members…</p> : null}
    <AdministrationError error={members.error ?? add.error ?? remove.error} />
    {members.isSuccess ? <>
      <form className="flex flex-wrap items-end gap-3" onSubmit={event => {
        event.preventDefault();
        add.mutate({ principal_uuid: principal, ...(scope.kind === "account" ? { principal_kind: kind } : {}) });
      }}>
        <div><Label htmlFor="member-principal">Member principal UUID</Label><Input id="member-principal" value={principal} required onChange={event => setPrincipal(event.target.value)} /></div>
        {scope.kind === "account" ? <label>Principal kind<select aria-label="Principal kind" value={kind} onChange={event => setKind(event.target.value as "human" | "service")}><option value="human">Human</option><option value="service">Service</option></select></label> : null}
        <Button disabled={add.isPending || !principal} type="submit">Add member</Button>
      </form>
      <ul className="space-y-2">{members.data.results.map(member => <li key={member.principal_uuid}>
        <Button variant="ghost" onClick={() => setRemoving(member.principal_uuid)}>{member.principal_uuid}</Button>
      </li>)}</ul>
      {removing ? <div className="space-y-2"><p>Remove membership for {removing}?</p><Button variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate(undefined, { onSuccess: () => setRemoving("") })}>Confirm removal</Button><Button variant="outline" onClick={() => setRemoving("")}>Cancel</Button></div> : null}
      <AdministrationPages label="members" count={members.data.count} offset={offset} onOffset={setOffset} />
    </> : null}
  </AdministrationSection>;
}
