import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Flag, Radar, Users } from "lucide-react";

import { useCtfEvent, useDeleteCtfEvent, useForceDeleteCtfEvent } from "@/api/ctfAdmin";
import { describeMutationError } from "@/api/errors";
import type { CtfEventDetail } from "@/api/types";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import { ConfirmDialog } from "@/components/confirm-dialog";

import { EventLifecycleCard } from "./EventLifecycleCard";
import { EventStaffCard } from "./EventStaffCard";
import { EventPagesCard } from "./EventPagesCard";
import { EventWebhooksCard } from "./EventWebhooksCard";
import { formatDateTime, titleCase } from "../format";
import {
  ctfAdminEventChallengesPath,
  ctfAdminEventEditPath,
  ctfAdminEventMonitoringPath,
  ctfAdminEventParticipantsPath,
  ctfAdminEventsPath,
} from "../routes";

function Detail({ label, value }: Readonly<{ label: string; value: React.ReactNode }>) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 text-sm">{value}</dd>
    </div>
  );
}

function EventLinks({ eventId }: Readonly<{ eventId: string }>) {
  const links = [
    { to: ctfAdminEventChallengesPath(eventId), label: "Challenges", Icon: Flag },
    { to: ctfAdminEventParticipantsPath(eventId), label: "Participants", Icon: Users },
    { to: ctfAdminEventMonitoringPath(eventId), label: "Monitoring", Icon: Radar },
  ];
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {links.map(({ to, label, Icon }) => (
        <Link
          key={to}
          to={to}
          className="flex items-center gap-3 rounded-lg border border-border/60 p-4 transition-colors hover:border-border hover:bg-accent/40 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          <Icon className="size-5 text-muted-foreground" aria-hidden="true" />
          <span className="font-medium">{label}</span>
        </Link>
      ))}
    </div>
  );
}

function ForceDeleteDialog({
  event,
  open,
  onOpenChange,
}: Readonly<{ event: CtfEventDetail; open: boolean; onOpenChange: (open: boolean) => void }>) {
  const navigate = useNavigate();
  const forceDelete = useForceDeleteCtfEvent(event.id);
  const [confirmName, setConfirmName] = useState("");
  const error = describeMutationError(forceDelete.error, "Could not force-delete the event.");
  const matches = confirmName.trim() === event.name;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          forceDelete.reset();
          setConfirmName("");
        }
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Force delete event</DialogTitle>
          <DialogDescription>
            This destroys all provisioned ranges and permanently removes the event and its data. This cannot be undone.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-2">
          <Label htmlFor="force-confirm">
            Type the event name (<span className="font-medium">{event.name}</span>) to confirm
          </Label>
          <Input
            id="force-confirm"
            value={confirmName}
            autoComplete="off"
            onChange={(e) => setConfirmName(e.target.value)}
          />
        </div>
        {error ? (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={forceDelete.isPending}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            disabled={!matches || forceDelete.isPending}
            onClick={() =>
              forceDelete.mutate(confirmName.trim(), { onSuccess: () => navigate(ctfAdminEventsPath()) })
            }
          >
            Force delete
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function EventOverview({ event }: Readonly<{ event: CtfEventDetail }>) {
  return (
    <Card>
      <CardContent>
        {event.description ? <p className="mb-5 text-sm whitespace-pre-wrap">{event.description}</p> : null}
        <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Detail label="Status" value={<Badge variant="secondary">{titleCase(event.status)}</Badge>} />
          <Detail label="Mode" value={event.team_mode ? "Team" : "Solo"} />
          <Detail label="Scenario" value={event.scenario_id || "—"} />
          <Detail label="Starts" value={formatDateTime(event.event_start)} />
          <Detail label="Ends" value={formatDateTime(event.event_end)} />
          <Detail label="Registration deadline" value={formatDateTime(event.registration_deadline)} />
          <Detail label="Max participants" value={event.max_participants ?? "Unlimited"} />
          <Detail label="Range spin-up" value={`${event.range_spinup_minutes} min`} />
          <Detail label="Scoreboard" value={event.scoreboard_visible ? "Visible" : "Hidden"} />
        </dl>
      </CardContent>
    </Card>
  );
}

export function EventDetailPage() {
  const params = useParams();
  const eventId = params.eventId ?? "";
  const query = useCtfEvent(eventId);
  const navigate = useNavigate();
  const del = useDeleteCtfEvent();
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [confirmingForce, setConfirmingForce] = useState(false);

  if (query.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-9 w-72" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  if (query.isError || !query.data) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Event unavailable</AlertTitle>
        <AlertDescription>
          This event was not found or has been removed.{" "}
          <Link className="underline" to={ctfAdminEventsPath()}>
            Back to events
          </Link>
          .
        </AlertDescription>
      </Alert>
    );
  }

  const event = query.data;

  return (
    <>
      <nav className="mb-3 text-sm text-muted-foreground" aria-label="Breadcrumb">
        <Link className="hover:text-foreground" to={ctfAdminEventsPath()}>
          Events
        </Link>
        <span className="px-1.5">/</span>
        <span className="text-foreground">{event.name}</span>
      </nav>

      <PageHeader
        title={event.name}
        description="Event overview and management"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Link to={ctfAdminEventEditPath(event.id)} className={cn(buttonVariants({ variant: "outline", size: "sm" }))}>
              Edit
            </Link>
            <Button variant="outline" size="sm" onClick={() => setConfirmingDelete(true)}>
              Delete
            </Button>
            <Button variant="destructive" size="sm" onClick={() => setConfirmingForce(true)}>
              Force delete
            </Button>
          </div>
        }
      />

      <div className="space-y-6">
        <EventLifecycleCard event={event} />
        <EventOverview event={event} />
        <EventStaffCard eventId={event.id} />
        <EventWebhooksCard eventId={event.id} />
        <EventPagesCard eventId={event.id} />
        <EventLinks eventId={event.id} />
      </div>

      <ConfirmDialog
        open={confirmingDelete}
        title="Delete event?"
        confirmLabel="Delete"
        destructive
        pending={del.isPending}
        error={del.error}
        onOpenChange={(open) => {
          if (!open) {
            del.reset();
            setConfirmingDelete(false);
          }
        }}
        onConfirm={() =>
          del.mutate(event.id, {
            onSuccess: () => {
              setConfirmingDelete(false);
              navigate(ctfAdminEventsPath());
            },
          })
        }
      >
        This removes the event. Provisioned ranges are not force-destroyed; use force delete for that.
      </ConfirmDialog>

      <ForceDeleteDialog event={event} open={confirmingForce} onOpenChange={setConfirmingForce} />
    </>
  );
}
