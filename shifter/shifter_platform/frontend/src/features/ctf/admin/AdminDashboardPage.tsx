import { Link } from "react-router";

import { Plus } from "lucide-react";

import { useCtfEvents } from "@/api/ctfAdmin";
import type { CtfEventSummary } from "@/api/types";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

import { formatDateTime, titleCase } from "../format";
import { ctfAdminEventCreatePath, ctfAdminEventPath, ctfAdminEventsPath } from "../routes";

const ACTIVE_STATUSES = new Set(["registration", "active", "paused"]);

function DashboardBody({ query }: Readonly<{ query: ReturnType<typeof useCtfEvents> }>) {
  if (query.isLoading) {
    return (
      <div className="space-y-3">
        {[0, 1, 2].map((row) => (
          <Skeleton key={row} className="h-16 w-full" />
        ))}
      </div>
    );
  }

  if (query.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Could not load events</AlertTitle>
        <AlertDescription>Please retry.</AlertDescription>
      </Alert>
    );
  }

  const events = query.data?.events ?? [];
  if (events.length === 0) {
    return (
      <Card>
        <CardContent className="grid place-items-center px-6 py-16 text-center">
          <p className="text-sm font-medium">No events yet</p>
          <p className="mt-1 text-sm text-muted-foreground">Create your first CTF event to get started.</p>
          <Link to={ctfAdminEventCreatePath()} className={cn(buttonVariants({ size: "sm" }), "mt-4")}>
            <Plus className="size-4" />
            New event
          </Link>
        </CardContent>
      </Card>
    );
  }

  const active = events.filter((event: CtfEventSummary) => ACTIVE_STATUSES.has(event.status));

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-3">
        <SummaryTile label="Total events" value={events.length} />
        <SummaryTile label="Active / open" value={active.length} />
        <SummaryTile label="Team-mode events" value={events.filter((event) => event.team_mode).length} />
      </div>
      <Card className="overflow-hidden py-0">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Event</TableHead>
              <TableHead className="w-[140px]">Status</TableHead>
              <TableHead className="w-[200px]">Starts</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {events.map((event) => (
              <TableRow key={event.id}>
                <TableCell className="font-medium">
                  <Link className="hover:underline" to={ctfAdminEventPath(event.id)}>
                    {event.name}
                  </Link>
                </TableCell>
                <TableCell>
                  <Badge variant="secondary">{titleCase(event.status)}</Badge>
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">{formatDateTime(event.event_start)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}

function SummaryTile({ label, value }: Readonly<{ label: string; value: number }>) {
  return (
    <Card>
      <CardContent className="py-4">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      </CardContent>
    </Card>
  );
}

export function AdminDashboardPage() {
  const query = useCtfEvents();
  return (
    <>
      <PageHeader
        title="CTF operations"
        description="Manage your CTF events, challenges, and participants."
        actions={
          <div className="flex items-center gap-2">
            <Link to={ctfAdminEventsPath()} className={cn(buttonVariants({ variant: "outline", size: "sm" }))}>
              All events
            </Link>
            <Link to={ctfAdminEventCreatePath()} className={cn(buttonVariants({ size: "sm" }))}>
              <Plus className="size-4" />
              New event
            </Link>
          </div>
        }
      />
      <DashboardBody query={query} />
    </>
  );
}
