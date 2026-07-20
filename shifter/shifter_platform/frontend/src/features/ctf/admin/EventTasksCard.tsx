import { useState } from "react";

import { useCtfCleanupControl, useCtfEventTasks, useRunCtfTaskNow } from "@/api/ctfAdmin";
import { describeMutationError } from "@/api/errors";
import type { CtfScheduledTask } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import { formatDateTime, titleCase } from "../format";

const STATUS_VARIANT: Readonly<Record<string, "default" | "secondary" | "destructive" | "outline">> = {
  pending: "outline",
  running: "default",
  completed: "secondary",
  failed: "destructive",
  cancelled: "secondary",
};

function TaskRow({
  task,
  eventId,
}: Readonly<{ task: CtfScheduledTask; eventId: string }>) {
  const runNow = useRunCtfTaskNow(eventId);
  return (
    <TableRow>
      <TableCell>{titleCase(task.task_type)}</TableCell>
      <TableCell>
        <Badge variant={STATUS_VARIANT[task.status] ?? "outline"}>{titleCase(task.status)}</Badge>
        {task.retry_count > 0 ? (
          <span className="ml-2 text-xs text-muted-foreground">retry {task.retry_count}</span>
        ) : null}
      </TableCell>
      <TableCell>{formatDateTime(task.scheduled_for)}</TableCell>
      <TableCell>{task.executed_at ? formatDateTime(task.executed_at) : "—"}</TableCell>
      <TableCell className="max-w-64 truncate" title={task.error_message || undefined}>
        {task.error_message || "—"}
      </TableCell>
      <TableCell>
        {task.status === "pending" ? (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={runNow.isPending}
            onClick={() => runNow.mutate(task.id)}
          >
            Run now
          </Button>
        ) : null}
      </TableCell>
    </TableRow>
  );
}

/** Cleanup defer/cancel controls (CTF-1003), shown while cleanup still pends. */
function CleanupControls({ eventId, tasks }: Readonly<{ eventId: string; tasks: CtfScheduledTask[] }>) {
  const control = useCtfCleanupControl(eventId);
  const [hours, setHours] = useState("2");
  const pendingCleanup = tasks.some((t) => t.task_type === "cleanup_ranges" && t.status === "pending");
  const errorMessage = describeMutationError(control.error, "Could not update cleanup.");

  if (!pendingCleanup) return null;
  const parsedHours = Number.parseInt(hours, 10);
  return (
    <div className="flex flex-wrap items-end gap-2">
      <div className="flex w-28 flex-col gap-1">
        <Label htmlFor="cleanup-defer-hours">Defer by (h)</Label>
        <Input
          id="cleanup-defer-hours"
          type="number"
          min={1}
          max={168}
          value={hours}
          onChange={(e) => setHours(e.target.value)}
        />
      </div>
      <Button
        type="button"
        variant="outline"
        disabled={control.isPending || !Number.isFinite(parsedHours) || parsedHours < 1}
        onClick={() => control.mutate({ action: "defer", hours: parsedHours })}
      >
        Defer cleanup
      </Button>
      <Button
        type="button"
        variant="destructive"
        disabled={control.isPending}
        onClick={() => control.mutate({ action: "cancel" })}
      >
        Cancel automated cleanup
      </Button>
      {control.error ? <p className="w-full text-xs text-destructive">{errorMessage}</p> : null}
    </div>
  );
}

/** Scheduled-task history and controls for one event (#526 monitoring surface). */
export function EventTasksCard({ eventId }: Readonly<{ eventId: string }>) {
  const query = useCtfEventTasks(eventId);

  if (query.isLoading) return <Skeleton className="h-40 w-full" />;
  const tasks = query.data?.tasks ?? [];
  return (
    <Card>
      <CardContent className="space-y-4">
        <div>
          <h2 className="text-sm font-semibold">Scheduled tasks</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Automation for this event: spinup, start/end, reminders, cleanup and its participant warning.
            Pending tasks can be run immediately; failed tasks show their error and retry count.
          </p>
        </div>
        <CleanupControls eventId={eventId} tasks={tasks} />
        {tasks.length ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Task</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Scheduled for</TableHead>
                <TableHead>Executed</TableHead>
                <TableHead>Error</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {tasks.map((task) => (
                <TaskRow key={task.id} task={task} eventId={eventId} />
              ))}
            </TableBody>
          </Table>
        ) : (
          <p className="text-xs text-muted-foreground">
            No tasks scheduled yet. Automation is planned when registration opens.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
