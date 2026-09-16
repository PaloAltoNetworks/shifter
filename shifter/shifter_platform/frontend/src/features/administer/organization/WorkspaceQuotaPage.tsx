/**
 * Workspace resource quota & usage surface (#1946, PLAT-239). Rendered at
 * `workspaces/:workspaceUuid/quota` inside the workspace-scoped console layout.
 *
 * Authority lives on the server: `GET /api/v1/workspaces/{uuid}/quota/` authorizes
 * the caller's workspace role (owner/admin) and returns usage against configured
 * limits plus the recent quota decisions. This surface is strictly read-only —
 * quota *policy* is authored only through the superuser-only Django-admin escape
 * hatch (PLAT-241), never here — so it presents usage and the "when/why a limit
 * applied" history without any mutation control or client-side authority.
 */
import { useParams } from "react-router";

import { useWorkspaceQuota } from "@/api/workspaces";
import type { WorkspaceQuotaDecision, WorkspaceQuotaResource } from "@/api/types";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import { formatTimestamp } from "../format";

const RESOURCE_LABELS: Readonly<Record<string, string>> = {
  concurrent_ranges: "Concurrent ranges",
  member_seats: "Member seats",
};

const MODE_LABELS: Readonly<Record<string, string>> = {
  advisory: "Soft cap",
  enforcing: "Hard cap",
};

const OUTCOME_LABELS: Readonly<Record<string, string>> = {
  admitted: "Admitted",
  warned: "Warned",
  rejected: "Blocked",
};

function resourceLabel(resource: string): string {
  return RESOURCE_LABELS[resource] ?? resource;
}

function outcomeVariant(outcome: string): "secondary" | "destructive" | "outline" {
  if (outcome === "rejected") return "destructive";
  if (outcome === "warned") return "outline";
  return "secondary";
}

function ResourceCard({ resource }: Readonly<{ resource: WorkspaceQuotaResource }>) {
  const unlimited = resource.limit === null || resource.limit === undefined;
  const percent = unlimited || resource.limit === 0 ? 0 : Math.min(100, Math.round((resource.usage / resource.limit) * 100));
  return (
    <Card className="p-6" aria-label={`${resourceLabel(resource.resource)} usage`}>
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <h2 className="text-sm font-medium">{resourceLabel(resource.resource)}</h2>
          <p className="text-sm text-muted-foreground">
            {unlimited ? (
              <>Unlimited — no quota policy configured.</>
            ) : (
              <>
                {resource.usage} of {resource.limit} used
              </>
            )}
          </p>
        </div>
        {unlimited ? (
          <Badge variant="secondary">Unlimited</Badge>
        ) : (
          <Badge variant="outline">{MODE_LABELS[resource.mode ?? ""] ?? resource.mode}</Badge>
        )}
      </div>
      {unlimited ? null : (
        <Progress value={percent} className="mt-4" aria-label={`${resourceLabel(resource.resource)} usage percent`} />
      )}
    </Card>
  );
}

function DecisionsTable({ decisions }: Readonly<{ decisions: readonly WorkspaceQuotaDecision[] }>) {
  if (decisions.length === 0) {
    return (
      <Card className="p-6">
        <p className="text-sm text-muted-foreground">No quota limits have been applied yet.</p>
      </Card>
    );
  }
  return (
    <Card className="overflow-hidden">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>When</TableHead>
            <TableHead>Resource</TableHead>
            <TableHead>Outcome</TableHead>
            <TableHead>Usage / limit</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {decisions.map((decision, index) => (
            <TableRow key={`${decision.created_at}-${index}`}>
              <TableCell className="whitespace-nowrap">{formatTimestamp(decision.created_at)}</TableCell>
              <TableCell>{resourceLabel(decision.resource)}</TableCell>
              <TableCell>
                <Badge variant={outcomeVariant(decision.outcome)}>
                  {OUTCOME_LABELS[decision.outcome] ?? decision.outcome}
                </Badge>
              </TableCell>
              <TableCell className="whitespace-nowrap">
                {decision.usage_before} / {decision.limit}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  );
}

export function WorkspaceQuotaPage() {
  const { workspaceUuid } = useParams();
  const uuid = workspaceUuid ?? "";
  const query = useWorkspaceQuota(uuid);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Resource quotas"
        description="Usage against this workspace's resource limits, and a history of when a limit was applied. Limits are set by a platform administrator."
      />

      {query.isPending ? (
        <div className="grid gap-4 sm:grid-cols-2" aria-hidden>
          <Skeleton className="h-32" />
          <Skeleton className="h-32" />
        </div>
      ) : null}

      {query.isError ? (
        <Alert variant="destructive" className="max-w-xl">
          <AlertTitle>Quota is not available</AlertTitle>
          <AlertDescription>
            Your role in this workspace does not permit viewing resource quotas, or the workspace could not be loaded.
          </AlertDescription>
        </Alert>
      ) : null}

      {query.data ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            {query.data.resources.map((resource) => (
              <ResourceCard key={resource.resource} resource={resource} />
            ))}
          </div>
          <div className="space-y-2">
            <h2 className="text-sm font-medium">Recent quota decisions</h2>
            <DecisionsTable decisions={query.data.recent_decisions} />
          </div>
        </>
      ) : null}
    </div>
  );
}
