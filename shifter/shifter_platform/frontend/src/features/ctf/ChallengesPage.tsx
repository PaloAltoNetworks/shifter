import { useMemo, useState } from "react";
import { Link } from "react-router";

import { CheckCircle2 } from "lucide-react";

import { useCtfChallenges } from "@/api/ctf";
import type { CtfChallengeListItem } from "@/api/types";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

import { titleCase } from "./format";
import { LabelFilterRow, distinctLabels, filterByLabels } from "./label-filters";
import { ctfChallengeDetailPath } from "./routes";

const UNCATEGORIZED = "Uncategorized";
const MISSION_CATEGORY = /^Mission\s+(\d+)\b/i;
const START_HERE_CATEGORY = /^Start Here$/i;

function compareCategories(left: string, right: string): number {
  const leftStart = START_HERE_CATEGORY.test(left);
  const rightStart = START_HERE_CATEGORY.test(right);
  if (leftStart || rightStart) {
    if (leftStart && rightStart) return left.localeCompare(right);
    return leftStart ? -1 : 1;
  }
  const leftMission = MISSION_CATEGORY.exec(left);
  const rightMission = MISSION_CATEGORY.exec(right);
  if (leftMission && rightMission) {
    return Number(leftMission[1]) - Number(rightMission[1]) || left.localeCompare(right);
  }
  if (leftMission) return -1;
  if (rightMission) return 1;
  return left.localeCompare(right);
}

/** Group challenges by category, preserving each challenge's server `order`. */
function groupByCategory(challenges: CtfChallengeListItem[]): Array<[string, CtfChallengeListItem[]]> {
  const groups = new Map<string, CtfChallengeListItem[]>();
  for (const challenge of challenges) {
    const key = challenge.category || UNCATEGORIZED;
    const bucket = groups.get(key) ?? [];
    bucket.push(challenge);
    groups.set(key, bucket);
  }
  for (const bucket of groups.values()) {
    bucket.sort((a, b) => a.order - b.order || a.name.localeCompare(b.name));
  }
  return [...groups.entries()].sort(([a], [b]) => compareCategories(a, b));
}

function ChallengeCard({ challenge }: Readonly<{ challenge: CtfChallengeListItem }>) {
  return (
    <Link
      to={ctfChallengeDetailPath(challenge.id)}
      className="block rounded-lg border border-border/60 p-4 transition-colors hover:border-border hover:bg-accent/40 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="font-medium">{challenge.name}</span>
        {challenge.solved ? (
          <Badge variant="secondary" className="gap-1">
            <CheckCircle2 className="size-3" aria-hidden="true" />
            Solved
          </Badge>
        ) : null}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span>{challenge.points} pts</span>
        {challenge.difficulty ? <span>· {titleCase(challenge.difficulty)}</span> : null}
      </div>
    </Link>
  );
}

function ChallengesBody({ query }: Readonly<{ query: ReturnType<typeof useCtfChallenges> }>) {
  const [activeTag, setActiveTag] = useState<string | null>(null);
  const [activeTopic, setActiveTopic] = useState<string | null>(null);
  const challenges = useMemo(
    () => filterByLabels(query.data ?? [], activeTag, activeTopic),
    [query.data, activeTag, activeTopic],
  );
  const tagLabels = useMemo(() => distinctLabels(query.data ?? [], "tags"), [query.data]);
  const topicLabels = useMemo(() => distinctLabels(query.data ?? [], "topics"), [query.data]);
  const grouped = useMemo(() => groupByCategory(challenges), [challenges]);

  if (query.isLoading) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {[0, 1, 2, 3, 4, 5].map((row) => (
          <Skeleton key={row} className="h-20 w-full" />
        ))}
      </div>
    );
  }

  if (query.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Could not load challenges</AlertTitle>
        <AlertDescription>Please retry.</AlertDescription>
      </Alert>
    );
  }

  const filterRows = (
    <div className="flex flex-col gap-2">
      <LabelFilterRow
        axis="tags"
        labels={tagLabels}
        active={activeTag}
        onToggle={(value) => setActiveTag(activeTag === value ? null : value)}
      />
      <LabelFilterRow
        axis="topics"
        labels={topicLabels}
        active={activeTopic}
        onToggle={(value) => setActiveTopic(activeTopic === value ? null : value)}
      />
    </div>
  );

  if (grouped.length === 0) {
    return (
      <div className="space-y-4">
        {filterRows}
        <Card>
          <CardContent className="grid place-items-center px-6 py-16 text-center">
            <p className="text-sm font-medium">
              {activeTag || activeTopic ? "No challenges match this filter" : "No challenges available yet"}
            </p>
            <p className="mt-1 text-sm text-muted-foreground">
              {activeTag || activeTopic
                ? "Clear the filter to see every available challenge."
                : "Challenges appear here once the event releases them."}
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {filterRows}
      {grouped.map(([category, items]) => (
        <section key={category} aria-label={category}>
          <h2 className="mb-3 text-sm font-semibold">{titleCase(category)}</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((challenge) => (
              <ChallengeCard key={challenge.id} challenge={challenge} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

export function ChallengesPage() {
  const query = useCtfChallenges();
  const total = query.data?.length ?? 0;
  const solved = query.data?.filter((challenge) => challenge.solved).length ?? 0;

  return (
    <>
      <PageHeader
        title="Challenges"
        description={query.data ? `${solved} of ${total} solved` : "Browse available challenges"}
      />
      <ChallengesBody query={query} />
    </>
  );
}
