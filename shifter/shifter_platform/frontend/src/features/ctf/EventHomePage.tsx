import { useEffect, useState } from "react";
import { Link } from "react-router";

import { BookOpen, Flag, Server, Trophy, UserCog, Users } from "lucide-react";

import { useCtfAnnouncements, useCtfBriefing, useCtfCurrentEvent, useCtfPages } from "@/api/ctf";
import { ApiError } from "@/api/errors";
import type { CtfCurrentEvent } from "@/api/types";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import { titleCase, formatDateTime } from "./format";
import { MarkdownContent } from "./MarkdownContent";
import {
  ctfAccountPath,
  ctfBriefingPath,
  ctfChallengesPath,
  ctfRangePath,
  ctfScoreboardPath,
  ctfTeamPath,
} from "./routes";

const QUICK_LINKS = [
  { to: ctfChallengesPath(), label: "Challenges", icon: Flag },
  { to: ctfScoreboardPath(), label: "Scoreboard", icon: Trophy },
  { to: ctfTeamPath(), label: "Team", icon: Users },
  { to: ctfRangePath(), label: "Range", icon: Server },
  { to: ctfAccountPath(), label: "Account", icon: UserCog },
] as const;

function Stat({ label, value }: Readonly<{ label: string; value: string | number }>) {
  return (
    <div className="rounded-lg border border-border/60 p-4">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 text-2xl font-semibold tracking-tight">{value}</dd>
    </div>
  );
}

function formatRemaining(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (days > 0) return `${days}d ${hours}h ${minutes}m`;
  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`;
  return `${minutes}m ${seconds}s`;
}

/** Countdown to event start (before start) or event end (CTF-702). */
function EventCountdown({ event }: Readonly<{ event: CtfCurrentEvent["event"] }>) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = globalThis.setInterval(() => setNow(Date.now()), 1000);
    return () => globalThis.clearInterval(timer);
  }, []);

  if (!event.event_start || !event.event_end) return null;
  const start = new Date(event.event_start).getTime();
  const end = new Date(event.event_end).getTime();
  let label: string;
  let value: string;
  if (now < start) {
    label = "Starts in";
    value = formatRemaining(start - now);
  } else if (now < end) {
    label = "Ends in";
    value = formatRemaining(end - now);
  } else {
    label = "Event";
    value = "Ended";
  }
  return (
    <div className="rounded-lg border border-border/60 p-4">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 text-2xl font-semibold tracking-tight tabular-nums" aria-live="off">
        {value}
      </dd>
    </div>
  );
}

/** Local-timezone schedule facts (CTF-702/705). */
function EventSchedule({ event }: Readonly<{ event: CtfCurrentEvent["event"] }>) {
  return (
    <p className="mb-6 text-xs text-muted-foreground">
      {event.event_start ? <>Starts {formatDateTime(event.event_start)}</> : null}
      {event.event_end ? <> · Ends {formatDateTime(event.event_end)}</> : null}
      {event.registration_deadline ? <> · Registration closes {formatDateTime(event.registration_deadline)}</> : null}
    </p>
  );
}

/** Past announcements feed for the current event (CTF-803). */
function AnnouncementsCard() {
  const query = useCtfAnnouncements();
  const announcements = query.data?.announcements ?? [];
  if (!announcements.length) return null;
  return (
    <Card className="mb-6">
      <CardContent>
        <h2 className="text-sm font-semibold">Announcements</h2>
        <ul className="mt-2 space-y-4">
          {announcements.map((announcement) => (
            <li key={announcement.id}>
              <p className="text-sm font-medium">{announcement.subject}</p>
              {announcement.sent_at ? (
                <p className="text-xs text-muted-foreground">{formatDateTime(announcement.sent_at)}</p>
              ) : null}
              <div className="mt-1 text-sm">
                <MarkdownContent text={announcement.body} />
              </div>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

/** Custom informational pages authored by the organizer (CTF-1303). */
function PagesCard() {
  const query = useCtfPages();
  const pages = query.data?.pages ?? [];
  if (!pages.length) return null;
  return (
    <Card className="mb-6">
      <CardContent>
        <h2 className="text-sm font-semibold">Event pages</h2>
        <div className="mt-2 space-y-2">
          {pages.map((page) => (
            <details key={page.id} className="rounded border border-border/60 p-2">
              <summary className="cursor-pointer text-sm font-medium">{page.title}</summary>
              <div className="mt-2 text-sm">
                <MarkdownContent text={page.body} />
              </div>
            </details>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

/**
 * Briefing entry point on the event home: a bounded retry when the lookup
 * failed, the banner when a briefing is present, nothing otherwise. A fetch
 * failure is never treated as absence (#1854).
 */
function BriefingEntry({ query }: Readonly<{ query: ReturnType<typeof useCtfBriefing> }>) {
  if (query.isError) {
    return (
      <Alert variant="destructive" className="mb-6">
        <AlertTitle>Could not check for a briefing</AlertTitle>
        <AlertDescription>
          <button
            type="button"
            className={cn(buttonVariants({ variant: "outline", size: "sm" }), "mt-2")}
            onClick={() => query.refetch()}
          >
            Retry
          </button>
        </AlertDescription>
      </Alert>
    );
  }
  if (query.data) {
    return (
      <Alert className="mb-6">
        <AlertTitle>Event briefing</AlertTitle>
        <AlertDescription>
          The organizer has published a briefing for this event.{" "}
          <Link className="underline" to={ctfBriefingPath()}>
            Open the briefing
          </Link>
        </AlertDescription>
      </Alert>
    );
  }
  return null;
}

function EventOverview({ data }: Readonly<{ data: CtfCurrentEvent }>) {
  const { event, participant } = data;
  // A published briefing gets a prominent entry point here (participants used to
  // open the workspace with no briefing and no starting point, #1854). A fetch
  // failure is NOT absence: only a resolved briefing shows the banner + quick
  // link; a failed lookup shows a bounded retry rather than silently hiding the
  // entry point.
  const briefingQuery = useCtfBriefing();
  const briefing = briefingQuery.data;
  const quickLinks = briefing ? [{ to: ctfBriefingPath(), label: "Briefing", icon: BookOpen }, ...QUICK_LINKS] : QUICK_LINKS;
  return (
    <>
      {event.theme_color ? (
        <div className="mb-3 h-1 w-full rounded" style={{ backgroundColor: event.theme_color }} aria-hidden />
      ) : null}
      {event.logo_url ? (
        <img src={event.logo_url} alt={`${event.name} logo`} className="mb-3 h-12 w-auto" />
      ) : null}
      <PageHeader
        title={event.name}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">{titleCase(event.status)}</Badge>
            {participant.team ? <span>Team: {participant.team.name}</span> : <span>Solo</span>}
            {participant.bracket ? <span>· Bracket: {participant.bracket.name}</span> : null}
          </span>
        }
      />

      <EventSchedule event={event} />

      <BriefingEntry query={briefingQuery} />

      <AnnouncementsCard />

      <PagesCard />

      {event.description ? (
        <Card className="mb-6">
          <CardContent>
            <p className="text-sm whitespace-pre-wrap">{event.description}</p>
          </CardContent>
        </Card>
      ) : null}

      {event.rules ? (
        <Card className="mb-6">
          <CardContent>
            <h2 className="text-sm font-semibold">Rules</h2>
            <div className="mt-2">
              <MarkdownContent text={event.rules} />
            </div>
          </CardContent>
        </Card>
      ) : null}

      <dl className="mb-8 grid gap-4 sm:grid-cols-4">
        <EventCountdown event={event} />
        <Stat label="Score" value={participant.cached_score} />
        <Stat label="Solves" value={participant.cached_solve_count} />
        <Stat label="Status" value={titleCase(participant.status)} />
      </dl>

      <h2 className="mb-3 text-sm font-semibold">Quick links</h2>
      <nav aria-label="Workspace quick links" className="flex flex-wrap gap-2">
        {quickLinks.map(({ to, label, icon: Icon }) => (
          <Link key={to} to={to} className={cn(buttonVariants({ variant: "outline", size: "sm" }))}>
            <Icon className="size-4" />
            {label}
          </Link>
        ))}
      </nav>
    </>
  );
}

export function EventHomePage() {
  const query = useCtfCurrentEvent();

  if (query.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-9 w-64" />
        <div className="grid gap-4 sm:grid-cols-3">
          {[0, 1, 2].map((row) => (
            <Skeleton key={row} className="h-24 w-full" />
          ))}
        </div>
      </div>
    );
  }

  if (query.error instanceof ApiError && query.error.status === 404) {
    return (
      <>
        <PageHeader title="Event Home" />
        <Alert>
          <AlertTitle>No active event</AlertTitle>
          <AlertDescription>
            You are not currently enrolled in an active CTF event. When an organizer invites you, your event will appear
            here.
          </AlertDescription>
        </Alert>
      </>
    );
  }

  if (query.isError || !query.data) {
    return (
      <>
        <PageHeader title="Event Home" />
        <Alert variant="destructive">
          <AlertTitle>Could not load your event</AlertTitle>
          <AlertDescription>Please retry.</AlertDescription>
        </Alert>
      </>
    );
  }

  return <EventOverview data={query.data} />;
}
