import { useEventModelAssessment } from "@/api/model-access";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Organizer model-access capacity assessment for an event (M09, #2126).
 *
 * Shows only the bounded planning summary — outcome, whether it blocks, the
 * partition and reason codes. Raw quotas, usage and account identifiers stay
 * operator-only. An unavailable assessment is shown as such, never as a positive
 * decision.
 */
export function EventModelAccessCard({ eventId }: Readonly<{ eventId: string }>) {
  const query = useEventModelAssessment(eventId);
  if (query.isLoading) return <Skeleton className="h-24 w-full" />;
  const assessment = query.data;
  if (!assessment) return null;
  return (
    <Card>
      <CardContent>
        <h2 className="text-sm font-semibold">Model-access capacity</h2>
        {assessment.available ? (
          <dl className="mt-2 grid gap-4 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-muted-foreground">Outcome</dt>
              <dd>{assessment.outcome}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Blocking</dt>
              <dd>{assessment.blocking ? "Yes" : "No"}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Reasons</dt>
              <dd>{assessment.reason_codes.length ? assessment.reason_codes.join(", ") : "—"}</dd>
            </div>
          </dl>
        ) : (
          <p className="mt-2 text-sm text-muted-foreground">
            No model-access capacity assessment is available for this event.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
