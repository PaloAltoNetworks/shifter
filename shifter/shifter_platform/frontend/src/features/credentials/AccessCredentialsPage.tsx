import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { usePersonalCredentials, type PersonalCommand, type IssuedCredential } from "@/api/access-credentials";
import { useAuthorizationCatalog } from "@/api/authorization";
import { apiFetch } from "@/api/client";
import { describeMutationError } from "@/api/errors";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ServiceCredentialsPanel } from "./ServiceCredentialsPanel";

export function AccessCredentialsPage() {
  return <>
    <PageHeader title="Access credentials" description="Manage personal tokens and independent service identities." />
    <PersonalCredentialsPanel />
    <ServiceCredentialsPanel />
  </>;
}

function PersonalCredentialsPanel() {
  const [offset, setOffset] = useState(0);
  const credentials = usePersonalCredentials(offset);
  const catalog = useAuthorizationCatalog();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [action, setAction] = useState("");
  const [targetUuid, setTargetUuid] = useState("");
  const [expiry, setExpiry] = useState("");
  const [rotation, setRotation] = useState<string | null>(null);
  const [secret, setSecret] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const definition = catalog.data?.find(item => item.code === action);
  const actions = (catalog.data ?? []).filter(item => !["installation.use_personal_tokens", "installation.manage_service_credentials"].includes(item.code));
  const queryError = describeMutationError(credentials.error ?? catalog.error, "Credential metadata could not be loaded.");

  async function issue() {
    if (!definition) return;
    setBusy(true); setError(""); setSecret("");
    try {
      const body: PersonalCommand = { name, scopes: [`authorization:${action}` as PersonalCommand["scopes"][number]],
        expires_at: new Date(expiry).toISOString(), target_type: definition.target_type as PersonalCommand["target_type"],
        target_uuid: definition.target_type === "installation" ? null : targetUuid };
      const path = rotation ? `/credentials/personal/${rotation}/rotate/` : "/credentials/personal/";
      // Direct call: raw proof never becomes mutation.data or a query value.
      const issued = await apiFetch<IssuedCredential>(path, { method: "POST", body });
      setSecret(issued.token); setRotation(null);
      await queryClient.invalidateQueries({ queryKey: ["access-credentials", "personal"] });
    } catch (error_) { setError(describeMutationError(error_, "Token issuance denied.") ?? "Token issuance denied."); }
    finally { setBusy(false); }
  }

  async function revoke(uuid: string) {
    setBusy(true); setError(""); setSecret("");
    try {
      await apiFetch(`/credentials/personal/${uuid}/revoke/`, { method: "POST", body: {} });
      await queryClient.invalidateQueries({ queryKey: ["access-credentials", "personal"] });
    } catch (error_) { setError(describeMutationError(error_, "Revocation failed.") ?? "Revocation failed."); }
    finally { setBusy(false); }
  }

  return <section aria-labelledby="personal-credentials" className="space-y-4 mb-10">
    <h2 id="personal-credentials" className="text-xl font-semibold">Personal tokens</h2>
    <p>Issuance and use require your live personal-token grant. A token cannot exceed your current authority or create more credentials. You can still revoke your own tokens after losing issuance rights.</p>
    {queryError || error ? <p role="alert">{error || queryError}</p> : null}
    {credentials.isPending ? <output>Loading tokens…</output> : null}
    {secret ? <div className="space-y-2 rounded border p-4">
      <Label htmlFor="one-time-token">Copy this token now. It will not be shown again.</Label>
      <Input id="one-time-token" readOnly value={secret} autoComplete="off" />
      <Button onClick={() => setSecret("")}>Dismiss secret</Button>
    </div> : null}
    <form className="grid gap-3 max-w-xl" onSubmit={event => { event.preventDefault(); void issue(); }}>
      <Label htmlFor="token-name">Token name</Label><Input id="token-name" value={name} onChange={event => setName(event.target.value)} required maxLength={100} />
      <Label htmlFor="token-action">Token action</Label>
      <select id="token-action" className="rounded border bg-background p-2" value={action} onChange={event => setAction(event.target.value)} required>
        <option value="">Select an action</option>{actions.map(item => <option key={item.code} value={item.code}>{item.code}</option>)}
      </select>
      {definition && definition.target_type !== "installation" ? <><Label htmlFor="token-target">{definition.target_type} UUID</Label><Input id="token-target" value={targetUuid} onChange={event => setTargetUuid(event.target.value)} required /></> : null}
      <Label htmlFor="token-expiry">Expires at</Label><Input id="token-expiry" type="datetime-local" value={expiry} onChange={event => setExpiry(event.target.value)} required />
      <p>The server enforces the configured maximum lifetime. Rotation atomically revokes the selected old token.</p>
      <Button disabled={busy || !definition} type="submit">{rotation ? "Rotate token" : "Issue token"}</Button>
      {rotation ? <Button variant="outline" type="button" onClick={() => setRotation(null)}>Cancel rotation</Button> : null}
    </form>
    {credentials.data?.results.length === 0 ? <p>No personal tokens.</p> : null}
    <ul className="space-y-3">{credentials.data?.results.map(token => <li key={token.credential_uuid} className="rounded border p-3">
      <h3>{token.name}</h3><p className="break-all">{token.credential_uuid}</p><p>{token.scopes.join(", ")}</p>
      <p className="break-all">Target: {token.target_type || "legacy"} {token.target_uuid ?? ""}</p>
      <p>{token.revoked_at ? "Revoked" : `Expires: ${token.expires_at ?? "legacy"}`}</p>
      {token.requires_reissue ? <p>Legacy token: reissue required at S8; this proof is not accepted.</p> : null}
      <div className="flex gap-2"><Button variant="outline" disabled={busy || Boolean(token.revoked_at)} onClick={() => { setRotation(token.credential_uuid); setName(token.name); setSecret(""); }}>Select for rotation</Button>
      <Button variant="outline" disabled={busy || Boolean(token.revoked_at)} onClick={() => void revoke(token.credential_uuid)}>Revoke {token.name}</Button></div>
    </li>)}</ul>
    <nav aria-label="Personal token pages" className="flex gap-2"><Button variant="outline" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous tokens</Button><Button variant="outline" disabled={credentials.data?.next_offset == null} onClick={() => setOffset(credentials.data?.next_offset ?? offset)}>Next tokens</Button></nav>
  </section>;
}
