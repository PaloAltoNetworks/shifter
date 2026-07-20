import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { useCtfOrganizerScoreboard } from "@/api/ctf";
import { useAnnounceCtfNotification,
  useCancelCtfScheduledNotification, useCtfEventRanges, useCtfNotifications, useCtfParticipants, useCtfScoreTimeline, useProvisionCtfEventRanges, useProvisionCtfEventSpares, useSendCtfNotification } from "@/api/ctfAdmin";
import { describeMutationError } from "@/api/errors";
import type { CtfOrganizerScoreboard } from "@/api/types";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";

import { formatDateTime, rankingKey, rankingNumber, rankingString, titleCase } from "../format";
import { EventTasksCard } from "./EventTasksCard";
import { ResultsExportButton } from "./ResultsExportButton";
import { ctfAdminEventPath, ctfAdminEventsPath } from "../routes";

export type MonitoringTab = "scoreboard" | "ranges" | "notifications" | "analytics";

function ScoreboardTab({ eventId }: Readonly<{ eventId: string }>) {
  const query = useCtfOrganizerScoreboard(eventId, undefined, Boolean(eventId));

  if (query.isLoading) return <Skeleton className="h-64 w-full" />;
  if (query.isError || !query.data) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Could not load the scoreboard</AlertTitle>
        <AlertDescription>Please retry.</AlertDescription>
      </Alert>
    );
  }

  const data: CtfOrganizerScoreboard = query.data;
  const rows = data.rankings ?? [];
  const teamMode = Boolean(data.team_mode);

  if (rows.length === 0) {
    return (
      <Card>
        <CardContent className="grid place-items-center px-6 py-16 text-center">
          <p className="text-sm font-medium">No scores yet</p>
          <p className="mt-1 text-sm text-muted-foreground">Rankings appear once participants start solving.</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <>
      {data.frozen ? <Badge variant="secondary" className="mb-3">Frozen</Badge> : null}
      <Card className="overflow-hidden py-0">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="w-[70px]">Rank</TableHead>
              <TableHead>{teamMode ? "Team" : "Name"}</TableHead>
              <TableHead className="w-[100px]">Score</TableHead>
              <TableHead className="w-[100px]">Solves</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row, index) => (
              <TableRow key={rankingKey(row, index)}>
                <TableCell className="font-medium">{rankingNumber(row, "rank") ?? index + 1}</TableCell>
                <TableCell>{rankingString(row, "name")}</TableCell>
                <TableCell>{rankingNumber(row, "score") ?? 0}</TableCell>
                <TableCell>{rankingNumber(row, "solve_count") ?? 0}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
    </>
  );
}

function renderRangesBody(query: ReturnType<typeof useCtfEventRanges>): React.ReactNode {
  if (query.isLoading) return <Skeleton className="h-48 w-full" />;
  if (query.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Could not load ranges</AlertTitle>
        <AlertDescription>Please retry.</AlertDescription>
      </Alert>
    );
  }
  if ((query.data?.ranges.length ?? 0) === 0) {
    return (
      <Card>
        <CardContent className="grid place-items-center px-6 py-16 text-center">
          <p className="text-sm font-medium">No participant ranges yet</p>
          <p className="mt-1 text-sm text-muted-foreground">Provision ranges to give participants access.</p>
        </CardContent>
      </Card>
    );
  }
  return (
    <Card className="overflow-hidden py-0">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Participant</TableHead>
            <TableHead>Email</TableHead>
            <TableHead className="w-[140px]">Range status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {(query.data?.ranges ?? []).map((range) => (
            <TableRow key={range.participant_id}>
              <TableCell className="font-medium">{range.name}</TableCell>
              <TableCell className="text-sm text-muted-foreground">{range.email}</TableCell>
              <TableCell>
                <Badge variant="secondary">{titleCase(range.range_status)}</Badge>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  );
}

function RangesTab({ eventId }: Readonly<{ eventId: string }>) {
  const query = useCtfEventRanges(eventId, Boolean(eventId));
  const provision = useProvisionCtfEventRanges(eventId);
  const spares = useProvisionCtfEventSpares(eventId);
  const [spareCount, setSpareCount] = useState("1");
  const error = describeMutationError(provision.error ?? spares.error, "Could not run the range action.");

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <Button size="sm" disabled={provision.isPending} onClick={() => provision.mutate()}>
          Provision all ranges
        </Button>
        <div className="flex items-end gap-2">
          <div className="flex flex-col gap-2">
            <Label htmlFor="spare-count">Spares</Label>
            <Input
              id="spare-count"
              type="number"
              min={1}
              value={spareCount}
              onChange={(e) => setSpareCount(e.target.value)}
              className="w-24"
            />
          </div>
          <Button
            variant="outline"
            size="sm"
            disabled={spares.isPending}
            onClick={() => spares.mutate(Math.max(1, Number(spareCount) || 1))}
          >
            Provision spares
          </Button>
        </div>
      </div>
      {error ? (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
      {renderRangesBody(query)}
    </div>
  );
}

function AnnounceDialog({ eventId, open, onOpenChange }: Readonly<{ eventId: string; open: boolean; onOpenChange: (open: boolean) => void }>) {
  const announce = useAnnounceCtfNotification(eventId);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [scheduledAt, setScheduledAt] = useState("");
  const error = describeMutationError(announce.error, "Could not create the announcement.");

  function reset() {
    announce.reset();
    setSubject("");
    setBody("");
    setScheduledAt("");
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New announcement</DialogTitle>
          <DialogDescription>Draft an announcement for this event. You can send it after creating it.</DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (!subject.trim() || !body.trim()) return;
            announce.mutate(
              {
                subject: subject.trim(),
                body: body.trim(),
                ...(scheduledAt ? { scheduled_at: new Date(scheduledAt).toISOString() } : {}),
              },
              {
                onSuccess: () => {
                  reset();
                  onOpenChange(false);
                },
              },
            );
          }}
        >
          <div className="flex flex-col gap-2">
            <Label htmlFor="ann-subject">Subject</Label>
            <Input id="ann-subject" value={subject} onChange={(e) => setSubject(e.target.value)} />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="ann-body">Body</Label>
            <Textarea id="ann-body" rows={4} value={body} onChange={(e) => setBody(e.target.value)} />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="ann-schedule">Schedule for later (optional)</Label>
            <Input
              id="ann-schedule"
              type="datetime-local"
              value={scheduledAt}
              onChange={(e) => setScheduledAt(e.target.value)}
            />
          </div>
          {error ? (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)} disabled={announce.isPending}>
              Cancel
            </Button>
            <Button type="submit" disabled={announce.isPending || !subject.trim() || !body.trim()}>
              {scheduledAt ? "Schedule" : "Send now"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function SendButton({ eventId, notificationId, status }: Readonly<{ eventId: string; notificationId: string; status: string }>) {
  const send = useSendCtfNotification(eventId);
  const cancelSchedule = useCancelCtfScheduledNotification(eventId);
  if (status === "sent") return <span className="text-xs text-muted-foreground">Sent</span>;
  if (status === "scheduled") {
    return (
      <Button
        variant="outline"
        size="sm"
        disabled={cancelSchedule.isPending}
        onClick={() => cancelSchedule.mutate(notificationId)}
      >
        Cancel schedule
      </Button>
    );
  }
  return (
    <Button variant="outline" size="sm" disabled={send.isPending} onClick={() => send.mutate(notificationId)}>
      {send.isSuccess ? "Queued" : "Send"}
    </Button>
  );
}

function renderNotificationsBody(query: ReturnType<typeof useCtfNotifications>, eventId: string): React.ReactNode {
  if (query.isLoading) return <Skeleton className="h-48 w-full" />;
  if (query.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Could not load notifications</AlertTitle>
        <AlertDescription>Please retry.</AlertDescription>
      </Alert>
    );
  }
  const notifications = query.data?.notifications ?? [];
  if (notifications.length === 0) {
    return (
      <Card>
        <CardContent className="grid place-items-center px-6 py-16 text-center">
          <p className="text-sm font-medium">No notifications yet</p>
          <p className="mt-1 text-sm text-muted-foreground">Create an announcement to notify participants.</p>
        </CardContent>
      </Card>
    );
  }
  return (
    <Card className="overflow-hidden py-0">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Subject</TableHead>
            <TableHead className="w-[130px]">Type</TableHead>
            <TableHead className="w-[120px]">Status</TableHead>
            <TableHead className="w-[90px] text-right">Sent</TableHead>
            <TableHead className="w-[110px] text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {notifications.map((notification) => (
            <TableRow key={notification.id}>
              <TableCell className="font-medium">{notification.subject}</TableCell>
              <TableCell className="text-sm text-muted-foreground">{titleCase(notification.notification_type)}</TableCell>
              <TableCell>
                <Badge variant="secondary">{titleCase(notification.status)}</Badge>
              </TableCell>
              <TableCell className="text-right font-mono text-sm tabular-nums">{notification.sent_count}</TableCell>
              <TableCell className="text-right">
                <SendButton eventId={eventId} notificationId={notification.id} status={notification.status} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  );
}

function NotificationsTab({ eventId }: Readonly<{ eventId: string }>) {
  const query = useCtfNotifications(eventId);
  const [announcing, setAnnouncing] = useState(false);

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button size="sm" onClick={() => setAnnouncing(true)}>
          New announcement
        </Button>
      </div>
      {renderNotificationsBody(query, eventId)}
      <AnnounceDialog eventId={eventId} open={announcing} onOpenChange={setAnnouncing} />
    </div>
  );
}

function renderAnalyticsBody(
  participantId: string,
  timeline: ReturnType<typeof useCtfScoreTimeline>,
): React.ReactNode {
  if (!participantId) {
    return <p className="text-sm text-muted-foreground">Select a participant to see their score timeline.</p>;
  }
  if (timeline.isLoading) return <Skeleton className="h-48 w-full" />;
  if (timeline.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Could not load the score timeline</AlertTitle>
        <AlertDescription>Please retry.</AlertDescription>
      </Alert>
    );
  }
  const rows = timeline.data?.timeline ?? [];
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">No scoring activity yet for this participant.</p>;
  }
  return (
    <Card className="overflow-hidden py-0">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>When</TableHead>
            <TableHead>Challenge</TableHead>
            <TableHead className="w-[100px] text-right">Points</TableHead>
            <TableHead className="w-[120px] text-right">Total</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow key={rankingKey(row, index)}>
              <TableCell className="text-sm text-muted-foreground">
                {formatDateTime(rankingString(row, "timestamp") || rankingString(row, "solved_at"))}
              </TableCell>
              <TableCell>{rankingString(row, "challenge_name") || "—"}</TableCell>
              <TableCell className="text-right font-mono text-sm tabular-nums">
                {rankingNumber(row, "points") ?? 0}
              </TableCell>
              <TableCell className="text-right font-mono text-sm tabular-nums">
                {rankingNumber(row, "cumulative_score") ?? rankingNumber(row, "total_score") ?? 0}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  );
}

function AnalyticsTab({ eventId }: Readonly<{ eventId: string }>) {
  const participants = useCtfParticipants(eventId, Boolean(eventId));
  const [participantId, setParticipantId] = useState("");
  const timeline = useCtfScoreTimeline(participantId, Boolean(participantId));
  const options = participants.data?.participants ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-2">
        <Label htmlFor="analytics-participant">Participant</Label>
        <Select value={participantId} onValueChange={setParticipantId}>
          <SelectTrigger id="analytics-participant" size="sm" className="w-[260px]">
            <SelectValue placeholder="Select a participant" />
          </SelectTrigger>
          <SelectContent>
            {options.map((participant) => (
              <SelectItem key={participant.id} value={participant.id}>
                {participant.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {renderAnalyticsBody(participantId, timeline)}
    </div>
  );
}

export function MonitoringPage({ defaultTab = "scoreboard" }: Readonly<{ defaultTab?: MonitoringTab }>) {
  const params = useParams();
  const eventId = params.eventId ?? "";

  return (
    <>
      <nav className="mb-3 text-sm text-muted-foreground" aria-label="Breadcrumb">
        <Link className="hover:text-foreground" to={ctfAdminEventsPath()}>
          Events
        </Link>
        <span className="px-1.5">/</span>
        <Link className="hover:text-foreground" to={ctfAdminEventPath(eventId)}>
          Event
        </Link>
        <span className="px-1.5">/</span>
        <span className="text-foreground">Monitoring</span>
      </nav>

      <PageHeader title="Monitoring" description="Live scoreboard, ranges, notifications, and analytics" />

      <Tabs defaultValue={defaultTab}>
        <TabsList>
          <TabsTrigger value="scoreboard">Scoreboard</TabsTrigger>
          <TabsTrigger value="ranges">Ranges</TabsTrigger>
          <TabsTrigger value="notifications">Notifications</TabsTrigger>
          <TabsTrigger value="analytics">Analytics</TabsTrigger>
          <TabsTrigger value="tasks">Tasks</TabsTrigger>
        </TabsList>
        <TabsContent value="scoreboard" className="mt-4">
          <ScoreboardTab eventId={eventId} />
        </TabsContent>
        <TabsContent value="ranges" className="mt-4">
          <RangesTab eventId={eventId} />
        </TabsContent>
        <TabsContent value="notifications" className="mt-4">
          <NotificationsTab eventId={eventId} />
        </TabsContent>
        <TabsContent value="analytics" className="mt-4">
          <div className="mb-3 flex justify-end">
            <ResultsExportButton eventId={eventId} />
          </div>
          <AnalyticsTab eventId={eventId} />
        </TabsContent>
        <TabsContent value="tasks" className="mt-4">
          <EventTasksCard eventId={eventId} />
        </TabsContent>
      </Tabs>
    </>
  );
}
