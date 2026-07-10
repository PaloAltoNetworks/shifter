import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Plus } from "lucide-react";

import { useBootstrapContext } from "@/app/bootstrap-context";
import { useRestoreRisk, useRisks, type RiskFilters } from "@/api/risks";
import { SEVERITIES, STATUSES, type Severity, type Status } from "@/api/types";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

import { SeverityBadge, StatusBadge } from "./badges";
import { ConfirmDialog } from "./ConfirmDialog";
import { formatTimestamp, titleCase } from "./format";

const ALL = "all";

function parseFilters(params: URLSearchParams): RiskFilters {
  const severity = params.get("severity");
  const status = params.get("status");
  const page = Number(params.get("page") ?? "1");
  return {
    severity: SEVERITIES.includes(severity as Severity) ? (severity as Severity) : undefined,
    status: STATUSES.includes(status as Status) ? (status as Status) : undefined,
    includeDeleted: params.get("deleted") === "1",
    page: Number.isFinite(page) && page > 1 ? page : undefined,
  };
}

export function RiskListPage() {
  const [params, setParams] = useSearchParams();
  const bootstrap = useBootstrapContext();
  const canWrite = bootstrap.principal.is_staff;
  const filters = parseFilters(params);
  const query = useRisks(filters);
  const [restoreId, setRestoreId] = useState<number | null>(null);
  const restore = useRestoreRisk();

  const filtersActive = Boolean(filters.severity || filters.status || filters.includeDeleted);

  function updateParam(key: string, value: string | null) {
    const next = new URLSearchParams(params);
    if (value) {
      next.set(key, value);
    } else {
      next.delete(key);
    }
    next.delete("page");
    setParams(next);
  }

  function goToPage(page: number) {
    const next = new URLSearchParams(params);
    if (page > 1) {
      next.set("page", String(page));
    } else {
      next.delete("page");
    }
    setParams(next);
  }

  const count = query.data?.count ?? 0;
  const countNoun = count === 1 ? "risk" : "risks";
  const description = query.data ? `${count} ${countNoun} in the register` : "Risk register";

  return (
    <>
      <PageHeader
        title="Risks"
        description={description}
        actions={
          canWrite ? (
            <Link to="/risks/create" className={cn(buttonVariants({ size: "sm" }))}>
              <Plus className="size-4" />
              New risk
            </Link>
          ) : null
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Select
          value={filters.severity ?? ALL}
          onValueChange={(value) => updateParam("severity", value === ALL ? null : value)}
        >
          <SelectTrigger size="sm" className="w-[160px]" aria-label="Filter by severity">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All severities</SelectItem>
            {SEVERITIES.map((value) => (
              <SelectItem key={value} value={value}>
                {titleCase(value)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select
          value={filters.status ?? ALL}
          onValueChange={(value) => updateParam("status", value === ALL ? null : value)}
        >
          <SelectTrigger size="sm" className="w-[160px]" aria-label="Filter by status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All statuses</SelectItem>
            {STATUSES.map((value) => (
              <SelectItem key={value} value={value}>
                {titleCase(value)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <label className="flex select-none items-center gap-2 text-sm text-muted-foreground">
          <input
            type="checkbox"
            className="size-4 rounded border-input bg-transparent accent-primary"
            checked={filters.includeDeleted ?? false}
            onChange={(event) => updateParam("deleted", event.target.checked ? "1" : null)}
          />
          <span>Show deleted</span>
        </label>
      </div>

      <Card className="overflow-hidden py-0" aria-busy={query.isFetching}>
        <RiskListBody query={query} filtersActive={filtersActive} canWrite={canWrite} onRestore={setRestoreId} />
      </Card>

      {query.data && (query.data.next || query.data.previous) ? (
        <div className="mt-4 flex items-center gap-2">
          <Button variant="outline" size="sm" disabled={!query.data.previous} onClick={() => goToPage((filters.page ?? 1) - 1)}>
            Previous
          </Button>
          <Button variant="outline" size="sm" disabled={!query.data.next} onClick={() => goToPage((filters.page ?? 1) + 1)}>
            Next
          </Button>
        </div>
      ) : null}

      <ConfirmDialog
        open={restoreId !== null}
        title="Restore risk?"
        confirmLabel="Restore"
        pending={restore.isPending}
        error={restore.error}
        onOpenChange={(open) => {
          if (!open) {
            restore.reset();
            setRestoreId(null);
          }
        }}
        onConfirm={() => {
          if (restoreId !== null) {
            restore.mutate(restoreId, { onSuccess: () => setRestoreId(null) });
          }
        }}
      >
        This risk will be restored to the active register.
      </ConfirmDialog>
    </>
  );
}

function RiskListBody({
  query,
  filtersActive,
  canWrite,
  onRestore,
}: Readonly<{
  query: ReturnType<typeof useRisks>;
  filtersActive: boolean;
  canWrite: boolean;
  onRestore: (id: number) => void;
}>) {
  if (query.isLoading) {
    return (
      <div className="space-y-3 p-4">
        {[0, 1, 2, 3].map((row) => (
          <Skeleton key={row} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  if (query.isError) {
    return (
      <div className="p-4">
        <Alert variant="destructive">
          <AlertTitle>Could not load risks</AlertTitle>
          <AlertDescription>Please retry.</AlertDescription>
        </Alert>
      </div>
    );
  }

  const results = query.data?.results ?? [];
  if (results.length === 0) {
    return (
      <div className="grid place-items-center px-6 py-16 text-center">
        <p className="text-sm font-medium">{filtersActive ? "No risks match these filters" : "No risks yet"}</p>
        <p className="mt-1 text-sm text-muted-foreground">
          {filtersActive ? "Adjust or clear the filters to see more." : "Create the first risk to get started."}
        </p>
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead>Title</TableHead>
          <TableHead className="w-[120px]">Severity</TableHead>
          <TableHead className="w-[130px]">Status</TableHead>
          <TableHead className="w-[80px] text-right">Score</TableHead>
          <TableHead className="w-[110px] text-right">Comments</TableHead>
          <TableHead className="w-[180px]">Updated</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {results.map((risk) => (
          <TableRow key={risk.id}>
            <TableCell className="font-medium">
              <div className="flex items-center gap-2">
                <Link className="hover:underline" to={`/risks/${risk.id}`}>
                  {risk.title}
                </Link>
                {risk.is_deleted ? (
                  <>
                    <Badge variant="outline" className="border-zinc-700 text-zinc-400">
                      Deleted
                    </Badge>
                    {canWrite ? (
                      <Button variant="ghost" size="sm" onClick={() => onRestore(risk.id)}>
                        Restore
                      </Button>
                    ) : null}
                  </>
                ) : null}
              </div>
            </TableCell>
            <TableCell>
              <SeverityBadge severity={risk.severity ?? "low"} />
            </TableCell>
            <TableCell>
              <StatusBadge status={risk.status ?? "open"} />
            </TableCell>
            <TableCell className="text-right font-mono text-sm tabular-nums">{risk.risk_score ?? "—"}</TableCell>
            <TableCell className="text-right font-mono text-sm tabular-nums text-muted-foreground">
              {risk.comment_count}
            </TableCell>
            <TableCell className="text-sm text-muted-foreground">{formatTimestamp(risk.updated_at)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
