import { useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { useMutation } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { useBootstrapContext } from "@/app/bootstrap-context";
import {
  fetchScenarioExport,
  useCloneScenario,
  useDeleteScenario,
  useScenario,
  useUpdateScenarioMetadata,
} from "@/api/scenarios";
import type { ScenarioDetail } from "@/api/types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

import { EnabledBadge, SourceBadge, StaffOnlyBadge } from "./badges";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { downloadTextFile } from "./format";
import { scenarioEditPath, scenarioListPath, scenarioYamlEditPath } from "./routes";

function Field({ label, children }: Readonly<{ label: string; children: ReactNode }>) {
  return (
    <div className="grid grid-cols-[150px_1fr] gap-4 border-b border-border/60 py-3 last:border-0">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}

type MetadataMutation = ReturnType<typeof useUpdateScenarioMetadata>;

function ScenarioActions({
  scenario,
  metadata,
  exporting,
  onExport,
  onClone,
  onDelete,
}: Readonly<{
  scenario: ScenarioDetail;
  metadata: MetadataMutation;
  exporting: boolean;
  onExport: () => void;
  onClone: () => void;
  onDelete: () => void;
}>) {
  return (
    <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
      {scenario.editable ? (
        <>
          <Link className={cn(buttonVariants({ variant: "outline", size: "sm" }))} to={scenarioEditPath(scenario.id)}>
            Edit
          </Link>
          <Link
            className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
            to={scenarioYamlEditPath(scenario.id)}
          >
            Edit YAML
          </Link>
        </>
      ) : null}
      <Button variant="outline" size="sm" onClick={onClone}>
        Clone
      </Button>
      {scenario.exportable ? (
        <Button variant="outline" size="sm" onClick={onExport} disabled={exporting}>
          Export YAML
        </Button>
      ) : null}
      <Button
        variant="outline"
        size="sm"
        onClick={() => metadata.mutate({ enabled: !scenario.enabled })}
        disabled={metadata.isPending}
      >
        {scenario.enabled ? "Disable" : "Enable"}
      </Button>
      <Button
        variant="outline"
        size="sm"
        onClick={() => metadata.mutate({ staff_only: !scenario.staff_only })}
        disabled={metadata.isPending}
      >
        {scenario.staff_only ? "Make available to all" : "Make staff-only"}
      </Button>
      {scenario.deletable ? (
        <Button variant="destructive" size="sm" onClick={onDelete}>
          Delete
        </Button>
      ) : null}
    </div>
  );
}

function OverviewCard({ scenario }: Readonly<{ scenario: ScenarioDetail }>) {
  return (
    <Card>
      <CardContent>
        <dl>
          <Field label="Source">
            <SourceBadge source={scenario.source} />
          </Field>
          <Field label="Type">{scenario.scenario_type}</Field>
          <Field label="Availability">
            <div className="flex flex-wrap items-center gap-1.5">
              <EnabledBadge enabled={scenario.enabled} />
              {scenario.staff_only ? <StaffOnlyBadge /> : null}
            </div>
          </Field>
          <Field label="Launchable">{scenario.launchable ? "Yes" : "No"}</Field>
          <Field label="NGFW">{scenario.ngfw ? "Required" : "Not required"}</Field>
          <Field label="Description">
            <p className="whitespace-pre-wrap">{scenario.description || "—"}</p>
          </Field>
        </dl>
      </CardContent>
    </Card>
  );
}

function InstancesCard({ scenario }: Readonly<{ scenario: ScenarioDetail }>) {
  if (scenario.instances.length === 0) return null;
  return (
    <Card className="mt-6 overflow-hidden py-0">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Instance</TableHead>
            <TableHead className="w-[120px]">Role</TableHead>
            <TableHead className="w-[130px]">OS</TableHead>
            <TableHead className="w-[100px]">XDR</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {scenario.instances.map((instance) => (
            <TableRow key={instance.name}>
              <TableCell className="font-medium">{instance.name}</TableCell>
              <TableCell>{instance.role}</TableCell>
              <TableCell>{instance.os_type}</TableCell>
              <TableCell>{instance.xdr_agent ? "Yes" : "No"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  );
}

function SubnetsCard({ scenario }: Readonly<{ scenario: ScenarioDetail }>) {
  if (scenario.subnets.length === 0) return null;
  return (
    <Card className="mt-6">
      <CardContent>
        <h2 className="mb-3 text-sm font-semibold">Subnets</h2>
        <ul className="flex flex-col gap-2 text-sm">
          {scenario.subnets.map((subnet) => (
            <li key={subnet.name}>
              <span className="font-medium">{subnet.name}</span>
              <span className="text-muted-foreground"> — {subnet.instances.join(", ")}</span>
              {subnet.connected_to && subnet.connected_to.length > 0 ? (
                <span className="text-muted-foreground"> (connects to {subnet.connected_to.join(", ")})</span>
              ) : null}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function AcesCard({ scenario }: Readonly<{ scenario: ScenarioDetail }>) {
  const aces = scenario.aces;
  if (!aces) return null;
  return (
    <Card className="mt-6">
      <CardContent>
        <h2 className="mb-3 text-sm font-semibold">ACES package provenance</h2>
        <dl>
          <Field label="Contract">
            {aces.contract_kind} / {aces.contract_profile}
          </Field>
          <Field label="Package">{aces.package_ref}</Field>
          <Field label="Version">{aces.package_version}</Field>
          <Field label="Digest">
            <span className="font-mono text-xs break-all">{aces.package_digest}</span>
          </Field>
          <Field label="Conformance">{aces.conformance_status}</Field>
        </dl>
      </CardContent>
    </Card>
  );
}

export function ScenarioDetailPage() {
  const params = useParams();
  const navigate = useNavigate();
  const scenarioId = params.scenarioId ?? "";
  const bootstrap = useBootstrapContext();
  const canAuthor = bootstrap.permissions.can_access_threat_research;

  const query = useScenario(scenarioId);
  const remove = useDeleteScenario();
  const metadata = useUpdateScenarioMetadata(scenarioId);
  const exportMutation = useMutation({
    mutationFn: () => fetchScenarioExport(scenarioId),
    onSuccess: (result) => downloadTextFile(`${result.scenario_id}.yaml`, result.yaml),
  });

  const [showDelete, setShowDelete] = useState(false);
  const [showClone, setShowClone] = useState(false);

  if (query.isLoading) {
    return (
      <div className="grid place-items-center py-24 text-muted-foreground">
        <Loader2 className="size-6 animate-spin" aria-label="Loading scenario" />
      </div>
    );
  }
  if (query.isError || !query.data) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Scenario unavailable</AlertTitle>
        <AlertDescription>
          This scenario was not found or has been removed.{" "}
          <Link className="underline" to={scenarioListPath()}>
            Back to scenarios
          </Link>
          .
        </AlertDescription>
      </Alert>
    );
  }

  const scenario: ScenarioDetail = query.data;

  return (
    <>
      <nav className="mb-3 text-sm text-muted-foreground" aria-label="Breadcrumb">
        <Link className="hover:text-foreground" to={scenarioListPath()}>
          Scenarios
        </Link>
        <span className="px-1.5">/</span>
        <span className="text-foreground">{scenario.name}</span>
      </nav>

      <div className="mb-6 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">{scenario.name}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <SourceBadge source={scenario.source} />
            <EnabledBadge enabled={scenario.enabled} />
            {scenario.staff_only ? <StaffOnlyBadge /> : null}
            <span className="font-mono text-xs text-muted-foreground">{scenario.id}</span>
          </div>
        </div>
        {canAuthor ? (
          <ScenarioActions
            scenario={scenario}
            metadata={metadata}
            exporting={exportMutation.isPending}
            onExport={() => exportMutation.mutate()}
            onClone={() => setShowClone(true)}
            onDelete={() => setShowDelete(true)}
          />
        ) : null}
      </div>

      {metadata.error ? (
        <Alert variant="destructive" className="mb-4">
          <AlertTitle>Could not update availability</AlertTitle>
          <AlertDescription>Please retry.</AlertDescription>
        </Alert>
      ) : null}
      {exportMutation.error ? (
        <Alert variant="destructive" className="mb-4">
          <AlertTitle>Could not export scenario</AlertTitle>
          <AlertDescription>Please retry.</AlertDescription>
        </Alert>
      ) : null}

      <OverviewCard scenario={scenario} />
      <AcesCard scenario={scenario} />
      <InstancesCard scenario={scenario} />
      <SubnetsCard scenario={scenario} />

      <ConfirmDialog
        open={showDelete}
        title="Delete scenario?"
        confirmLabel="Delete"
        destructive
        pending={remove.isPending}
        error={remove.error}
        onOpenChange={(open) => {
          if (!open) {
            remove.reset();
            setShowDelete(false);
          }
        }}
        onConfirm={() => remove.mutate(scenario.id, { onSuccess: () => navigate(scenarioListPath()) })}
      >
        This scenario will be soft-deleted and removed from the catalog.
      </ConfirmDialog>

      <CloneDialog
        open={showClone}
        sourceId={scenario.id}
        onClose={() => setShowClone(false)}
        onCloned={(newId) => {
          setShowClone(false);
          navigate(`${scenarioListPath()}${newId}/`);
        }}
      />
    </>
  );
}

function CloneDialog({
  open,
  sourceId,
  onClose,
  onCloned,
}: Readonly<{
  open: boolean;
  sourceId: string;
  onClose: () => void;
  onCloned: (newId: string) => void;
}>) {
  const clone = useCloneScenario(sourceId);
  const [newId, setNewId] = useState("");
  const [newName, setNewName] = useState("");
  const error = clone.error instanceof Error ? clone.error.message : null;

  function reset() {
    clone.reset();
    setNewId("");
    setNewName("");
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          reset();
          onClose();
        }
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Clone scenario</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="clone-id">New scenario ID</Label>
            <Input id="clone-id" value={newId} placeholder="my-copy" onChange={(event) => setNewId(event.target.value)} />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="clone-name">New name (optional)</Label>
            <Input id="clone-name" value={newName} onChange={(event) => setNewName(event.target.value)} />
          </div>
          {error ? (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={clone.isPending}>
            Cancel
          </Button>
          <Button
            onClick={() =>
              clone.mutate(
                { new_scenario_id: newId, new_name: newName },
                { onSuccess: (created) => onCloned(created.scenario_id) },
              )
            }
            disabled={clone.isPending || !newId.trim()}
          >
            {clone.isPending ? <Loader2 className="size-4 animate-spin" /> : null}
            Clone
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
