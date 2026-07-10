import { useAudit } from "@/api/risks";
import { ApiError } from "@/api/errors";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import { formatTimestamp, titleCase } from "./format";

export function HistoryPanel({ riskId, canViewAudit }: Readonly<{ riskId: number; canViewAudit: boolean }>) {
  const audit = useAudit(riskId, canViewAudit);

  if (!canViewAudit) {
    return <p className="text-sm text-muted-foreground">Audit history requires administrator access.</p>;
  }
  if (audit.isLoading) {
    return <Skeleton className="h-24 w-full" />;
  }
  if (audit.isError) {
    if (audit.error instanceof ApiError && audit.error.status === 403) {
      return <p className="text-sm text-muted-foreground">Audit history requires administrator access.</p>;
    }
    return (
      <Alert variant="destructive">
        <AlertDescription>Could not load history.</AlertDescription>
      </Alert>
    );
  }

  const rows = audit.data?.results ?? [];
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">No history yet.</p>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="w-[200px]">When</TableHead>
          <TableHead>Action</TableHead>
          <TableHead>Actor</TableHead>
          <TableHead>Request</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.id}>
            <TableCell className="text-sm text-muted-foreground">{formatTimestamp(row.timestamp)}</TableCell>
            <TableCell className="text-sm">{titleCase(String(row.action ?? ""))}</TableCell>
            <TableCell className="text-sm text-muted-foreground">
              {row.actor_type ? `${row.actor_type}` : "—"}
              {row.actor_id == null ? "" : ` #${row.actor_id}`}
            </TableCell>
            <TableCell className="font-mono text-xs text-muted-foreground">{row.request_id ?? "—"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
