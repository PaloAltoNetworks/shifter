import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { useCtfOrganizerScoreboard } from "@/api/ctf";
import { useAssignCtfBracket, useCtfEventRanges, useCtfParticipant, useCtfParticipantRangeAction, useGrantCtfAward, useResendCtfInvite, useRevokeCtfAward, type CtfRangeAction } from "@/api/ctfAdmin";
import { describeMutationError } from "@/api/errors";
import type { CtfOrganizerParticipantDetail } from "@/api/types";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";

import { ConfirmDialog } from "@/components/confirm-dialog";

import { ParticipantModerationCard } from "./ParticipantModerationCard";
import { formatDateTime, titleCase } from "../format";
import { ctfAdminEventParticipantsPath, ctfAdminEventsPath } from "../routes";

const NO_BRACKET = "__none__";
const LIFECYCLE: ReadonlyArray<{ action: Exclude<CtfRangeAction, "destroy">; label: string }> = [
  { action: "provision", label: "Provision" },
  { action: "start", label: "Start" },
  { action: "stop", label: "Stop" },
  { action: "restart", label: "Restart" },
];

function Detail({ label, value }: Readonly<{ label: string; value: React.ReactNode }>) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 text-sm">{value}</dd>
    </div>
  );
}

function RangeControls({
  participant,
}: Readonly<{ participant: CtfOrganizerParticipantDetail }>) {
  const eventId = participant.event_id;
  const ranges = useCtfEventRanges(eventId, Boolean(eventId));
  const action = useCtfParticipantRangeAction(participant.id, eventId);
  const [confirmingDestroy, setConfirmingDestroy] = useState(false);
  const error = describeMutationError(action.error, "Could not run the range action.");

  const row = ranges.data?.ranges.find((r) => r.participant_id === participant.id);
  const rangeStatus = action.data?.status ?? row?.range_status ?? "unknown";

  return (
    <Card>
      <CardContent>
        <div className="mb-4 flex items-center gap-2">
          <span className="text-sm text-muted-foreground">Range status</span>
          <Badge variant="secondary">{titleCase(rangeStatus)}</Badge>
        </div>
        <div className="flex flex-wrap gap-2">
          {LIFECYCLE.map(({ action: act, label }) => (
            <Button
              key={act}
              variant="outline"
              size="sm"
              disabled={action.isPending}
              onClick={() => action.mutate(act)}
            >
              {label}
            </Button>
          ))}
          <Button variant="destructive" size="sm" disabled={action.isPending} onClick={() => setConfirmingDestroy(true)}>
            Destroy
          </Button>
        </div>
        {error ? (
          <Alert variant="destructive" className="mt-3">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}
      </CardContent>

      <ConfirmDialog
        open={confirmingDestroy}
        title="Destroy this range?"
        confirmLabel="Destroy"
        destructive
        pending={action.isPending}
        error={action.error}
        onOpenChange={(open) => {
          if (!open) {
            action.reset();
            setConfirmingDestroy(false);
          }
        }}
        onConfirm={() => action.mutate("destroy", { onSuccess: () => setConfirmingDestroy(false) })}
      >
        The participant loses access and any in-range work is lost. This cannot be undone.
      </ConfirmDialog>
    </Card>
  );
}

function BracketControl({ participant }: Readonly<{ participant: CtfOrganizerParticipantDetail }>) {
  const eventId = participant.event_id;
  const scoreboard = useCtfOrganizerScoreboard(eventId, undefined, Boolean(eventId));
  const assign = useAssignCtfBracket(participant.id);
  const brackets = scoreboard.data?.brackets ?? [];
  const error = describeMutationError(assign.error, "Could not assign the bracket.");

  if (brackets.length === 0) return null;

  return (
    <Card>
      <CardContent>
        <div className="flex flex-col gap-2">
          <Label htmlFor="bracket-select">Bracket</Label>
          <Select
            defaultValue={participant.bracket_id ?? NO_BRACKET}
            onValueChange={(value) => assign.mutate(value === NO_BRACKET ? null : value)}
          >
            <SelectTrigger id="bracket-select" size="sm" className="w-[220px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_BRACKET}>No bracket</SelectItem>
              {brackets.map((bracket) => (
                <SelectItem key={bracket.id} value={bracket.id}>
                  {bracket.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {error ? (
          <Alert variant="destructive" className="mt-3">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}
      </CardContent>
    </Card>
  );
}

function ResendControl({ participantId }: Readonly<{ participantId: string }>) {
  const resend = useResendCtfInvite(participantId);
  const error = describeMutationError(resend.error, "Could not resend the invitation.");
  return (
    <div className="flex flex-col items-end gap-1">
      <Button variant="outline" size="sm" disabled={resend.isPending} onClick={() => resend.mutate()}>
        {resend.isSuccess ? "Invitation sent" : "Resend invitation"}
      </Button>
      {error ? <span className="text-xs text-destructive">{error}</span> : null}
    </div>
  );
}


function AwardsCard({ participant }: Readonly<{ participant: CtfOrganizerParticipantDetail }>) {
  const grant = useGrantCtfAward(participant.id);
  const revoke = useRevokeCtfAward(participant.id);
  const [points, setPoints] = useState("");
  const [reason, setReason] = useState("");
  const parsedPoints = Number(points.trim());
  const canGrant = points.trim() !== "" && Number.isInteger(parsedPoints) && parsedPoints !== 0 && reason.trim() !== "";

  return (
    <Card>
      <CardContent>
        <h2 className="text-sm font-semibold">Awards</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Bonus points (positive) or deductions (negative) outside challenge solves. They count toward the total score.
        </p>
        {participant.awards.length > 0 ? (
          <ul className="mt-3 divide-y divide-border/60">
            {participant.awards.map((award) => (
              <li key={award.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                <span>
                  <span className="font-mono tabular-nums">{award.points > 0 ? `+${award.points}` : award.points}</span>
                  <span className="ml-2">{award.reason}</span>
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  disabled={revoke.isPending}
                  onClick={() => revoke.mutate(award.id)}
                >
                  Revoke
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-3 text-sm text-muted-foreground">No awards granted.</p>
        )}
        <form
          className="mt-4 flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (!canGrant) return;
            grant.mutate(
              { points: parsedPoints, reason: reason.trim() },
              { onSuccess: () => { setPoints(""); setReason(""); } },
            );
          }}
        >
          <div className="flex flex-col gap-1">
            <Label htmlFor="award-points">Points</Label>
            <Input
              id="award-points"
              type="number"
              className="w-28"
              value={points}
              onChange={(event) => setPoints(event.target.value)}
            />
          </div>
          <div className="flex min-w-56 flex-1 flex-col gap-1">
            <Label htmlFor="award-reason">Reason</Label>
            <Input id="award-reason" value={reason} onChange={(event) => setReason(event.target.value)} />
          </div>
          <Button type="submit" disabled={!canGrant || grant.isPending}>
            Grant award
          </Button>
        </form>
        {grant.isError ? (
          <p className="mt-2 text-xs text-destructive">{describeMutationError(grant.error, "Could not grant the award.")}</p>
        ) : null}
      </CardContent>
    </Card>
  );
}

export function ParticipantDetailPage() {
  const params = useParams();
  const participantId = params.participantId ?? "";
  const query = useCtfParticipant(participantId);

  if (query.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-9 w-72" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (query.isError || !query.data) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Participant unavailable</AlertTitle>
        <AlertDescription>
          This participant was not found or has been removed.{" "}
          <Link className="underline" to={ctfAdminEventsPath()}>
            Back to events
          </Link>
          .
        </AlertDescription>
      </Alert>
    );
  }

  const participant = query.data;

  return (
    <>
      <nav className="mb-3 text-sm text-muted-foreground" aria-label="Breadcrumb">
        <Link className="hover:text-foreground" to={ctfAdminEventParticipantsPath(participant.event_id)}>
          Participants
        </Link>
        <span className="px-1.5">/</span>
        <span className="text-foreground">{participant.name}</span>
      </nav>

      <PageHeader
        title={participant.name}
        description={participant.email}
        actions={<ResendControl participantId={participant.id} />}
      />

      <div className="space-y-6">
        <Card>
          <CardContent>
            <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <Detail label="Status" value={<Badge variant="secondary">{titleCase(participant.status)}</Badge>} />
              <Detail label="Team" value={participant.team_name || "—"} />
              <Detail label="Total score" value={participant.total_score} />
              <Detail label="Solved" value={participant.solved_count} />
              <Detail label="Attempts" value={participant.attempt_count} />
              <Detail label="Registered" value={formatDateTime(participant.registered_at)} />
              <Detail label="Invited" value={formatDateTime(participant.invited_at)} />
              <Detail label="Last active" value={formatDateTime(participant.last_active_at)} />
            </dl>
          </CardContent>
        </Card>

        <AwardsCard participant={participant} />
        <ParticipantModerationCard participant={participant} />
        <BracketControl participant={participant} />
        <RangeControls participant={participant} />
      </div>
    </>
  );
}
