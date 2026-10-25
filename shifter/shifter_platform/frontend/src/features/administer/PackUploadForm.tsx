import { useState } from "react";

import { useUploadPack, type AdapterPack } from "@/api/adapter-packs";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function PackUploadForm({ organization, packs }: Readonly<{ organization: string; packs: AdapterPack[] }>) {
  const [name, setName] = useState("");
  const [replacement, setReplacement] = useState("");
  const [archive, setArchive] = useState<File | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [fileKey, setFileKey] = useState(0);
  const upload = useUploadPack(organization);
  const previous = packs.find((pack) => pack.id === replacement);
  const packName = previous?.name ?? name;
  const valid = (!replacement || Boolean(previous)) && /^[A-Za-z0-9_-]{1,100}$/.test(packName) && archive !== null && archive.size > 0;
  return <section className="mb-6 space-y-3" aria-label="Install a content pack">
    <h2 className="text-lg font-semibold">Install a content pack</h2>
    <p>Upload the pack author’s archive. Shifter validates the content before making it available to your organization.
      Install and assign its adapter separately.</p>
    <Label htmlFor="pack-upload-revision">Installation</Label>
    <select id="pack-upload-revision" value={replacement} disabled={upload.isPending}
      className="block rounded border bg-background p-2" onChange={(event) => { setReplacement(event.target.value); upload.reset(); }}>
      <option value="">Install a new pack</option>
      {packs.filter((pack) => pack.can_update).map((pack) =>
        <option key={pack.id} value={pack.id}>Update {pack.name}</option>)}
    </select>
    <Label htmlFor="pack-upload-name">Pack name</Label>
    <Input id="pack-upload-name" value={packName} disabled={upload.isPending || Boolean(previous)}
      onChange={(event) => { setName(event.target.value); upload.reset(); }} placeholder="Name provided by the pack author" />
    <Label htmlFor="pack-upload-file">Pack archive (.tar or .tar.gz)</Label>
    <Input key={fileKey} id="pack-upload-file" type="file" accept=".tar,.tar.gz,.tgz" disabled={upload.isPending}
      onChange={(event) => { setArchive(event.target.files?.[0] ?? null); upload.reset(); }} />
    <Button disabled={!valid || upload.isPending} onClick={() => setConfirm(true)}>Review pack installation</Button>
    {upload.isSuccess ? <output className="block">Installed {upload.data.name} version {upload.data.package_version}.
      Assign an adapter below if this pack requires one.</output> : null}
    <ConfirmDialog open={confirm} onOpenChange={(open) => { if (!upload.isPending) setConfirm(open); }}
      title={previous ? "Install this pack update?" : "Install this content pack?"}
      confirmLabel="Install pack" pending={upload.isPending} error={upload.error} confirmDisabled={!valid}
      onConfirm={() => {
        if (!archive || !valid) return;
        const body = new FormData();
        body.append("name", packName); body.append("archive", archive);
        if (previous) body.append("expected_digest", previous.pack_digest);
        upload.mutate(body, { onSuccess: () => { setConfirm(false); setArchive(null); setFileKey((key) => key + 1); } });
      }}>
      {archive?.name} will be installed for this organization. Content validation does not run an adapter or start a range.
      {previous ? " Existing ranges keep their original version. Review and rebind the adapter for new launches after updating." : ""}
    </ConfirmDialog>
  </section>;
}
