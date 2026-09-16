import { useState } from "react";
import { Link } from "react-router";

import { ApiError } from "@/api/errors";
import { useNgfwList } from "@/api/mission-control";
import type { NGFWListItem } from "@/api/types";
import { rangeStatusMapping } from "@/app/state-map";
import { PageHeader } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

import { formatTimestamp } from "./format";
import { NgfwDestroyDialog } from "./NgfwDestroyDialog";
import { missionControlNgfwDetailPath, missionControlNgfwWizardPath } from "./routes";

function EmptyNgfwState() {
  return (
    <Card className="grid place-items-center px-6 py-16 text-center">
      <p className="text-sm font-medium">No NGFWs configured</p>
      <p className="mt-1 text-sm text-muted-foreground">
        Set up a persistent NGFW to enable traffic logging to XDR for your ranges.
      </p>
      <Link to={missionControlNgfwWizardPath()} className={cn(buttonVariants({ size: "sm" }), "mt-4")}>
        Set up NGFW
      </Link>
    </Card>
  );
}

function NgfwRow({ ngfw, onDestroy }: Readonly<{ ngfw: NGFWListItem; onDestroy: () => void }>) {
  const mapping = rangeStatusMapping(ngfw.status);
  return (
    <TableRow>
      <TableCell className="font-medium">
        <Link className="hover:underline" to={missionControlNgfwDetailPath(ngfw.id)}>
          {ngfw.name}
        </Link>
      </TableCell>
      <TableCell>
        <StatusChip intent={mapping.intent} label={mapping.label} />
      </TableCell>
      <TableCell className="font-mono text-sm text-muted-foreground">{ngfw.serial_number ?? "—"}</TableCell>
      <TableCell className="text-sm text-muted-foreground">{formatTimestamp(ngfw.created_at)}</TableCell>
      <TableCell className="text-right">
        <Button type="button" variant="outline" size="sm" onClick={onDestroy}>
          Deprovision
        </Button>
      </TableCell>
    </TableRow>
  );
}

function NgfwListBody({
  query,
  onDestroy,
}: Readonly<{ query: ReturnType<typeof useNgfwList>; onDestroy: (ngfw: NGFWListItem) => void }>) {
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
        <AlertTitle>Could not load your NGFWs</AlertTitle>
        <AlertDescription>{message}</AlertDescription>
      </Alert>
    );
  }

  const ngfws = query.data?.ngfws ?? [];
  if (ngfws.length === 0) {
    return <EmptyNgfwState />;
  }

  return (
    <Card className="overflow-hidden py-0" aria-busy={query.isFetching}>
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Name</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Serial number</TableHead>
            <TableHead>Created</TableHead>
            <TableHead className="text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {ngfws.map((ngfw) => (
            <NgfwRow key={ngfw.id} ngfw={ngfw} onDestroy={() => onDestroy(ngfw)} />
          ))}
        </TableBody>
      </Table>
    </Card>
  );
}

/** List of the current user's NGFWs, with per-row deprovision (#1370). */
export function NgfwListPage() {
  const query = useNgfwList();
  const [destroyTarget, setDestroyTarget] = useState<NGFWListItem | null>(null);

  return (
    <>
      <PageHeader
        title="NGFWs"
        description="Manage your persistent Next-Generation Firewalls for XDR traffic logging."
        actions={
          <Link to={missionControlNgfwWizardPath()} className={cn(buttonVariants({ size: "sm" }))}>
            Set up NGFW
          </Link>
        }
      />

      <NgfwListBody query={query} onDestroy={setDestroyTarget} />

      {destroyTarget ? (
        <NgfwDestroyDialog
          ngfw={destroyTarget}
          open={destroyTarget != null}
          onOpenChange={(open) => {
            if (!open) setDestroyTarget(null);
          }}
        />
      ) : null}
    </>
  );
}
