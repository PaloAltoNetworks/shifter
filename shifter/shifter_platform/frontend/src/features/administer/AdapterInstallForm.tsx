import { useRef, useState, type FormEvent } from "react";

import { useInstallAdapter } from "@/api/adapters";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { manifestPreview } from "./adapter-manifest";

const MAX_MANIFEST_BYTES = 65_536;

export function AdapterInstallForm({ organization }: Readonly<{ organization: string }>) {
  const install = useInstallAdapter(organization);
  const [manifest, setManifest] = useState<unknown>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [review, setReview] = useState(false);
  const [success, setSuccess] = useState(false);
  const fileGeneration = useRef(0);
  const fileInput = useRef<HTMLInputElement>(null);
  const preview = manifestPreview(manifest);
  const validCredentials = Boolean(username) === Boolean(password);

  async function readManifest(file: File | undefined) {
    const generation = ++fileGeneration.current;
    setManifest(null); setError(null); setSuccess(false);
    if (!file) return;
    if (file.size > MAX_MANIFEST_BYTES) {
      setError("Choose a plugin manifest no larger than 64 KiB.");
      return;
    }
    try {
      const value: unknown = JSON.parse(await file.text());
      if (generation !== fileGeneration.current) return;
      if (!manifestPreview(value)) {
        setError("This is not a plugin manifest. Ask the plugin author for the installation file.");
        return;
      }
      setManifest(value);
    } catch {
      if (generation === fileGeneration.current) setError("The plugin manifest could not be read.");
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (preview && validCredentials) { install.reset(); setReview(true); }
  }

  return (
    <Card className="mb-6">
      <CardHeader><CardTitle>Install a plugin</CardTitle></CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-4">
          <p>Upload the plugin author&apos;s installation file. Shifter checks compatibility before enabling this version.</p>
          {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
          {success ? <output className="block">Installation started. Compatibility checks are running.</output> : null}
          <Label htmlFor="adapter-manifest">Plugin installation file</Label>
          <Input id="adapter-manifest" ref={fileInput} type="file" accept="application/json,.json"
            disabled={review || install.isPending} onChange={(event) => void readManifest(event.target.files?.[0])} />
          <details>
            <summary>Private registry sign-in (optional)</summary>
            <div className="mt-3 space-y-2">
              <Label htmlFor="registry-username">Registry username</Label>
              <Input id="registry-username" autoComplete="off" value={username} disabled={review || install.isPending}
                onChange={(event) => setUsername(event.target.value)} />
              <Label htmlFor="registry-password">Registry password or access token</Label>
              <Input id="registry-password" type="password" autoComplete="new-password" value={password}
                disabled={review || install.isPending} onChange={(event) => setPassword(event.target.value)} />
              {validCredentials ? null : <p>Enter both the registry username and password or access token.</p>}
            </div>
          </details>
          {preview ? <dl className="grid gap-2 break-all text-sm" aria-label="Plugin installation details">
            <dt className="font-semibold">Plugin</dt><dd>{preview.plugin_id} · {preview.version}</dd>
            <dt className="font-semibold">Protocol</dt><dd>{preview.protocol}</dd>
            <dt className="font-semibold">Executable image</dt><dd>{preview.worker_image}</dd>
            <dt className="font-semibold">Requested capabilities</dt><dd>{preview.capabilities.join(", ")}</dd>
            {Object.keys(preview.model_bindings ?? {}).length ? <>
              <dt className="font-semibold">Model access</dt><dd>{Object.keys(preview.model_bindings ?? {}).join(", ")}
                {" · Subject to deployment policy and budget"}</dd>
            </> : null}
          </dl> : null}
          <Button type="submit" disabled={!preview || !validCredentials || install.isPending}>Review installation</Button>
        </form>
        <ConfirmDialog open={review} onOpenChange={(open) => { if (!install.isPending) setReview(open); }}
          title="Install this plugin?" confirmLabel="Install plugin" pending={install.isPending} error={install.error}
          onConfirm={() => install.mutate({ manifest,
            ...(username && password ? { registry_credentials: { username, password } } : {}),
          }, { onSuccess: () => {
            setReview(false); setSuccess(true); setManifest(null); setUsername(""); setPassword("");
            if (fileInput.current) fileInput.current.value = "";
          } })}>
          {preview?.plugin_id} {preview?.version} will be installed for this organization.
          The requested guest actions can run only after you bind this version to a pack.
        </ConfirmDialog>
      </CardContent>
    </Card>
  );
}
