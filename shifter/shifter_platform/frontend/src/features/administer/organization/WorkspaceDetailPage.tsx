/**
 * Workspace overview surface (#1940, PLAT-233). Rendered at the
 * `workspaces/:workspaceUuid` index inside the workspace-scoped console layout.
 *
 * Shows the selected workspace's detail and its lifecycle actions — rename,
 * archive/restore, and owner transfer. Authority lives on the server:
 * `/api/v1/workspaces/{uuid}/` (and its `archive`/`restore`/`transfer` actions)
 * authorizes the caller's workspace role and is the audit boundary; this surface
 * only presents the projection and posts the actions, never comparing roles
 * client-side. The workspace is addressed by its public-UUID route param.
 */
import { useEffect, useState } from "react";
import { useParams } from "react-router";

import {
  useArchiveWorkspace,
  useRenameWorkspace,
  useRestoreWorkspace,
  useSetWorkspaceEgressPolicy,
  useTransferWorkspaceOwnership,
  useWorkspace,
} from "@/api/workspaces";
import { ApiError, describeMutationError } from "@/api/errors";
import type { Workspace, WorkspaceEgressPolicy } from "@/api/types";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";

const EGRESS_POLICY_OPTIONS: ReadonlyArray<{ value: WorkspaceEgressPolicy; label: string; hint: string }> = [
  { value: "status-quo", label: "Inherit deployment baseline", hint: "Ranges keep the deployment's default network egress." },
  { value: "none", label: "Zero egress (no outbound NAT path)", hint: "New ranges provision with no outbound internet path." },
];

import { formatTimestamp } from "../format";

function loadErrorTitle(error: unknown): string {
  if (error instanceof ApiError && error.status === 403) return "You do not have permission to view this workspace";
  if (error instanceof ApiError && error.status === 404) return "Workspace not found";
  return "Could not load the workspace";
}

export function WorkspaceDetailPage() {
  const { workspaceUuid } = useParams();
  const uuid = workspaceUuid ?? "";
  const query = useWorkspace(uuid);

  if (query.isLoading) {
    return <Skeleton className="h-64 w-full max-w-2xl" />;
  }
  if (query.isError || !query.data) {
    return (
      <Alert variant="destructive" className="max-w-xl">
        <AlertTitle>{loadErrorTitle(query.error)}</AlertTitle>
        <AlertDescription>Please retry. If the problem persists, contact an administrator.</AlertDescription>
      </Alert>
    );
  }

  return <WorkspaceDetail uuid={uuid} workspace={query.data} />;
}

function WorkspaceDetail({ uuid, workspace }: Readonly<{ uuid: string; workspace: Workspace }>) {
  return (
    <div className="space-y-6">
      <PageHeader title={workspace.name} description={`Workspace in ${workspace.organization_name}`} />
      <OverviewCard workspace={workspace} />
      <RenameCard uuid={uuid} workspace={workspace} />
      <EgressPolicyCard uuid={uuid} workspace={workspace} />
      <LifecycleCard uuid={uuid} workspace={workspace} />
      <TransferOwnershipCard uuid={uuid} />
    </div>
  );
}

function OverviewCard({ workspace }: Readonly<{ workspace: Workspace }>) {
  return (
    <Card className="max-w-2xl space-y-4 p-6">
      <h2 className="text-sm font-medium">Overview</h2>
      <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
        <Detail label="Name" value={workspace.name} />
        <Detail label="Organization" value={workspace.organization_name} />
        <div className="flex flex-col gap-1">
          <dt className="text-muted-foreground">Status</dt>
          <dd>
            {workspace.is_archived ? <Badge variant="secondary">Archived</Badge> : <Badge variant="outline">Active</Badge>}
          </dd>
        </div>
        <Detail label="Archived" value={formatTimestamp(workspace.archived_at)} />
        <Detail label="Network egress" value={egressPolicyLabel(workspace.egress_policy)} />
        <Detail label="Created" value={formatTimestamp(workspace.created_at)} />
        <Detail label="Updated" value={formatTimestamp(workspace.updated_at)} />
      </dl>
    </Card>
  );
}

function Detail({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <div className="flex flex-col gap-1">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}

/** Inline rename form using the lifecycle PATCH. */
function RenameCard({ uuid, workspace }: Readonly<{ uuid: string; workspace: Workspace }>) {
  const [name, setName] = useState(workspace.name);
  const [saved, setSaved] = useState(false);
  const mutation = useRenameWorkspace(uuid);

  // Re-seed the field when a fresh server snapshot arrives (e.g. after another
  // admin's concurrent rename lands in the cache).
  useEffect(() => {
    setName(workspace.name);
  }, [workspace.name]);

  const fieldErrors = mutation.error instanceof ApiError ? mutation.error.fieldErrors() : {};
  const topLevelError =
    Object.keys(fieldErrors).length === 0 ? describeMutationError(mutation.error, "The workspace could not be renamed.") : null;

  function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSaved(false);
    mutation.mutate(name.trim(), { onSuccess: () => setSaved(true) });
  }

  return (
    <Card className="max-w-2xl p-6">
      <form className="space-y-4" onSubmit={onSubmit} aria-label="Rename workspace">
        <div className="flex flex-col gap-2">
          <Label htmlFor="workspace-name">Name</Label>
          <Input
            id="workspace-name"
            value={name}
            aria-invalid={fieldErrors.name ? true : undefined}
            onChange={(event) => {
              setName(event.target.value);
              setSaved(false);
            }}
          />
          {fieldErrors.name?.length ? <p className="text-sm text-destructive">{fieldErrors.name.join(" ")}</p> : null}
        </div>

        {topLevelError ? (
          <Alert variant="destructive">
            <AlertDescription>{topLevelError}</AlertDescription>
          </Alert>
        ) : null}
        {saved && !mutation.isPending ? <output className="text-sm text-muted-foreground">Saved.</output> : null}

        <Button type="submit" disabled={mutation.isPending || name.trim().length === 0 || name.trim() === workspace.name}>
          {mutation.isPending ? "Saving…" : "Rename"}
        </Button>
      </form>
    </Card>
  );
}

function egressPolicyLabel(policy: WorkspaceEgressPolicy): string {
  return EGRESS_POLICY_OPTIONS.find((option) => option.value === policy)?.label ?? policy;
}

/**
 * Set the workspace network egress policy (#1945, PLAT-238). The server
 * (`PUT /api/v1/workspaces/{uuid}/egress-policy/`) authorizes the owner/admin
 * role, re-validates the closed choice, and is the audit boundary; this control
 * only presents the current value and posts the change. The change applies to
 * newly provisioned ranges and never mutates a running range.
 */
function EgressPolicyCard({ uuid, workspace }: Readonly<{ uuid: string; workspace: Workspace }>) {
  const [policy, setPolicy] = useState<WorkspaceEgressPolicy>(workspace.egress_policy);
  const [saved, setSaved] = useState(false);
  const mutation = useSetWorkspaceEgressPolicy(uuid);

  useEffect(() => {
    setPolicy(workspace.egress_policy);
  }, [workspace.egress_policy]);

  const topLevelError = describeMutationError(mutation.error, "The egress policy could not be updated.");
  const selected = EGRESS_POLICY_OPTIONS.find((option) => option.value === policy);

  function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSaved(false);
    mutation.mutate(policy, { onSuccess: () => setSaved(true) });
  }

  return (
    <Card className="max-w-2xl p-6">
      <form className="space-y-4" onSubmit={onSubmit} aria-label="Set network egress policy">
        <div className="space-y-1">
          <h2 className="text-sm font-medium">Network egress policy</h2>
          <p className="text-sm text-muted-foreground">
            Controls outbound network access for ranges launched in this workspace. Applies to newly provisioned ranges;
            existing ranges are unchanged.
          </p>
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="workspace-egress-policy">Policy</Label>
          <Select
            value={policy}
            onValueChange={(value) => {
              setPolicy(value as WorkspaceEgressPolicy);
              setSaved(false);
            }}
          >
            <SelectTrigger id="workspace-egress-policy" className="w-[320px]" aria-label="Network egress policy">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {EGRESS_POLICY_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {selected ? <p className="text-sm text-muted-foreground">{selected.hint}</p> : null}
        </div>

        {mutation.isError ? (
          <Alert variant="destructive">
            <AlertDescription>{topLevelError}</AlertDescription>
          </Alert>
        ) : null}
        {saved && !mutation.isPending ? <output className="text-sm text-muted-foreground">Saved.</output> : null}

        <Button type="submit" disabled={mutation.isPending || policy === workspace.egress_policy}>
          {mutation.isPending ? "Saving…" : "Save egress policy"}
        </Button>
      </form>
    </Card>
  );
}

/** Archive or restore the workspace, confirmed before the action fires. */
function LifecycleCard({ uuid, workspace }: Readonly<{ uuid: string; workspace: Workspace }>) {
  const [open, setOpen] = useState(false);
  const archive = useArchiveWorkspace(uuid);
  const restore = useRestoreWorkspace(uuid);
  const isArchived = workspace.is_archived;
  const mutation = isArchived ? restore : archive;

  function onConfirm() {
    mutation.mutate(undefined, { onSuccess: () => setOpen(false) });
  }

  return (
    <Card className="max-w-2xl space-y-3 p-6">
      <h2 className="text-sm font-medium">{isArchived ? "Restore workspace" : "Archive workspace"}</h2>
      <p className="text-sm text-muted-foreground">
        {isArchived
          ? "Restoring returns this workspace to active use."
          : "Archiving hides this workspace from active use. You can restore it later."}
      </p>
      <Button variant={isArchived ? "default" : "destructive"} onClick={() => setOpen(true)}>
        {isArchived ? "Restore" : "Archive"}
      </Button>
      <ConfirmDialog
        open={open}
        title={isArchived ? "Restore this workspace?" : "Archive this workspace?"}
        confirmLabel={isArchived ? "Restore" : "Archive"}
        destructive={!isArchived}
        pending={mutation.isPending}
        error={mutation.error}
        onConfirm={onConfirm}
        onOpenChange={setOpen}
      >
        {isArchived
          ? `"${workspace.name}" will return to active use.`
          : `"${workspace.name}" will be archived and hidden from active use.`}
      </ConfirmDialog>
    </Card>
  );
}

/** Transfer workspace ownership to another member by their user id. */
function TransferOwnershipCard({ uuid }: Readonly<{ uuid: string }>) {
  const [userId, setUserId] = useState("");
  const [open, setOpen] = useState(false);
  const mutation = useTransferWorkspaceOwnership(uuid);

  const parsed = Number(userId);
  const validUserId = userId.trim().length > 0 && Number.isInteger(parsed) && parsed > 0;

  const fieldErrors = mutation.error instanceof ApiError ? mutation.error.fieldErrors() : {};

  function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (validUserId) setOpen(true);
  }

  function onConfirm() {
    mutation.mutate({ user_id: parsed }, {
      onSuccess: () => {
        setOpen(false);
        setUserId("");
      },
    });
  }

  return (
    <Card className="max-w-2xl p-6">
      <form className="space-y-4" onSubmit={onSubmit} aria-label="Transfer ownership">
        <h2 className="text-sm font-medium">Transfer ownership</h2>
        <p className="text-sm text-muted-foreground">Assign a new owner for this workspace by their user id.</p>
        <div className="flex flex-col gap-2">
          <Label htmlFor="transfer-owner-id">New owner user ID</Label>
          <Input
            id="transfer-owner-id"
            type="number"
            min={1}
            value={userId}
            aria-invalid={fieldErrors.user_id ? true : undefined}
            onChange={(event) => setUserId(event.target.value)}
            className="w-[240px]"
          />
          {fieldErrors.user_id?.length ? (
            <p className="text-sm text-destructive">{fieldErrors.user_id.join(" ")}</p>
          ) : null}
        </div>
        <Button type="submit" disabled={!validUserId || mutation.isPending}>
          Transfer ownership
        </Button>
      </form>
      <ConfirmDialog
        open={open}
        title="Transfer workspace ownership?"
        confirmLabel="Transfer"
        destructive
        pending={mutation.isPending}
        error={mutation.error}
        onConfirm={onConfirm}
        onOpenChange={setOpen}
      >
        Ownership will be transferred to user {userId}. You may lose owner access to this workspace.
      </ConfirmDialog>
    </Card>
  );
}
