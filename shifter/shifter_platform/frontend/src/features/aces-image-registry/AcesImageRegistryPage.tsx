import { useId, useState, type FormEvent } from "react";

import { useAcesImageMappings, useDisableAcesImageMapping, useRegisterAcesImageMapping } from "@/api/aces-image-registry";
import { describeMutationError } from "@/api/errors";
import { ACES_IMAGE_PROVIDERS, type AcesImageMapping, type AcesImageProvider } from "@/api/types";
import { useBootstrapContext } from "@/app/bootstrap-context";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";

/**
 * Tenant/operator surface for the ACES image registry (#1566): register a
 * mapping from an authored ACES `source` (name + optional version) to a concrete
 * provider image, list existing mappings, and soft-disable one (disable is not
 * delete). All writes go through the CMS API, which delegates to the single
 * validated `engine.services` write path; this page is UI only and the API
 * remains the authority (it is CMS-authoring gated and 404s unless the ACES
 * native path is enabled).
 */
export function AcesImageRegistryPage() {
  const bootstrap = useBootstrapContext();
  const canAuthor = bootstrap.permissions.can_access_threat_research;
  const query = useAcesImageMappings(true);

  return (
    <>
      <PageHeader
        title="ACES image registry"
        description="Map authored ACES image sources to concrete provider images used at realization."
      />
      {canAuthor ? <RegisterForm /> : null}
      <Card className="overflow-hidden py-0" aria-busy={query.isFetching}>
        <MappingsTable query={query} canAuthor={canAuthor} />
      </Card>
    </>
  );
}

function RegisterForm() {
  const ids = {
    provider: useId(),
    sourceName: useId(),
    sourceVersion: useId(),
    imageRef: useId(),
    machineType: useId(),
    diskSizeGb: useId(),
    diskType: useId(),
    notes: useId(),
  };
  const register = useRegisterAcesImageMapping();

  const [provider, setProvider] = useState<AcesImageProvider>("gce");
  const [sourceName, setSourceName] = useState("");
  const [sourceVersion, setSourceVersion] = useState("");
  const [imageRef, setImageRef] = useState("");
  const [machineType, setMachineType] = useState("");
  const [diskSizeGb, setDiskSizeGb] = useState("");
  const [diskType, setDiskType] = useState("");
  const [notes, setNotes] = useState("");

  const serverError = describeMutationError(register.error, "The mapping could not be registered.");

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const parsedDisk = diskSizeGb.trim() ? Number(diskSizeGb) : null;
    register.mutate(
      {
        provider,
        source_name: sourceName,
        image_ref: imageRef,
        source_version: sourceVersion,
        machine_type: machineType,
        disk_size_gb: parsedDisk,
        disk_type: diskType,
        enabled: true,
        notes,
      },
      {
        onSuccess: () => {
          setSourceName("");
          setSourceVersion("");
          setImageRef("");
          setMachineType("");
          setDiskSizeGb("");
          setDiskType("");
          setNotes("");
        },
      },
    );
  }

  return (
    <Card className="mb-4 p-4">
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        <h2 className="text-sm font-semibold">Register a mapping</h2>
        {serverError ? (
          <Alert variant="destructive">
            <AlertTitle>Could not register mapping</AlertTitle>
            <AlertDescription>{serverError}</AlertDescription>
          </Alert>
        ) : null}
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor={ids.provider}>Provider</Label>
            <Select value={provider} onValueChange={(value) => setProvider(value as AcesImageProvider)}>
              <SelectTrigger id={ids.provider} className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ACES_IMAGE_PROVIDERS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={ids.sourceName}>Source name</Label>
            <Input
              id={ids.sourceName}
              value={sourceName}
              onChange={(event) => setSourceName(event.target.value)}
              placeholder="alpine"
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={ids.sourceVersion}>Source version</Label>
            <Input
              id={ids.sourceVersion}
              value={sourceVersion}
              onChange={(event) => setSourceVersion(event.target.value)}
              placeholder="3.19 (blank matches any version)"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={ids.imageRef}>Image ref</Label>
            <Input
              id={ids.imageRef}
              value={imageRef}
              onChange={(event) => setImageRef(event.target.value)}
              placeholder="projects/x/global/images/alpine-3-19"
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={ids.machineType}>Machine type</Label>
            <Input
              id={ids.machineType}
              value={machineType}
              onChange={(event) => setMachineType(event.target.value)}
              placeholder="Optional (backend default when blank)"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={ids.diskSizeGb}>Disk size (GB)</Label>
            <Input
              id={ids.diskSizeGb}
              type="number"
              min={1}
              value={diskSizeGb}
              onChange={(event) => setDiskSizeGb(event.target.value)}
              placeholder="Optional"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={ids.diskType}>Disk type</Label>
            <Input
              id={ids.diskType}
              value={diskType}
              onChange={(event) => setDiskType(event.target.value)}
              placeholder="Optional (backend default when blank)"
            />
          </div>
          <div className="space-y-1.5 sm:col-span-2">
            <Label htmlFor={ids.notes}>Notes</Label>
            <Textarea
              id={ids.notes}
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              placeholder="Optional"
              rows={2}
            />
          </div>
        </div>
        <Button type="submit" size="sm" disabled={register.isPending}>
          {register.isPending ? "Registering…" : "Register mapping"}
        </Button>
      </form>
    </Card>
  );
}

function MappingsTable({
  query,
  canAuthor,
}: Readonly<{ query: ReturnType<typeof useAcesImageMappings>; canAuthor: boolean }>) {
  const disableMutation = useDisableAcesImageMapping();

  if (query.isLoading) {
    return (
      <div className="space-y-3 p-4">
        {[0, 1, 2].map((row) => (
          <Skeleton key={row} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  if (query.isError) {
    return (
      <div className="p-4">
        <Alert variant="destructive">
          <AlertTitle>Could not load image mappings</AlertTitle>
          <AlertDescription>Please retry.</AlertDescription>
        </Alert>
      </div>
    );
  }

  const rows = query.data ?? [];
  if (rows.length === 0) {
    return (
      <div className="grid place-items-center px-6 py-16 text-center">
        <p className="text-sm font-medium">No image mappings yet</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Register the first mapping so authored ACES sources can realize to provider images.
        </p>
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead>Mapping</TableHead>
          <TableHead>Image ref</TableHead>
          <TableHead className="w-[120px]">Status</TableHead>
          {canAuthor ? <TableHead className="w-[100px]">Actions</TableHead> : null}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <MappingRow key={row.id} row={row} canAuthor={canAuthor} disableMutation={disableMutation} />
        ))}
      </TableBody>
    </Table>
  );
}

function MappingRow({
  row,
  canAuthor,
  disableMutation,
}: Readonly<{
  row: AcesImageMapping;
  canAuthor: boolean;
  disableMutation: ReturnType<typeof useDisableAcesImageMapping>;
}>) {
  const version = row.source_version || "*";
  const pending = disableMutation.isPending && disableMutation.variables?.source_name === row.source_name;
  return (
    <TableRow>
      <TableCell className="font-mono text-xs">
        {row.provider}:{row.source_name}@{version}
      </TableCell>
      <TableCell className="font-mono text-xs break-all">{row.image_ref}</TableCell>
      <TableCell>
        <Badge variant={row.enabled ? "default" : "secondary"}>{row.enabled ? "Enabled" : "Disabled"}</Badge>
      </TableCell>
      {canAuthor ? (
        <TableCell>
          {row.enabled ? (
            <Button
              size="sm"
              variant="outline"
              disabled={pending}
              onClick={() =>
                disableMutation.mutate({
                  provider: row.provider,
                  source_name: row.source_name,
                  source_version: row.source_version,
                })
              }
            >
              {pending ? "Disabling…" : "Disable"}
            </Button>
          ) : null}
        </TableCell>
      ) : null}
    </TableRow>
  );
}
