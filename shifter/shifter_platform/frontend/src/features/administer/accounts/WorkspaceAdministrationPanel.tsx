import { useState } from "react";

import { useAdministrationMutation, useAdministrationQuery, type AdministrationSchemas, type MembershipPage, type Workspace } from "@/api/account-administration";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { ScopeAuthorizationContent } from "../organization/WorkspaceAuthorizationPage";
import { AdministrationError, AdministrationSection, NameForm } from "./AdministrationForms";
import { ScopeInvitationPanel } from "./ScopeInvitationPanel";
import { ScopeMembershipPanel } from "./ScopeMembershipPanel";
import { RangeScopePanel } from "./RangeScopePanel";

export function WorkspaceAdministrationPanel({ accountUuid, organizationUuid, workspaceUuid }: Readonly<{
  accountUuid: string; organizationUuid: string; workspaceUuid: string;
}>) {
  const detail = useAdministrationQuery<Workspace>(`/accounts/${accountUuid}/organizations/${organizationUuid}/workspaces/${workspaceUuid}/`, { include_archived: true });
  if (detail.isPending) return <p>Loading workspace…</p>;
  if (detail.isError) return <AdministrationError error={detail.error} />;
  return <WorkspaceContent key={workspaceUuid} workspace={detail.data} />;
}

function WorkspaceContent({ workspace }: Readonly<{ workspace: Workspace }>) {
  const path = `/workspaces/${workspace.uuid}`;
  const rename = useAdministrationMutation<unknown, AdministrationSchemas["SubdivisionCommand"]>(`${path}/rename/`);
  const lifecycle = useAdministrationMutation(`${path}/${workspace.archived_at ? "restore" : "archive"}/`);
  const [confirming, setConfirming] = useState(false);
  return <AdministrationSection title={workspace.name}>
    <p>{workspace.archived_at ? "Archived" : "Active"}{workspace.is_default ? " · Default workspace" : ""}</p>
    <NameForm label="Workspace name" initial={workspace.name} submit="Rename workspace" pending={rename.isPending || Boolean(workspace.archived_at)} error={rename.error} onSave={name => rename.mutate({ name })} />
    <Button variant="outline" disabled={lifecycle.isPending || (!workspace.archived_at && workspace.is_default)} onClick={() => setConfirming(true)}>{workspace.archived_at ? "Restore workspace" : "Archive workspace"}</Button>
    {confirming ? <div className="space-y-2"><p>Confirm this workspace lifecycle change? Existing ranges remain bound to the workspace.</p><Button disabled={lifecycle.isPending} onClick={() => lifecycle.mutate({}, { onSuccess: () => setConfirming(false) })}>Confirm workspace change</Button><Button variant="outline" onClick={() => setConfirming(false)}>Cancel</Button></div> : null}
    <AdministrationError error={lifecycle.error} />
    <RangeScopePanel key={workspace.uuid} workspaceUuid={workspace.uuid} />
    {workspace.archived_at ? null : <Tabs defaultValue="members"><TabsList>
      <TabsTrigger value="members">Workspace members</TabsTrigger><TabsTrigger value="invitations">Invitations</TabsTrigger><TabsTrigger value="ownership">Ownership</TabsTrigger><TabsTrigger value="limits">Quota and egress</TabsTrigger><TabsTrigger value="policies">Workspace policies</TabsTrigger>
    </TabsList>
      <TabsContent value="members"><ScopeMembershipPanel scope={{ kind: "workspace", uuid: workspace.uuid }} /></TabsContent>
      <TabsContent value="invitations"><ScopeInvitationPanel workspaceUuid={workspace.uuid} /></TabsContent>
      <TabsContent value="ownership"><WorkspaceOwnership workspace={workspace} /></TabsContent>
      <TabsContent value="limits"><WorkspaceLimits workspace={workspace} /></TabsContent>
      <TabsContent value="policies"><ScopeAuthorizationContent workspaceUuid={workspace.uuid} /></TabsContent>
    </Tabs>}
  </AdministrationSection>;
}

function WorkspaceOwnership({ workspace }: Readonly<{ workspace: Workspace }>) {
  const [destination, setDestination] = useState("");
  const [selectedSource, setSelectedSource] = useState("");
  const owners = workspace.owner_principal_uuids;
  const source = owners.includes(selectedSource) ? selectedSource : owners[0] ?? null;
  const [confirming, setConfirming] = useState(false);
  const members = useAdministrationQuery<MembershipPage>(`/workspaces/${workspace.uuid}/memberships/`, { offset: 0, limit: 100 });
  const transfer = useAdministrationMutation<unknown, AdministrationSchemas["PrincipalOwnershipCommand"]>(`/workspaces/${workspace.uuid}/transfer/`);
  const addOwner = useAdministrationMutation(`/workspaces/${workspace.uuid}/owners/`);
  return <AdministrationSection title="Workspace ownership">
    <p>Current owners: {owners.join(", ") || "Unassigned"}. Ownership does not grant application permissions.</p>
    <label htmlFor="workspace-source-owner">Source owner</label><select id="workspace-source-owner" value={source ?? ""} onChange={event => setSelectedSource(event.target.value)}><option value="">Unassigned</option>{owners.map(owner => <option key={owner} value={owner}>{owner}</option>)}</select>
    <ul>{owners.map(owner => <OwnerRemoval key={owner} workspaceUuid={workspace.uuid} owner={owner} last={owners.length === 1} />)}</ul>
    <AdministrationError error={members.error ?? transfer.error ?? addOwner.error} />
    <Label htmlFor="workspace-destination">Destination principal UUID</Label>
    <Input id="workspace-destination" list="workspace-members" required value={destination} onChange={event => { setDestination(event.target.value); setConfirming(false); }} />
    <datalist id="workspace-members">{members.data?.results.filter(member => !owners.includes(member.principal_uuid)).map(member => <option key={member.principal_uuid} value={member.principal_uuid} />)}</datalist>
    <p>The destination must be an existing active workspace member.</p>
    <Button disabled={!destination || transfer.isPending} onClick={() => setConfirming(true)}>Transfer ownership</Button>
    <Button variant="outline" disabled={!destination || addOwner.isPending} onClick={() => addOwner.mutate({ principal_uuid: destination })}>Add owner</Button>
    {confirming ? <div className="space-y-2"><p>Transfer ownership to {destination}?</p><Button disabled={transfer.isPending} onClick={() => transfer.mutate({ source_principal_uuid: source, destination_principal_uuid: destination }, { onSuccess: () => setConfirming(false) })}>Confirm ownership transfer</Button><Button variant="outline" onClick={() => setConfirming(false)}>Cancel</Button></div> : null}
  </AdministrationSection>;
}

function OwnerRemoval({ workspaceUuid, owner, last }: Readonly<{ workspaceUuid: string; owner: string; last: boolean }>) {
  const [confirming, setConfirming] = useState(false);
  const remove = useAdministrationMutation(`/workspaces/${workspaceUuid}/owners/${owner}/`, "DELETE");
  return <li className="space-y-2"><p>{owner}</p><AdministrationError error={remove.error} />
    <Button variant="outline" disabled={last || remove.isPending} onClick={() => setConfirming(true)}>Remove owner {owner}</Button>
    {confirming ? <Button variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate(undefined)}>Confirm owner removal</Button> : null}
  </li>;
}

function WorkspaceLimits({ workspace }: Readonly<{ workspace: Workspace }>) {
  const [resource, setResource] = useState<AdministrationSchemas["WorkspaceQuotaPolicyCommand"]["resource"]>("member_seats");
  const [egress, setEgress] = useState<AdministrationSchemas["WorkspaceEgressPolicyCommand"]["egress_policy"]>(workspace.egress_policy === "none" ? "none" : "status-quo");
  const path = `/workspaces/${workspace.uuid}`;
  const usage = useAdministrationQuery<AdministrationSchemas["WorkspaceQuota"]>(`${path}/quota/`);
  const setEgressPolicy = useAdministrationMutation<unknown, AdministrationSchemas["WorkspaceEgressPolicyCommand"]>(`${path}/egress-policy/`, "PUT");
  return <AdministrationSection title="Quota and egress">
    <AdministrationError error={usage.error ?? setEgressPolicy.error} />
    {usage.data ? <ul>{usage.data.resources.map(item => <li key={item.resource}>{item.resource.replaceAll("_", " ")}: {item.usage} / {item.limit ?? "unlimited"} {item.mode ?? ""}</li>)}</ul> : null}
    <Label htmlFor="quota-resource">Quota resource</Label><select id="quota-resource" value={resource} onChange={event => setResource(event.target.value as typeof resource)}><option value="member_seats">Member seats</option><option value="concurrent_ranges">Concurrent ranges</option></select>
    {usage.isSuccess ? <QuotaPolicyForm key={resource} workspaceUuid={workspace.uuid} resource={resource} policy={usage.data.resources.find(item => item.resource === resource)} /> : null}
    <form className="space-y-3" onSubmit={event => { event.preventDefault(); setEgressPolicy.mutate({ egress_policy: egress }); }}>
      <Label htmlFor="workspace-egress">Workspace egress</Label><select id="workspace-egress" value={egress} onChange={event => setEgress(event.target.value as typeof egress)}><option value="status-quo">Inherit deployment policy</option><option value="none">Zero outbound egress</option></select>
      <p>This selection applies to newly provisioned ranges.</p><Button type="submit" disabled={setEgressPolicy.isPending}>Save egress</Button>
    </form>
  </AdministrationSection>;
}

function QuotaPolicyForm({ workspaceUuid, resource, policy }: Readonly<{
  workspaceUuid: string; resource: AdministrationSchemas["WorkspaceQuotaPolicyCommand"]["resource"];
  policy: AdministrationSchemas["WorkspaceQuotaResource"] | undefined;
}>) {
  const [mode, setMode] = useState<AdministrationSchemas["WorkspaceQuotaPolicyCommand"]["mode"]>(policy?.mode === "advisory" ? "advisory" : "enforcing");
  const [limit, setLimit] = useState(policy?.limit == null ? "" : String(policy.limit));
  const quota = useAdministrationMutation<unknown, AdministrationSchemas["WorkspaceQuotaPolicyCommand"]>(`/workspaces/${workspaceUuid}/quota-policy/`, "PUT");
  return <form className="space-y-3" onSubmit={event => { event.preventDefault(); quota.mutate({ resource, mode, limit: Number(limit) }); }}>
    <AdministrationError error={quota.error} />
    <Label htmlFor="quota-mode">Quota enforcement</Label><select id="quota-mode" value={mode} onChange={event => setMode(event.target.value as typeof mode)}><option value="enforcing">Enforce limit</option><option value="advisory">Warn only</option></select>
    <Label htmlFor="quota-limit">Quota limit</Label><Input id="quota-limit" type="number" min={0} step={1} value={limit} required onChange={event => setLimit(event.target.value)} />
    <Button type="submit" disabled={quota.isPending || limit === ""}>Save quota</Button>
  </form>;
}
