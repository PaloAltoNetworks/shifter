import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Plus } from "lucide-react";

import { useCtfEventChallenges } from "@/api/ctfAdmin";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

import { titleCase } from "../format";
import { LabelFilterRow, distinctLabels, filterByLabels } from "../label-filters";
import { ChallengeTransferControls } from "./ChallengeTransferControls";
import { ctfAdminChallengeCreatePath, ctfAdminChallengePath, ctfAdminEventPath, ctfAdminEventsPath } from "../routes";

function ChallengesBody({ query }: Readonly<{ query: ReturnType<typeof useCtfEventChallenges> }>) {
  const [activeTag, setActiveTag] = useState<string | null>(null);
  const [activeTopic, setActiveTopic] = useState<string | null>(null);
  const allChallenges = useMemo(() => query.data?.challenges ?? [], [query.data]);
  const filtered = useMemo(
    () => filterByLabels(allChallenges, activeTag, activeTopic),
    [allChallenges, activeTag, activeTopic],
  );

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
          <AlertTitle>Could not load challenges</AlertTitle>
          <AlertDescription>Please retry.</AlertDescription>
        </Alert>
      </div>
    );
  }

  const challenges = filtered;
  if (challenges.length === 0 && allChallenges.length === 0) {
    return (
      <div className="grid place-items-center px-6 py-16 text-center">
        <p className="text-sm font-medium">No challenges yet</p>
        <p className="mt-1 text-sm text-muted-foreground">Add the first challenge to this event.</p>
      </div>
    );
  }

  return (
    <div>
      <div className="flex flex-col gap-2 border-b border-border/60 p-4">
        <LabelFilterRow
          axis="tags"
          labels={distinctLabels(allChallenges, "tags")}
          active={activeTag}
          onToggle={(value) => setActiveTag(activeTag === value ? null : value)}
        />
        <LabelFilterRow
          axis="topics"
          labels={distinctLabels(allChallenges, "topics")}
          active={activeTopic}
          onToggle={(value) => setActiveTopic(activeTopic === value ? null : value)}
        />
        {challenges.length === 0 ? (
          <p className="text-sm text-muted-foreground">No challenges match this filter.</p>
        ) : null}
      </div>
      <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="w-[70px]">Order</TableHead>
          <TableHead>Name</TableHead>
          <TableHead className="w-[130px]">Category</TableHead>
          <TableHead className="w-[120px]">Difficulty</TableHead>
          <TableHead className="w-[80px] text-right">Points</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {challenges.map((challenge) => (
          <TableRow key={challenge.id}>
            <TableCell className="font-mono text-sm tabular-nums text-muted-foreground">{challenge.order}</TableCell>
            <TableCell className="font-medium">
              <Link className="hover:underline" to={ctfAdminChallengePath(challenge.id)}>
                {challenge.name}
              </Link>
            </TableCell>
            <TableCell>
              {challenge.category ? <Badge variant="secondary">{titleCase(challenge.category)}</Badge> : "—"}
            </TableCell>
            <TableCell className="text-sm text-muted-foreground">
              {challenge.difficulty ? titleCase(challenge.difficulty) : "—"}
            </TableCell>
            <TableCell className="text-right font-mono text-sm tabular-nums">{challenge.points}</TableCell>
          </TableRow>
        ))}
      </TableBody>
      </Table>
    </div>
  );
}

export function ChallengesAdminPage() {
  const params = useParams();
  const eventId = params.eventId ?? "";
  const query = useCtfEventChallenges(eventId);
  const count = query.data?.challenges.length ?? 0;
  const countNoun = count === 1 ? "challenge" : "challenges";
  const description = query.data ? `${count} ${countNoun}` : "Event challenges";

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
        <span className="text-foreground">Challenges</span>
      </nav>

      <PageHeader
        title="Challenges"
        description={description}
        actions={
          <div className="flex items-center gap-2">
            <ChallengeTransferControls eventId={eventId} />
            <Link to={ctfAdminChallengeCreatePath(eventId)} className={cn(buttonVariants({ size: "sm" }))}>
              <Plus className="size-4" />
              New challenge
            </Link>
          </div>
        }
      />
      <Card className="overflow-hidden py-0" aria-busy={query.isFetching}>
        <ChallengesBody query={query} />
      </Card>
    </>
  );
}
