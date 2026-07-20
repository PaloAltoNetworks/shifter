import { Link } from "react-router-dom";

import { ApiError } from "@/api/errors";
import { useRangeHistory } from "@/api/mission-control";
import type { RangeHistory } from "@/api/types";
import { rangeStatusMapping } from "@/app/state-map";
import { PageHeader } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

import { formatTimestamp } from "./format";
import { missionControlLaunchPath, missionControlRangeDetailPath } from "./routes";

function EmptyHistoryState() {
  return (
    <Card className="grid place-items-center px-6 py-16 text-center">
      <p className="text-sm font-medium">No ranges yet</p>
      <p className="mt-1 text-sm text-muted-foreground">Launch a range to see it here.</p>
      <Link to={missionControlLaunchPath()} className={cn(buttonVariants({ size: "sm" }), "mt-4")}>
        Launch a range
      </Link>
    </Card>
  );
}

function HistoryRow({ entry }: Readonly<{ entry: RangeHistory }>) {
  const mapping = rangeStatusMapping(entry.status);
  return (
    <TableRow>
      <TableCell className="font-medium">
        {entry.request_id ? (
          <Link className="hover:underline" to={missionControlRangeDetailPath(entry.request_id)}>
            {entry.scenario_id}
          </Link>
        ) : (
          entry.scenario_id
        )}
      </TableCell>
      <TableCell>
        <StatusChip intent={mapping.intent} label={mapping.label} />
      </TableCell>
      <TableCell className="text-sm text-muted-foreground">{formatTimestamp(entry.created_at)}</TableCell>
      <TableCell className="text-sm text-muted-foreground">{formatTimestamp(entry.updated_at)}</TableCell>
    </TableRow>
  );
}

function RangeHistoryBody({ query }: Readonly<{ query: ReturnType<typeof useRangeHistory> }>) {
  if (query.isLoading) {
    return (
      <div className="space-y-3">
        {[0, 1, 2].map((row) => (
          <Skeleton key={row} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  if (query.isError) {
    const message = query.error instanceof ApiError ? query.error.message : "Please retry.";
    return (
      <Alert variant="destructive">
        <AlertTitle>Could not load your ranges</AlertTitle>
        <AlertDescription>{message}</AlertDescription>
      </Alert>
    );
  }

  const ranges = query.data?.ranges ?? [];
  if (ranges.length === 0) {
    return <EmptyHistoryState />;
  }

  return (
    <Card className="overflow-hidden py-0" aria-busy={query.isFetching}>
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Scenario</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Created</TableHead>
            <TableHead>Updated</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {ranges.map((entry, index) => (
            <HistoryRow key={entry.request_id ?? `${entry.scenario_id}-${index}`} entry={entry} />
          ))}
        </TableBody>
      </Table>
    </Card>
  );
}

/** List of the current user's ranges, past and present (#1370). */
export function RangeHistoryPage() {
  const query = useRangeHistory();

  return (
    <>
      <PageHeader title="Ranges" description="Your range history" />
      <RangeHistoryBody query={query} />
    </>
  );
}
