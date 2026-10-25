import { useState } from "react";

import { useAdministrationMutation, useAdministrationQuery, type AdministrationSchemas } from "@/api/account-administration";
import { useAuthorizationOperation, useRelationshipMutation } from "@/api/authorization";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AccessCredentialsPage } from "@/features/credentials/AccessCredentialsPage";

import { AuditPage } from "../AuditPage";
import { PlatformSettingsPage } from "../PlatformSettingsPage";
import { MutationOutcome, ScopeAuthorizationContent } from "../organization/WorkspaceAuthorizationPage";
import { AdministrationError, AdministrationSection } from "./AdministrationForms";

/** Exported preparation; activation and navigation remain owned by S8. */
export function PlatformAdministrationPage() {
  return <div className="space-y-6"><PageHeader title="Platform administration" description="Every operation is checked against your current credential and policy." />
    <Tabs defaultValue="users"><TabsList><TabsTrigger value="users">Users</TabsTrigger><TabsTrigger value="policies">Platform policies</TabsTrigger><TabsTrigger value="credentials">Credentials</TabsTrigger><TabsTrigger value="audit">Audit history</TabsTrigger><TabsTrigger value="settings">Lease settings</TabsTrigger></TabsList>
      <TabsContent value="users"><PolicyIdentityAdministration /></TabsContent>
      <TabsContent value="policies"><ScopeAuthorizationContent workspaceUuid={{ kind: "installation" }} /></TabsContent>
      <TabsContent value="credentials"><AccessCredentialsPage /></TabsContent>
      <TabsContent value="audit"><AuditPage /></TabsContent>
      <TabsContent value="settings"><PlatformSettingsPage /></TabsContent>
    </Tabs>
  </div>;
}

function PolicyIdentityAdministration() {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const list = useAdministrationQuery<AdministrationSchemas["PaginatedAdminUserListItemList"]>("/administer/users/", { search, page, include_deleted: includeDeleted });
  return <AdministrationSection title="Users">
    <Label htmlFor="identity-search">Search users</Label><Input id="identity-search" value={search} maxLength={200} onChange={event => { setSearch(event.target.value); setPage(1); }} />
    <label className="flex gap-2"><input type="checkbox" checked={includeDeleted} onChange={event => { setIncludeDeleted(event.target.checked); setPage(1); }} />Include deleted users</label>
    <AdministrationError error={list.error} />
    {list.isPending ? <p>Loading users…</p> : null}
    {list.isSuccess ? <><ul>{list.data.results.map(user => <li key={user.id}><Button variant="outline" onClick={() => setSelected(user.id)}>{user.display_name}</Button></li>)}</ul>
      <nav aria-label="User pages" className="flex gap-2"><Button disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous users</Button><Button disabled={!list.data.next} onClick={() => setPage(page + 1)}>Next users</Button></nav>
    </> : null}
    {selected === null ? null : <PolicyUserDetails key={selected} id={selected} />}
  </AdministrationSection>;
}

function PolicyUserDetails({ id }: Readonly<{ id: number }>) {
  const detail = useAdministrationQuery<AdministrationSchemas["PolicyAdminUserDetail"]>(`/administer/users/${id}/`);
  const [action, setAction] = useState("");
  const actionPaths: Record<string, string> = { delete: "delete", reset_password: "reset-password" };
  const path = actionPaths[action] ?? "lifecycle";
  const mutation = useAdministrationMutation(`/administer/users/${id}/${path}/`);
  const labels: Record<string, string> = { activate: "Activate", deactivate: "Deactivate", suspend: "Suspend", restore: "Restore", delete: "Delete", reset_password: "Reset password" };
  if (detail.isPending) return <p>Loading user…</p>;
  if (detail.isError) return <AdministrationError error={detail.error} />;
  const user = detail.data;
  return <AdministrationSection title={user.display_name}>
    <p>{user.email || user.username} · {user.lifecycle_state}</p><p>Principal: {user.principal_uuid}</p>
    <div className="flex flex-wrap gap-2">{user.available_actions.filter(value => labels[value]).map(value => <Button key={value} variant="outline" onClick={() => { mutation.reset(); setAction(value); }}>{labels[value]}</Button>)}</div>
    {action ? <div className="space-y-2"><p>Confirm {labels[action]?.toLowerCase()} for this user?</p><AdministrationError error={mutation.error} /><Button disabled={mutation.isPending} onClick={() => mutation.mutate(path === "lifecycle" ? { action } : {}, { onSuccess: () => setAction("") })}>Confirm identity change</Button><Button variant="outline" onClick={() => setAction("")}>Cancel</Button></div> : null}
    {user.available_actions.includes("transfer_ownership") ? <OffboardingForm userId={id} /> : null}
    <UserMetadataForm user={user} />
    <ScopedOrganizerForm userId={id} />
    <PersonalCredentialAdministration principalUuid={user.principal_uuid} />
  </AdministrationSection>;
}

function OffboardingForm({ userId }: Readonly<{ userId: number }>) {
  const [replacement, setReplacement] = useState("");
  const [ranges, setRanges] = useState(true);
  const [workspaces, setWorkspaces] = useState(true);
  const [confirming, setConfirming] = useState(false);
  const mutation = useAdministrationMutation<AdministrationSchemas["PolicyTransferOwnershipResult"], AdministrationSchemas["PolicyTransferOwnershipCommand"]>(`/administer/users/${userId}/transfer-ownership/`);
  return <AdministrationSection title="Offboarding ownership transfer">
    <p>Each resource retains its scope and destination eligibility checks. Blocked resources remain owned by the source.</p>
    <Label htmlFor="offboarding-replacement">Replacement user ID</Label><Input id="offboarding-replacement" type="number" min={1} step={1} value={replacement} onChange={event => { setReplacement(event.target.value); setConfirming(false); }} />
    <label className="flex gap-2"><input type="checkbox" checked={ranges} onChange={event => setRanges(event.target.checked)} />Ranges</label>
    <label className="flex gap-2"><input type="checkbox" checked={workspaces} onChange={event => setWorkspaces(event.target.checked)} />Workspaces</label>
    <Button disabled={!replacement || (!ranges && !workspaces) || mutation.isPending} onClick={() => setConfirming(true)}>Review ownership transfer</Button>
    <AdministrationError error={mutation.error} />
    {confirming ? <Button disabled={mutation.isPending} onClick={() => mutation.mutate({ replacement_user_id: Number(replacement), resource_kinds: [...(ranges ? ["ranges" as const] : []), ...(workspaces ? ["workspaces" as const] : [])] })}>Confirm offboarding transfer</Button> : null}
    {mutation.data ? <output>Ranges transferred: {mutation.data.ranges_reassigned}; blocked: {mutation.data.ranges_blocked}. Workspaces transferred: {mutation.data.workspaces_transferred}; blocked: {mutation.data.workspaces_blocked}.</output> : null}
  </AdministrationSection>;
}

function ScopedOrganizerForm({ userId }: Readonly<{ userId: number }>) {
  const [kind, setKind] = useState<AdministrationSchemas["ScopedOrganizerCommand"]["target_type"]>("account");
  const [uuid, setUuid] = useState("");
  const mutation = useRelationshipMutation<Omit<AdministrationSchemas["ScopedOrganizerCommand"], "idempotency_key">>(`/administer/users/${userId}/grant-organizer/`);
  const original = mutation.variables?.body;
  const originalScope = original ? { kind: original.target_type, uuid: original.target_uuid } : "";
  const operation = useAuthorizationOperation(originalScope, mutation.data?.operation_id ?? "",
    mutation.data?.state === "requested" || mutation.data?.state === "unresolved");
  const state = operation.data?.state ?? mutation.data?.state;
  const locked = mutation.isPending || mutation.uncertain || state === "requested" || state === "unresolved";
  return <AdministrationSection title="Scoped event creation">
    <p>Assign permission to create events under one actual account, organization or workspace. Manage revocation and other event permissions under Policies and groups.</p>
    <form className="space-y-3" onSubmit={event => { event.preventDefault(); mutation.mutate({ target_type: kind, target_uuid: uuid }); }}>
      <fieldset className="space-y-3" disabled={locked}><Label htmlFor="organizer-scope-kind">Event creation scope</Label><select id="organizer-scope-kind" value={kind} onChange={event => setKind(event.target.value as typeof kind)}><option value="account">Account</option><option value="organization">Organization</option><option value="workspace">Workspace</option></select>
      <Label htmlFor="organizer-target">Scope UUID</Label><Input id="organizer-target" value={uuid} required onChange={event => setUuid(event.target.value)} />
      <Button type="submit" disabled={locked || !uuid}>Assign event creation</Button></fieldset>
    </form>
    <AdministrationError error={mutation.error} />
    {mutation.uncertain ? <Button variant="outline" disabled={mutation.isPending} onClick={mutation.retryCommand}>Retry original assignment</Button> : null}
    <MutationOutcome workspaceUuid={originalScope} result={mutation.data} />
  </AdministrationSection>;
}

function PersonalCredentialAdministration({ principalUuid }: Readonly<{ principalUuid: string }>) {
  const [offset, setOffset] = useState(0);
  const page = useAdministrationQuery<AdministrationSchemas["PersonalCredentialPage"]>(`/administer/principals/${principalUuid}/personal-credentials/`, { offset, limit: 50 });
  return <AdministrationSection title="Personal credential administration">
    <p>Administrators can revoke personal credentials. Issuance and rotation require the credential owner’s browser session.</p>
    <AdministrationError error={page.error} />
    {page.isSuccess ? <><ul>{page.data.results.map(credential => <CredentialRevocation key={credential.credential_uuid} credential={credential} />)}</ul><Button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous personal credentials</Button><Button disabled={page.data.next_offset === null} onClick={() => setOffset(page.data.next_offset ?? offset)}>Next personal credentials</Button></> : null}
  </AdministrationSection>;
}

function CredentialRevocation({ credential }: Readonly<{ credential: AdministrationSchemas["PersonalCredential"] }>) {
  const [confirming, setConfirming] = useState(false);
  const revoke = useAdministrationMutation(`/administer/credentials/personal/${credential.credential_uuid}/revoke/`);
  return <li className="space-y-2 rounded border p-3"><p>{credential.name} · {credential.revoked_at ? "Revoked" : "Active"}</p><AdministrationError error={revoke.error} />
    <Button variant="outline" disabled={Boolean(credential.revoked_at) || revoke.isPending} onClick={() => setConfirming(true)}>Revoke {credential.name}</Button>
    {confirming ? <Button variant="destructive" disabled={revoke.isPending} onClick={() => revoke.mutate({})}>Confirm credential revocation</Button> : null}
  </li>;
}

function UserMetadataForm({ user }: Readonly<{ user: AdministrationSchemas["PolicyAdminUserDetail"] }>) {
  const context = useAdministrationQuery<AdministrationSchemas["AccountPrincipalContext"]>("/accounts/context/");
  const ownsRecoveryEmail = context.data?.principal_kind === "human" && context.data.principal_uuid === user.principal_uuid;
  const [draft, setDraft] = useState<AdministrationSchemas["PatchedPolicyUserMetadataCommand"]>({});
  const save = useAdministrationMutation<unknown, AdministrationSchemas["PatchedPolicyUserMetadataCommand"]>(`/administer/users/${user.id}/`, "PATCH");
  const fields = { username: "Username", email: "User email", first_name: "First name", last_name: "Last name" } as const;
  return <form className="space-y-3" onSubmit={event => { event.preventDefault(); save.mutate(draft, { onSuccess: () => setDraft({}) }); }}>
    {Object.entries(fields).map(([field, label]) => <div key={field}><Label htmlFor={`user-${field}`}>{label}</Label><Input id={`user-${field}`} disabled={field === "email" && !ownsRecoveryEmail} value={draft[field as keyof typeof fields] ?? user[field as keyof typeof fields] ?? ""} onChange={event => setDraft(current => ({ ...current, [field]: event.target.value }))} /></div>)}
    {ownsRecoveryEmail ? null : <p>The account owner must change their recovery email in their own browser session.</p>}
    <Button type="submit" disabled={save.isPending || Object.keys(draft).length === 0}>Save user profile</Button><AdministrationError error={save.error} />
  </form>;
}
