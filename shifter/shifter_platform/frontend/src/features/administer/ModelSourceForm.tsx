import { useEffect, useRef, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { describeMutationError } from "@/api/errors";
import { saveModelSource, sourceKey, type ModelSource, type SourceConfiguration } from "@/api/model-sources";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { SourceUserPicker } from "./SourceUserPicker";

const VERTEX = "vertex-v1";
const BEDROCK = "bedrock-v1";
const selectClass = "block rounded border bg-background p-2";

const providers = [
  [VERTEX, "Google Vertex AI"], [BEDROCK, "AWS Bedrock"], ["anthropic-v1", "Anthropic"],
  ["openai-v1", "OpenAI"], ["openrouter-v1", "OpenRouter"],
] as const;

const defaults: SourceConfiguration = {
  name: "", provider: VERTEX, authentication: "workload-identity", model: "", region: "", project: "",
  principal: "", count_region: "us", quota_identity: "", context_window_tokens: 200000, tokens_per_minute: 100000,
  input_price_per_million: 0, output_price_per_million: 0, currency: "USD", price_valid_until: "",
  allow_organization_members: false, allowed_user_ids: [], upstream_provider: "",
};

export function ModelSourceForm({ organization, source, onSaved }: Readonly<{
  organization: string; source?: ModelSource; onSaved: () => void;
}>) {
  const client = useQueryClient();
  const credentialRead = useRef(0);
  useEffect(() => () => { credentialRead.current += 1; }, []);
  const [fileError, setFileError] = useState("");
  const [config, setConfig] = useState<SourceConfiguration>(source?.configuration ?? defaults);
  const [apiKey, setApiKey] = useState("");
  const [cloudCredential, setCloudCredential] = useState<Record<string, unknown> | null>(null);
  const [accessKey, setAccessKey] = useState("");
  const [secretKey, setSecretKey] = useState("");
  const [sessionToken, setSessionToken] = useState("");
  const [individuals, setIndividuals] = useState(Boolean(source?.configuration.allowed_user_ids?.length));
  const [zeroPriceConfirmed, setZeroPriceConfirmed] = useState(false);
  const zeroPrice = config.input_price_per_million === 0 || config.output_price_per_million === 0;
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const cloud = config.provider === VERTEX || config.provider === BEDROCK;
  function field<K extends keyof SourceConfiguration>(name: K, value: SourceConfiguration[K]) {
    setConfig((prior) => ({ ...prior, [name]: value }));
  }
  function clearCredentials() { credentialRead.current += 1; setFileError(""); setApiKey(""); setCloudCredential(null); setAccessKey(""); setSecretKey(""); setSessionToken(""); }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (pending || (zeroPrice && !zeroPriceConfirmed)) return;
    setPending(true); setError(null);
    const credential = sourceCredential(config.provider, { apiKey, cloudCredential, accessKey, secretKey, sessionToken });
    clearCredentials();
    try {
      await saveModelSource(organization, { configuration: { ...config, quota_identity: cloud ? "cloud-account-region" : config.quota_identity }, ...(credential ? { credential } : {}) }, source);
      await Promise.all([client.invalidateQueries({ queryKey: sourceKey(organization) }),
        client.invalidateQueries({ queryKey: ["model-source-options"] })]);
      onSaved();
    } catch (error_) { setError(error_); } finally { setPending(false); }
  }
  const text = (name: keyof SourceConfiguration, label: string, required = true) => <div className="space-y-1" key={name}>
    <Label htmlFor={`source-${name}`}>{label}</Label>
    <Input id={`source-${name}`} value={String(config[name] ?? "")} required={required} disabled={pending}
      onChange={(event) => field(name, event.target.value)} />
  </div>;
  const number = (name: keyof SourceConfiguration, label: string, minimum = 0) => <div className="space-y-1" key={name}>
    <Label htmlFor={`source-${name}`}>{label}</Label>
    <Input id={`source-${name}`} type="number" min={minimum} step="1" value={Number(config[name])} required disabled={pending}
      onChange={(event) => field(name, Number(event.target.value))} />
  </div>;
  return <form aria-label="Model source" onSubmit={(event) => void submit(event)} className="space-y-4 rounded border p-4">
    <h2 className="text-lg font-semibold">{source ? "Edit model source" : "Add model source"}</h2>
    {error ? <Alert variant="destructive"><AlertDescription>{describeMutationError(error, "The model source could not be saved.")}</AlertDescription></Alert> : null}
    {text("name", "Source name")}
    <Label htmlFor="source-provider">Provider</Label>
    <select id="source-provider" className={selectClass} value={config.provider} disabled={pending}
      onChange={(event) => { const provider = event.target.value as SourceConfiguration["provider"]; clearCredentials();
        setConfig({ ...config, provider, authentication: [VERTEX, BEDROCK].includes(provider) ? "workload-identity" : "stored-credential",
          project: "", principal: "", region: [VERTEX, BEDROCK].includes(provider) ? "" : "provider-managed", count_region: provider === VERTEX ? "us" : "", upstream_provider: "" }); }}>
      {providers.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
    </select>
    {text("model", "Model ID")}
    {cloud ? text("region", "Data region") : <p>Data geography is managed by the provider. This source is available only where the scenario and tenant policy permit provider-managed processing.</p>}
    {config.provider === VERTEX ? <>
      {text("project", "Google Cloud project")}
      <p>You may use the project hosting Shifter or another project that authorizes this source.</p>
      {text("principal", "Invocation service account")}{text("count_region", "Token-count region")}
    </> : null}
    {config.provider === BEDROCK ? text("principal", "Invocation role ARN") : null}
    {config.provider === "openrouter-v1" ? text("upstream_provider", "Upstream provider") : null}
    {cloud ? <>
      <Label htmlFor="source-auth">Authentication</Label>
      <select id="source-auth" value={config.authentication} className={selectClass} disabled={pending}
        onChange={(event) => { clearCredentials(); field("authentication", event.target.value as SourceConfiguration["authentication"]); }}>
        <option value="workload-identity">Shifter’s approved invocation identity</option>
        <option value="stored-credential">Credentials for this source</option>
      </select>
    </> : <>
      <Label htmlFor="source-api-key">API key</Label>
      <Input id="source-api-key" type="password" autoComplete="new-password" value={apiKey} disabled={pending}
        required={!source?.has_credential} onChange={(event) => setApiKey(event.target.value)} />
    </>}
    {cloud && config.authentication === "stored-credential" && <CloudCredentialFields
      provider={config.provider} pending={pending} credentialAccessKey={accessKey} setAccessKey={setAccessKey}
      secretKey={secretKey} setSecretKey={setSecretKey} sessionToken={sessionToken} setSessionToken={setSessionToken}
      fileError={fileError} cloudCredential={cloudCredential} onFile={async (file) => {
        setCloudCredential(null); setFileError("");
        const read = ++credentialRead.current;
        if (!file) return;
        if (file.size > 32768) { setFileError("Choose a credential file no larger than 32 KiB."); return; }
        try { const value = JSON.parse(await file.text()); if (credentialRead.current === read) setCloudCredential(value); }
        catch { if (credentialRead.current === read) setFileError("Invalid credential file."); }
      }} />}
    {source?.has_credential ? <p>Leave credentials empty to keep the stored version.</p> : null}
    {cloud ? <p>Sources in the same cloud account and region share one application quota ceiling.</p> : <>{text("quota_identity", "Quota account identity")}
    <p>Use the same quota identity for sources that share the same provider limit.</p></>}
    {number("context_window_tokens", "Model context limit (tokens)", 1)}
    {number("tokens_per_minute", "Tokens per minute", 1)}
    {number("input_price_per_million", "Input price per million tokens (micro-units)")}
    {number("output_price_per_million", "Output price per million tokens (micro-units)")}
    <p>One currency unit equals 1,000,000 micro-units. Enter the account’s applicable prices.</p>
    {zeroPrice && <Label className="flex gap-2" htmlFor="source-zero-price"><input id="source-zero-price" type="checkbox" required
      checked={zeroPriceConfirmed} disabled={pending} onChange={(event) => setZeroPriceConfirmed(event.target.checked)} />
      <span>I confirm that zero-priced token components have no monetary charge reserved.</span>
    </Label>}
    <Label htmlFor="source-currency">Currency</Label>
    <select id="source-currency" value={config.currency} disabled={pending} className={selectClass}
      onChange={(event) => field("currency", event.target.value as SourceConfiguration["currency"])}>
      {["AUD", "CAD", "CHF", "EUR", "GBP", "JPY", "USD"].map((currency) => <option key={currency}>{currency}</option>)}
    </select>
    <Label htmlFor="source-price-date">Price valid until</Label>
    <Input id="source-price-date" type="date" required disabled={pending} value={config.price_valid_until.slice(0, 10)}
      onChange={(event) => field("price_valid_until", event.target.value ? `${event.target.value}T00:00:00Z` : "")} />
    <Label className="flex gap-2" htmlFor="source-members"><input id="source-members" type="checkbox" checked={config.allow_organization_members}
      disabled={pending} onChange={(event) => field("allow_organization_members", event.target.checked)} />Allow organization members to use this source</Label>
    <Button type="button" variant="outline" disabled={pending} onClick={() => setIndividuals(!individuals)}>{individuals ? "Hide individual grants" : "Authorize individual users"}</Button>
    {individuals && <SourceUserPicker organization={organization} selected={config.allowed_user_ids ?? []} onChange={(ids) => field("allowed_user_ids", ids)} disabled={pending} />}
    <p>Registration alone does not authorize users to spend from this account.</p>
    <Button type="submit" disabled={pending}>{pending ? "Saving…" : "Save model source"}</Button>
  </form>;
}


interface Credentials {
  apiKey: string;
  cloudCredential: Record<string, unknown> | null;
  accessKey: string;
  secretKey: string;
  sessionToken: string;
}

function sourceCredential(provider: SourceConfiguration["provider"], values: Credentials): Record<string, unknown> | null {
  if (provider === VERTEX) return values.cloudCredential;
  if (provider === BEDROCK) {
    if (!values.accessKey || !values.secretKey) return null;
    return { access_key_id: values.accessKey, secret_access_key: values.secretKey,
      ...(values.sessionToken ? { session_token: values.sessionToken } : {}) };
  }
  return values.apiKey ? { api_key: values.apiKey } : null;
}

function CloudCredentialFields({ provider, pending, credentialAccessKey, setAccessKey, secretKey, setSecretKey,
  sessionToken, setSessionToken, fileError, cloudCredential, onFile }: Readonly<{
  provider: SourceConfiguration["provider"]; pending: boolean;
  credentialAccessKey: string; setAccessKey: (value: string) => void;
  secretKey: string; setSecretKey: (value: string) => void;
  sessionToken: string; setSessionToken: (value: string) => void;
  fileError: string; cloudCredential: Record<string, unknown> | null;
  onFile: (file: File | undefined) => Promise<void>;
}>) {
  if (provider === VERTEX) return <>
    <Label htmlFor="source-account-file">Service account credential file</Label>
    <Input id="source-account-file" type="file" accept="application/json,.json" disabled={pending} onChange={(event) => {
      const file = event.target.files?.[0]; event.target.value = ""; void onFile(file);
    }} />
    {fileError && <p role="alert">{fileError}</p>}
    {cloudCredential ? <p>Credential file ready to submit.</p> : null}
  </>;
  return <>
    <Label htmlFor="source-access-key">Access key ID</Label>
    <Input id="source-access-key" value={credentialAccessKey} autoComplete="off" disabled={pending} onChange={(event) => setAccessKey(event.target.value)} />
    <Label htmlFor="source-secret-key">Secret access key</Label>
    <Input id="source-secret-key" type="password" value={secretKey} autoComplete="new-password" disabled={pending} onChange={(event) => setSecretKey(event.target.value)} />
    <Label htmlFor="source-session-token">Session token (temporary credentials)</Label>
    <Input id="source-session-token" type="password" autoComplete="new-password" value={sessionToken} disabled={pending} onChange={(event) => setSessionToken(event.target.value)} />
  </>;
}
