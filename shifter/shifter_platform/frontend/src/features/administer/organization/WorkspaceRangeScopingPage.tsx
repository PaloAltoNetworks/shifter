/**
 * Range-to-workspace scoping administration surface (#1944, PLAT-237). Rendered at
 * `workspaces/:workspaceUuid/range-scoping` inside the workspace-scoped console
 * layout.
 *
 * Authority lives on the server: the `/api/v1/cms/workspaces/{uuid}/range-scoping/`
 * and `/api/v1/cms/ranges/{request_id}/workspace/` endpoints require a staff
 * session AND the workspace's owner/admin scope operation, and are the
 * `shared.audit` boundary. This surface consumes the selected workspace's
 * server-derived `capabilities` for presentation only and posts the reassignment;
 * it never compares role codes to reconstruct policy. Only Mission Control ranges
 * are reassignable (`is_reassignable`, server-derived); the server reauthorizes
 * every call and can still return a `409` between render and submit.
 */
import { useEffect, useState } from "react";
import { useParams } from "react-router";

import { useRebindRangeWorkspace, useWorkspaceRangeScopeBindings } from "@/api/rangeScoping";
import { ApiError, describeMutationError } from "@/api/errors";
import type { PrincipalWorkspaceContext, RangeScopeBinding } from "@/api/types";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import { formatTimestamp } from "../format";
import { useWorkspaceContext } from "./WorkspaceContext";

/** The advisory capability the nav gate and this surface key on; the server reauthorizes. */
const REBIND_CAPABILITY = "rebind_range_workspace";

export function WorkspaceRangeScopingPage() {
  const { workspaceUuid } = useParams();
  const uuid = workspaceUuid ?? "";
  const { selected, workspaces } = useWorkspaceContext();
  const description = selected
    ? `Ranges scoped to ${selected.workspace_name}, and reassignment to another workspace`
    : "Ranges scoped to this workspace";

  const [page, setPage] = useState(1);
  // Selecting a different workspace resets to the first page so a stale page
  // index never points past the new workspace's range count.
  useEffect(() => setPage(1), [uuid]);

  const bindings = useWorkspaceRangeScopeBindings(uuid, { page });
  const canRebind = (selected?.capabilities ?? []).includes(REBIND_CAPABILITY);

  if (bindings.isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader title="Range scoping" description={description} />
        <Skeleton className="h-40 w-full max-w-4xl" />
      </div>
    );
  }

  if (bindings.isError || !bindings.data) {
    const forbidden = bindings.error instanceof ApiError && bindings.error.status === 403;
    const notFound = bindings.error instanceof ApiError && bindings.error.status === 404;
    return (
      <div className="space-y-6">
        <PageHeader title="Range scoping" description={description} />
        <Alert variant="destructive" className="max-w-xl">
          <AlertTitle>
            {forbidden || notFound
              ? "You do not have permission to administer range scoping for this workspace"
              : "Could not load the ranges for this workspace"}
          </AlertTitle>
          <AlertDescription>Please retry. If the problem persists, contact an administrator.</AlertDescription>
        </Alert>
      </div>
    );
  }

  const rows = bindings.data.results ?? [];
  const hasNext = Boolean(bindings.data.next);
  const hasPrevious = Boolean(bindings.data.previous);
  // Eligible reassignment targets: other workspaces the caller may rebind into.
  // The server still enforces the target's active state and the range owner's
  // membership; this only shapes the picker.
  const targets = workspaces.filter(
    (workspace) => workspace.workspace_uuid !== uuid && workspace.capabilities.includes(REBIND_CAPABILITY),
  );

  return (
    <div className="space-y-6">
      <PageHeader title="Range scoping" description={description} />
      {rows.length === 0 && page === 1 ? (
        <Card className="max-w-4xl p-6">
          <p className="text-sm text-muted-foreground">No ranges are scoped to this workspace.</p>
        </Card>
      ) : (
        <Card className="overflow-hidden py-0" aria-busy={bindings.isFetching}>
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Range</TableHead>
                <TableHead className="w-[120px]">Source</TableHead>
                <TableHead className="w-[120px]">Status</TableHead>
                <TableHead className="w-[110px]">Owner</TableHead>
                <TableHead className="w-[190px]">Created</TableHead>
                <TableHead className="w-[130px] text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <RangeRow key={row.request_id ?? `${row.owner_id}-${row.created_at}`} row={row} canRebind={canRebind} targets={targets} />
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
      {hasNext || hasPrevious ? (
        <nav className="flex items-center gap-3" aria-label="Range scoping pagination">
          <Button variant="outline" size="sm" disabled={!hasPrevious} onClick={() => setPage((current) => Math.max(1, current - 1))}>
            Previous
          </Button>
          <span className="text-sm text-muted-foreground">
            Page {page}
            {typeof bindings.data.count === "number" ? ` of ${bindings.data.count} ranges` : ""}
          </span>
          <Button variant="outline" size="sm" disabled={!hasNext} onClick={() => setPage((current) => current + 1)}>
            Next
          </Button>
        </nav>
      ) : null}
    </div>
  );
}

function RangeRow({
  row,
  canRebind,
  targets,
}: Readonly<{ row: RangeScopeBinding; canRebind: boolean; targets: readonly PrincipalWorkspaceContext[] }>) {
  const shortId = row.request_id ? row.request_id.slice(0, 8) : "—";
  return (
    <TableRow>
      <TableCell className="font-mono text-xs" title={row.request_id ?? undefined}>
        {shortId} <span className="text-muted-foreground">{row.scenario_id}</span>
      </TableCell>
      <TableCell>
        <Badge variant="outline">{row.range_source}</Badge>
      </TableCell>
      <TableCell className="text-sm">{row.status}</TableCell>
      <TableCell className="text-sm text-muted-foreground">#{row.owner_id}</TableCell>
      <TableCell className="text-sm text-muted-foreground">{formatTimestamp(row.created_at)}</TableCell>
      <TableCell className="text-right">
        <ReassignAction row={row} canRebind={canRebind} targets={targets} />
      </TableCell>
    </TableRow>
  );
}

function ReassignAction({
  row,
  canRebind,
  targets,
}: Readonly<{ row: RangeScopeBinding; canRebind: boolean; targets: readonly PrincipalWorkspaceContext[] }>) {
  const [open, setOpen] = useState(false);
  const [targetUuid, setTargetUuid] = useState("");
  const mutation = useRebindRangeWorkspace();

  // Only Mission Control ranges may be reassigned here (ADR-046-R14); a
  // domain-owned aggregate range shows a disabled control with the reason.
  if (!canRebind || !row.is_reassignable || !row.request_id) {
    return (
      <Button
        variant="ghost"
        size="sm"
        disabled
        title={row.is_reassignable ? undefined : "This range is managed by its event and cannot be reassigned."}
      >
        Reassign
      </Button>
    );
  }

  function onOpenChange(next: boolean) {
    setOpen(next);
    if (!next) {
      setTargetUuid("");
      mutation.reset();
    }
  }

  function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!row.request_id || !targetUuid) return;
    mutation.mutate(
      { requestId: row.request_id, targetWorkspaceUuid: targetUuid },
      { onSuccess: () => onOpenChange(false) },
    );
  }

  const error = describeMutationError(mutation.error, "The range could not be reassigned.");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <Button variant="ghost" size="sm" onClick={() => setOpen(true)}>
        Reassign
      </Button>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Reassign range scope</DialogTitle>
          <DialogDescription>
            Move this range to another workspace. The range owner must already be a member of the target workspace; the
            owner, lifecycle, and access of the range do not change.
          </DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={onSubmit} aria-label="Reassign range scope">
          <div className="flex flex-col gap-2">
            <Label htmlFor="reassign-target">Target workspace</Label>
            {targets.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                You do not administer another workspace to move this range into.
              </p>
            ) : (
              <Select value={targetUuid} onValueChange={setTargetUuid}>
                <SelectTrigger id="reassign-target" className="w-full" aria-label="Target workspace">
                  <SelectValue placeholder="Select a workspace" />
                </SelectTrigger>
                <SelectContent>
                  {targets.map((workspace) => (
                    <SelectItem key={workspace.workspace_uuid} value={workspace.workspace_uuid}>
                      {workspace.workspace_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>

          {error ? (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}

          <DialogFooter>
            <Button type="submit" disabled={mutation.isPending || targetUuid.length === 0}>
              {mutation.isPending ? "Reassigning…" : "Reassign"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
