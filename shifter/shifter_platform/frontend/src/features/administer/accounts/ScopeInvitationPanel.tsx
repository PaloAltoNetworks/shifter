import { useState } from "react";

import { useAdministrationMutation, useAdministrationQuery, type AdministrationSchemas } from "@/api/account-administration";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { AdministrationError, AdministrationPages, AdministrationSection } from "./AdministrationForms";

function InvitationActions({ workspaceUuid, invitation }: Readonly<{ workspaceUuid: string; invitation: AdministrationSchemas["PolicyWorkspaceInvitation"] }>) {
  const path = `/workspaces/${workspaceUuid}/invitations/${invitation.invitation_uuid}`;
  const resend = useAdministrationMutation(`${path}/resend/`);
  const revoke = useAdministrationMutation(`${path}/revoke/`);
  const [confirming, setConfirming] = useState(false);
  return <li className="space-y-2 rounded border p-3"><p>{invitation.email} · {invitation.status}</p>
    <AdministrationError error={resend.error ?? revoke.error} />
    {invitation.status === "pending" || invitation.status === "expired" ? <div className="flex gap-2">
      <Button variant="outline" disabled={resend.isPending || revoke.isPending} onClick={() => resend.mutate({})}>Resend invitation</Button>
      <Button variant="outline" onClick={() => setConfirming(true)}>Revoke invitation</Button>
      {confirming ? <Button variant="destructive" disabled={revoke.isPending} onClick={() => revoke.mutate({})}>Confirm revocation</Button> : null}
    </div> : null}
  </li>;
}

export function ScopeInvitationPanel({ workspaceUuid }: Readonly<{ workspaceUuid: string }>) {
  const [email, setEmail] = useState("");
  const [offset, setOffset] = useState(0);
  const path = `/workspaces/${workspaceUuid}/invitations/`;
  const list = useAdministrationQuery<AdministrationSchemas["PolicyInvitationPage"]>(path, { offset, limit: 50 });
  const issue = useAdministrationMutation(path);
  return <AdministrationSection title="Invitations">
    <p>Recipients must sign in with their verified identity to accept. Invitation acceptance adds membership; permissions are assigned separately.</p>
    <AdministrationError error={list.error ?? issue.error} />
    {list.isPending ? <p>Loading invitations…</p> : null}
    {list.isSuccess ? <>
      <form className="flex items-end gap-3" onSubmit={event => { event.preventDefault(); issue.mutate({ email }); }}>
        <div><Label htmlFor="invitation-email">Recipient email</Label><Input id="invitation-email" type="email" required value={email} onChange={event => setEmail(event.target.value)} /></div>
        <Button type="submit" disabled={issue.isPending}>Send invitation</Button>
      </form>
      <ul className="space-y-3">{list.data.results.map(invitation => <InvitationActions key={invitation.invitation_uuid} workspaceUuid={workspaceUuid} invitation={invitation} />)}</ul>
      <AdministrationPages count={list.data.count} offset={offset} onOffset={setOffset} label="invitations" />
    </> : null}
  </AdministrationSection>;
}
