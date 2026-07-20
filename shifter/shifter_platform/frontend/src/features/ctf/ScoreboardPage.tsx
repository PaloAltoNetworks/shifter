import { useState } from "react";

import { useCtfCurrentEvent, useCtfScoreboard } from "@/api/ctf";
import { ApiError } from "@/api/errors";
import type { CtfScoreboard } from "@/api/types";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import { rankingKey, rankingNumber, rankingString } from "./format";

const ALL = "all";

function ScoreboardTable({ rows, teamMode }: Readonly<{ rows: Record<string, unknown>[]; teamMode: boolean }>) {
  if (rows.length === 0) {
    return (
      <div className="grid place-items-center px-6 py-16 text-center">
        <p className="text-sm font-medium">No scores yet</p>
        <p className="mt-1 text-sm text-muted-foreground">Rankings appear once participants start solving.</p>
      </div>
    );
  }
  return (
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
  );
}

function ScoreboardContent({
  data,
  bracket,
  onBracketChange,
}: Readonly<{ data: CtfScoreboard; bracket: string; onBracketChange: (value: string) => void }>) {
  if (data.scoreboard_hidden) {
    return (
      <Alert>
        <AlertTitle>Scoreboard hidden</AlertTitle>
        <AlertDescription>The organizer has hidden the scoreboard for this event.</AlertDescription>
      </Alert>
    );
  }

  const brackets = data.brackets ?? [];
  const rows = bracket === ALL ? (data.rankings ?? []) : (data.bracket_rankings ?? []);

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        {data.frozen ? <Badge variant="secondary">Frozen</Badge> : null}
        {brackets.length > 0 ? (
          <Select value={bracket} onValueChange={onBracketChange}>
            <SelectTrigger size="sm" className="w-[180px]" aria-label="Filter by bracket">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All brackets</SelectItem>
              {brackets.map((entry) => (
                <SelectItem key={entry.id} value={entry.id}>
                  {entry.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : null}
      </div>
      <Card className="overflow-hidden py-0">
        <ScoreboardTable rows={rows} teamMode={Boolean(data.team_mode)} />
      </Card>
    </>
  );
}

export function ScoreboardPage() {
  const [bracket, setBracket] = useState<string>(ALL);
  const eventQuery = useCtfCurrentEvent();
  const eventId = eventQuery.data?.event.id ?? "";
  const scoreboard = useCtfScoreboard(eventId, bracket === ALL ? undefined : bracket, Boolean(eventId));

  const loading = eventQuery.isLoading || (Boolean(eventId) && scoreboard.isLoading);

  let body: React.ReactNode;
  if (eventQuery.error instanceof ApiError && eventQuery.error.status === 404) {
    body = (
      <Alert>
        <AlertTitle>No active event</AlertTitle>
        <AlertDescription>Join an event to see its scoreboard.</AlertDescription>
      </Alert>
    );
  } else if (loading) {
    body = <Skeleton className="h-64 w-full" />;
  } else if (eventQuery.isError || scoreboard.isError || !scoreboard.data) {
    body = (
      <Alert variant="destructive">
        <AlertTitle>Could not load the scoreboard</AlertTitle>
        <AlertDescription>Please retry.</AlertDescription>
      </Alert>
    );
  } else {
    body = <ScoreboardContent data={scoreboard.data} bracket={bracket} onBracketChange={setBracket} />;
  }

  return (
    <>
      <PageHeader title="Scoreboard" description="Event rankings" />
      {body}
    </>
  );
}
