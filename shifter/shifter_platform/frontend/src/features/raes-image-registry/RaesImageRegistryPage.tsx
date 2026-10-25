import { useId, useState, type FormEvent } from "react";

import {
  useRaesImageMappings,
  useDisableRaesImageMapping,
  useRegisterRaesImageMapping,
} from "@/api/raes-image-registry";
import { describeMutationError } from "@/api/errors";
import {
  RAES_IMAGE_PROVIDERS,
  type RaesImageMapping,
  type RaesImageProvider,
} from "@/api/types";
import { useBootstrapContext } from "@/app/bootstrap-context";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";

const MACHINE_IMAGE_KIND = "machine-image";

/**
 * Tenant/operator surface for the RAES image registry (#1566): register a
 * mapping from an authored RAES `source` (name + optional version) to a concrete
 * provider image, list existing mappings, and soft-disable one (disable is not
 * delete). All writes go through the CMS API, which delegates to the single
 * validated `engine.services` write path; this page is UI only and the API
 * remains the authority (it is CMS-authoring gated and 404s unless the RAES
 * native path is enabled).
 */
export function RaesImageRegistryPage() {
  const bootstrap = useBootstrapContext();
  const canAuthor = bootstrap.permissions.can_access_threat_research;
  const query = useRaesImageMappings(true);

  return (
    <>
      <PageHeader
        title="RAES image registry"
        description="Map authored RAES image sources to concrete provider images used at realization."
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
    imageKind: useId(),
    machineType: useId(),
    diskSizeGb: useId(),
    diskType: useId(),
    managementPort: useId(),
    managementUser: useId(),
    participantContainer: useId(),
    participantUser: useId(),
    readinessContract: useId(),
    readinessDigest: useId(),
    notes: useId(),
  };
  const register = useRegisterRaesImageMapping();

  const [provider, setProvider] = useState<RaesImageProvider>("gce");
  const [sourceName, setSourceName] = useState("");
  const [sourceVersion, setSourceVersion] = useState("");
  const [imageRef, setImageRef] = useState("");
  const [imageKind, setImageKind] = useState<"image" | "machine-image">("image");
  const [preconfiguredHost, setPreconfiguredHost] = useState(false);
  const [machineType, setMachineType] = useState("");
  const [diskSizeGb, setDiskSizeGb] = useState("");
  const [diskType, setDiskType] = useState("");
  const [managementUser, setManagementUser] = useState("");
  const [managementPort, setManagementPort] = useState("22");
  const [participantContainer, setParticipantContainer] = useState("");
  const [participantUser, setParticipantUser] = useState("");
  const [readinessContract, setReadinessContract] = useState("participant-readiness/v1");
  const [readinessDigest, setReadinessDigest] = useState("");
  const [notes, setNotes] = useState("");

  const serverError = describeMutationError(
    register.error,
    "The mapping could not be registered.",
  );

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
        management_ssh_port: Number(managementPort),
        management_ssh_username: managementUser,
        image_kind: imageKind,
        bootstrap_capability: preconfiguredHost || imageKind === MACHINE_IMAGE_KIND ? "preconfigured-machine-host" : "standard",
        participant_container_name: preconfiguredHost || imageKind === MACHINE_IMAGE_KIND ? participantContainer : "",
        participant_username: preconfiguredHost || imageKind === MACHINE_IMAGE_KIND ? participantUser : "",
        participant_readiness_contract: preconfiguredHost || imageKind === MACHINE_IMAGE_KIND ? readinessContract : "",
        participant_readiness_manifest_sha256: preconfiguredHost || imageKind === MACHINE_IMAGE_KIND ? readinessDigest : "",
        enabled: true,
        notes,
        // This form registers a legacy alias-only mapping; portable RAES artifact
        // identity (#1580) is admitted through the API/CLI, so the optional
        // identity + evidence fields are left blank here.
        artifact_id: "",
        artifact_version: "",
        artifact_digest: "",
        media_type: "",
        integrity_ref: "",
        provenance_ref: "",
      },
      {
        onSuccess: () => {
          setSourceName("");
          setSourceVersion("");
          setImageRef("");
          setImageKind("image");
          setPreconfiguredHost(false);
          setMachineType("");
          setDiskSizeGb("");
          setDiskType("");
          setManagementPort("22");
          setManagementUser("");
          setParticipantContainer("");
          setParticipantUser("");
          setReadinessContract("participant-readiness/v1");
          setReadinessDigest("");
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
            <Select
              value={provider}
              onValueChange={(value) => setProvider(value as RaesImageProvider)}
            >
              <SelectTrigger id={ids.provider} className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {RAES_IMAGE_PROVIDERS.map((option) => (
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
            <Label htmlFor={ids.imageKind}>Image type</Label>
            <Select value={imageKind} onValueChange={(value) => setImageKind(value as "image" | "machine-image")}>
              <SelectTrigger id={ids.imageKind} className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="image">Boot image</SelectItem>
                <SelectItem value={MACHINE_IMAGE_KIND}>Preconfigured machine host</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {imageKind === "image" ? <div className="flex items-center gap-2">
            <input id="preconfigured-host" type="checkbox" checked={preconfiguredHost}
              onChange={(event) => setPreconfiguredHost(event.target.checked)} />
            <Label htmlFor="preconfigured-host">Preconfigured participant host</Label>
          </div> : null}
          <div className="space-y-1.5">
            <Label htmlFor={ids.imageRef}>Image ref</Label>
            <Input
              id={ids.imageRef}
              value={imageRef}
              onChange={(event) => setImageRef(event.target.value)}
              placeholder={imageKind === MACHINE_IMAGE_KIND
                ? "projects/x/global/machineImages/training-host"
                : "projects/x/global/images/alpine-3-19"}
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
          {preconfiguredHost || imageKind === MACHINE_IMAGE_KIND ? <>
            <div className="space-y-1.5">
              <Label htmlFor={ids.participantContainer}>Participant container</Label>
              <Input id={ids.participantContainer} value={participantContainer} maxLength={128} required
                onChange={(event) => setParticipantContainer(event.target.value)} placeholder="participant-desktop" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor={ids.participantUser}>Participant username</Label>
              <Input id={ids.participantUser} value={participantUser} maxLength={32} required
                onChange={(event) => setParticipantUser(event.target.value)} placeholder="student" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor={ids.readinessContract}>Readiness contract</Label>
              <Input id={ids.readinessContract} value={readinessContract} readOnly />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor={ids.readinessDigest}>Readiness manifest SHA-256</Label>
              <Input id={ids.readinessDigest} value={readinessDigest} minLength={64} maxLength={64} required
                onChange={(event) => setReadinessDigest(event.target.value)} placeholder="64 lowercase hex characters" />
            </div>
          </> : null}
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
          <div className="space-y-1.5">
            <Label htmlFor={ids.managementPort}>Management SSH port</Label>
            <Input
              id={ids.managementPort}
              type="number"
              min={1}
              max={65535}
              value={managementPort}
              onChange={(event) => setManagementPort(event.target.value)}
              required
            />
            <p className="text-muted-foreground text-xs">
              SSH port baked into the host image for provisioning. Participant
              access is configured separately.
            </p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={ids.managementUser}>Management SSH username</Label>
            <Input
              id={ids.managementUser}
              value={managementUser}
              maxLength={32}
              onChange={(event) => setManagementUser(event.target.value)}
              placeholder="Backend default"
            />
            <p className="text-muted-foreground text-xs">
              Existing local administrator account required by the image, if
              any.
            </p>
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
}: Readonly<{
  query: ReturnType<typeof useRaesImageMappings>;
  canAuthor: boolean;
}>) {
  const disableMutation = useDisableRaesImageMapping();

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
          Register the first mapping so authored RAES sources can realize to
          provider images.
        </p>
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead>Mapping</TableHead>
          <TableHead>Image</TableHead>
          <TableHead>Management SSH port</TableHead>
          <TableHead className="w-[120px]">Status</TableHead>
          {canAuthor ? (
            <TableHead className="w-[100px]">Actions</TableHead>
          ) : null}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <MappingRow
            key={row.id}
            row={row}
            canAuthor={canAuthor}
            disableMutation={disableMutation}
          />
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
  row: RaesImageMapping;
  canAuthor: boolean;
  disableMutation: ReturnType<typeof useDisableRaesImageMapping>;
}>) {
  const version = row.source_version || "*";
  const pending =
    disableMutation.isPending &&
    disableMutation.variables?.source_name === row.source_name;
  return (
    <TableRow>
      <TableCell className="font-mono text-xs">
        {row.provider}:{row.source_name}@{version}
      </TableCell>
      <TableCell className="font-mono text-xs break-all">
        <span className="block">{row.image_ref}</span>
        <span className="text-muted-foreground">{row.image_kind === MACHINE_IMAGE_KIND ? "Machine host" : "Boot image"}</span>
      </TableCell>
      <TableCell>
        {row.management_ssh_username || "Default"}:{row.management_ssh_port}
      </TableCell>
      <TableCell>
        <Badge variant={row.enabled ? "default" : "secondary"}>
          {row.enabled ? "Enabled" : "Disabled"}
        </Badge>
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
