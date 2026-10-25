import { useState } from "react";

import { useAdministrationMutation, useAdministrationQuery, type Account, type AdministrationSchemas, type Organization, type Workspace } from "@/api/account-administration";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { ScopeAuthorizationContent } from "../organization/WorkspaceAuthorizationPage";
import { AdministrationError, AdministrationPages, AdministrationSection, NameForm } from "./AdministrationForms";
import { ScopeMembershipPanel } from "./ScopeMembershipPanel";
import { WorkspaceAdministrationPanel } from "./WorkspaceAdministrationPanel";

/** S4 exports components; neither router nor navigation imports this page. */
export function AccountAdministrationEntry() {
  const context = useAdministrationQuery<AdministrationSchemas["AccountPrincipalContext"]>("/accounts/context/");
  const [browse, setBrowse] = useState(false);
  if (context.isPending) return <p>Loading account context…</p>;
  if (context.isError) return <AdministrationError error={context.error} />;
  const personal = context.data.individual_account;
  const canBrowse = context.data.accounts.count > (personal ? 1 : 0) || context.data.installation_actions.includes("installation.manage_accounts");
  return <div className="space-y-4">
    {personal && canBrowse ? <nav aria-label="Account views"><Button variant="outline" onClick={() => setBrowse(false)}>Your account</Button><Button variant="outline" onClick={() => setBrowse(true)}>Other accounts</Button></nav> : null}
    <AccountAdministrationPage key={`${context.data.principal_uuid}-${browse}`} individual={Boolean(personal) && !browse} />
  </div>;
}

export function AccountAdministrationPage({ individual = false }: Readonly<{ individual?: boolean }>) {
  return individual ? <IndividualAccount /> : <AccountCollection />;
}

function IndividualAccount() {
  const current = useAdministrationQuery<Account>("/accounts/current/");
  if (current.isPending) return <p>Loading account…</p>;
  if (current.isError) return <AdministrationError error={current.error} />;
  return <AccountContent key={current.data.uuid} account={current.data} />;
}

function AccountCollection() {
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Account | null>(null);
  const accounts = useAdministrationQuery<AdministrationSchemas["AccountPage"]>("/accounts/", { offset, limit: 50, search });
  return <div className="space-y-6">
    <PageHeader title="Customer accounts" description="Administer the accounts permitted by your current policy." />
    <Label htmlFor="account-search">Search accounts</Label><Input id="account-search" value={search} maxLength={200} onChange={event => { setSearch(event.target.value); setOffset(0); }} />
    <AdministrationError error={accounts.error} />
    {accounts.isPending ? <p>Loading accounts…</p> : null}
    {accounts.isSuccess ? <>
      <ul className="space-y-2">{accounts.data.results.map(account => <li key={account.uuid}><Button variant="outline" onClick={() => setSelected(account)}>{account.name}</Button></li>)}</ul>
      <AdministrationPages label="accounts" count={accounts.data.count} offset={offset} onOffset={setOffset} />
    </> : null}
    <CreateAccount />
    {selected ? <SelectedAccount key={selected.uuid} uuid={selected.uuid} /> : null}
  </div>;
}

function SelectedAccount({ uuid }: Readonly<{ uuid: string }>) {
  const account = useAdministrationQuery<Account>(`/accounts/${uuid}/`);
  if (account.isPending) return <p>Loading selected account…</p>;
  if (account.isError) return <AdministrationError error={account.error} />;
  return <AccountContent account={account.data} />;
}

function CreateAccount() {
  const [kind, setKind] = useState<AdministrationSchemas["AccountCommand"]["kind"]>("team");
  const [principal, setPrincipal] = useState("");
  const create = useAdministrationMutation<Account, AdministrationSchemas["AccountCommand"]>("/accounts/");
  return <AdministrationSection title="Create account">
    <label htmlFor="new-account-kind">Account type</label><select id="new-account-kind" value={kind} onChange={event => setKind(event.target.value as typeof kind)}><option value="individual">Individual</option><option value="team">Team</option><option value="enterprise">Enterprise</option></select>
    {kind === "individual" ? <><Label htmlFor="individual-principal">Individual principal UUID</Label><Input id="individual-principal" required value={principal} onChange={event => setPrincipal(event.target.value)} /></> : null}
    <NameForm label="New account name" submit="Create account" pending={create.isPending} error={create.error} onSave={name => create.mutate({ name, kind, ...(kind === "individual" ? { individual_principal_uuid: principal } : {}) })} />
  </AdministrationSection>;
}

function AccountContent({ account }: Readonly<{ account: Account }>) {
  const save = useAdministrationMutation<Account, AdministrationSchemas["PatchedSubdivisionCommand"]>(`/accounts/${account.uuid}/`, "PATCH");
  return <div className="space-y-6">
    <PageHeader title={account.name} description={`${account.kind} account`} />
    <NameForm label="Account name" initial={account.name} submit="Save account" pending={save.isPending} error={save.error} onSave={name => save.mutate({ name })} />
    <Tabs defaultValue="members"><TabsList>
      <TabsTrigger value="members">Members</TabsTrigger><TabsTrigger value="policies">Policies and groups</TabsTrigger>
      {account.kind === "individual" ? null : <TabsTrigger value="organizations">Organizations</TabsTrigger>}
    </TabsList>
      <TabsContent value="members"><ScopeMembershipPanel scope={{ kind: "account", uuid: account.uuid }} /></TabsContent>
      <TabsContent value="policies"><ScopeAuthorizationContent workspaceUuid={{ kind: "account", uuid: account.uuid }} /></TabsContent>
      {account.kind === "individual" ? null : <TabsContent value="organizations"><OrganizationCollection accountUuid={account.uuid} /></TabsContent>}
    </Tabs>
  </div>;
}

function OrganizationCollection({ accountUuid }: Readonly<{ accountUuid: string }>) {
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Organization | null>(null);
  const path = `/accounts/${accountUuid}/organizations/`;
  const organizations = useAdministrationQuery<AdministrationSchemas["OrganizationPage"]>(path, { offset, limit: 50 });
  const create = useAdministrationMutation<Organization, AdministrationSchemas["SubdivisionCommand"]>(path);
  return <div className="space-y-5">
    <AdministrationError error={organizations.error} />
    {organizations.isSuccess ? <>
      <ul>{organizations.data.results.map(organization => <li key={organization.uuid}><Button variant="outline" onClick={() => setSelected(organization)}>{organization.name}{organization.is_default ? " (default)" : ""}</Button></li>)}</ul>
      <AdministrationPages label="organizations" count={organizations.data.count} offset={offset} onOffset={setOffset} />
    </> : null}
    <NameForm label="New organization name" submit="Create organization" pending={create.isPending} error={create.error} onSave={name => create.mutate({ name })} />
    {selected ? <OrganizationContent key={selected.uuid} accountUuid={accountUuid} organization={selected} /> : null}
  </div>;
}

function OrganizationContent({ accountUuid, organization }: Readonly<{ accountUuid: string; organization: Organization }>) {
  return <AdministrationSection title={organization.name}>
    <OrganizationProfile accountUuid={accountUuid} organizationUuid={organization.uuid} />
    <Tabs defaultValue="workspaces"><TabsList><TabsTrigger value="workspaces">Workspaces</TabsTrigger><TabsTrigger value="members">Members</TabsTrigger><TabsTrigger value="policies">Policies and groups</TabsTrigger></TabsList>
      <TabsContent value="workspaces"><WorkspaceCollection accountUuid={accountUuid} organizationUuid={organization.uuid} /></TabsContent>
      <TabsContent value="members"><ScopeMembershipPanel scope={{ kind: "organization", uuid: organization.uuid }} /></TabsContent>
      <TabsContent value="policies"><ScopeAuthorizationContent workspaceUuid={{ kind: "organization", uuid: organization.uuid, accountUuid }} /></TabsContent>
    </Tabs>
  </AdministrationSection>;
}

function OrganizationProfile({ accountUuid, organizationUuid }: Readonly<{ accountUuid: string; organizationUuid: string }>) {
  const path = `/accounts/${accountUuid}/organizations/${organizationUuid}/`;
  const query = useAdministrationQuery<AdministrationSchemas["OrganizationProfile"]>(path);
  if (query.isPending) return <p>Loading organization…</p>;
  if (query.isError) return <AdministrationError error={query.error} />;
  return <OrganizationProfileForm key={organizationUuid} path={path} profile={query.data} />;
}

function OrganizationProfileForm({ path, profile }: Readonly<{ path: string; profile: AdministrationSchemas["OrganizationProfile"] }>) {
  const [draft, setDraft] = useState<Partial<AdministrationSchemas["PatchedOrganizationProfileUpdate"]>>({});
  const save = useAdministrationMutation<unknown, AdministrationSchemas["PatchedOrganizationProfileUpdate"]>(path, "PATCH");
  const labels = { name: "Organization name", description: "Description", support_email: "Support email", support_url: "Support URL" };
  return <form className="space-y-3" onSubmit={event => {
    event.preventDefault();
    save.mutate(draft, { onSuccess: () => setDraft({}) });
  }}>
    {Object.entries(labels).map(([key, label]) => <div key={key}><Label htmlFor={`organization-${key}`}>{label}</Label><Input id={`organization-${key}`} value={draft[key as keyof typeof draft] ?? profile[key as keyof typeof labels]} onChange={event => setDraft(current => ({ ...current, [key]: event.target.value }))} /></div>)}
    <Button type="submit" disabled={save.isPending}>Save organization</Button><AdministrationError error={save.error} />
  </form>;
}

function WorkspaceCollection({ accountUuid, organizationUuid }: Readonly<{ accountUuid: string; organizationUuid: string }>) {
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Workspace | null>(null);
  const [archived, setArchived] = useState(false);
  const path = `/accounts/${accountUuid}/organizations/${organizationUuid}/workspaces/`;
  const list = useAdministrationQuery<AdministrationSchemas["WorkspacePage"]>(path, { offset, limit: 50, include_archived: archived, search });
  const create = useAdministrationMutation<Workspace, AdministrationSchemas["SubdivisionCommand"]>(path);
  return <div className="space-y-4">
    <Label htmlFor="workspace-search">Search workspaces</Label><Input id="workspace-search" maxLength={200} value={search} onChange={event => { setSearch(event.target.value); setOffset(0); }} />
    <label className="flex gap-2"><input type="checkbox" checked={archived} onChange={event => { setArchived(event.target.checked); setOffset(0); }} />Include archived workspaces</label>
    <AdministrationError error={list.error} />
    {list.isSuccess ? <><ul>{list.data.results.map(workspace => <li key={workspace.uuid}><Button variant="outline" onClick={() => setSelected(workspace)}>{workspace.name}{workspace.archived_at ? " (archived)" : ""}</Button></li>)}</ul><AdministrationPages label="workspaces" count={list.data.count} offset={offset} onOffset={setOffset} /></> : null}
    <NameForm label="New workspace name" submit="Create workspace" pending={create.isPending} error={create.error} onSave={name => create.mutate({ name })} />
    {selected ? <WorkspaceAdministrationPanel key={selected.uuid} accountUuid={accountUuid} organizationUuid={organizationUuid} workspaceUuid={selected.uuid} /> : null}
  </div>;
}
