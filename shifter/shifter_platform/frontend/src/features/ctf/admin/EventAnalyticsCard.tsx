import { useCtfEventAnalytics } from "@/api/ctfAdmin";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

function Bars({
  items,
  ariaLabel,
}: Readonly<{ items: Array<{ label: string; value: number }>; ariaLabel: string }>) {
  const peak = Math.max(1, ...items.map((item) => item.value));
  return (
    <div className="flex items-end gap-1" role="img" aria-label={ariaLabel}>
      {items.map((item) => (
        <div key={item.label} className="flex flex-col items-center gap-1" title={`${item.label}: ${item.value}`}>
          <div
            className="w-6 rounded-t bg-primary/70"
            style={{ height: `${Math.max(4, (item.value / peak) * 80)}px` }}
          />
          <span className="text-[10px] text-muted-foreground">{item.label}</span>
        </div>
      ))}
    </div>
  );
}

/** Event performance insights (CTF-1302): distribution, timeline, difficulty, engagement. */
export function EventAnalyticsCard({ eventId }: Readonly<{ eventId: string }>) {
  const query = useCtfEventAnalytics(eventId);

  if (query.isLoading) return <Skeleton className="h-40 w-full" />;
  const analytics = query.data;
  if (!analytics) return null;
  const { engagement } = analytics;

  return (
    <div className="space-y-4">
      <Card>
        <CardContent>
          <h2 className="text-sm font-semibold">Engagement</h2>
          <dl className="mt-2 grid gap-4 sm:grid-cols-5 text-sm">
            <div>
              <dt className="text-xs text-muted-foreground">Registered</dt>
              <dd className="font-semibold">{engagement.registered}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Active</dt>
              <dd className="font-semibold">{engagement.active}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Submitted</dt>
              <dd className="font-semibold">{engagement.with_submissions}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Avg challenges tried</dt>
              <dd className="font-semibold">{engagement.avg_challenges_attempted}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Hints used</dt>
              <dd className="font-semibold">{engagement.hints_used}</dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      {analytics.score_distribution.length ? (
        <Card>
          <CardContent>
            <h2 className="text-sm font-semibold">Score distribution</h2>
            <div className="mt-3 overflow-x-auto">
              <Bars
                ariaLabel="Score distribution histogram"
                items={analytics.score_distribution.map((bucket) => ({
                  label: `${bucket.from}`,
                  value: bucket.count,
                }))}
              />
            </div>
          </CardContent>
        </Card>
      ) : null}

      {analytics.solve_timeline.length ? (
        <Card>
          <CardContent>
            <h2 className="text-sm font-semibold">Solves over time</h2>
            <div className="mt-3 overflow-x-auto">
              <Bars
                ariaLabel="Solves per hour"
                items={analytics.solve_timeline.map((point) => ({
                  label: point.hour ? new Date(point.hour).getHours().toString().padStart(2, "0") : "?",
                  value: point.solves,
                }))}
              />
            </div>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardContent>
          <h2 className="text-sm font-semibold">Challenge difficulty</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Solve rate against point value; a high-value challenge everyone solves (or a low-value one nobody
            does) is miscalibrated.
          </p>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Challenge</TableHead>
                <TableHead>Points</TableHead>
                <TableHead>Solves</TableHead>
                <TableHead>Attempts</TableHead>
                <TableHead>Solve rate</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {analytics.challenges.map((challenge) => (
                <TableRow key={challenge.name}>
                  <TableCell>{challenge.name}</TableCell>
                  <TableCell>{challenge.points}</TableCell>
                  <TableCell>{challenge.solves}</TableCell>
                  <TableCell>{challenge.attempts}</TableCell>
                  <TableCell>{Math.round(challenge.solve_rate * 100)}%</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
