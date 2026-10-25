import { useParticipantModelAccess, type ParticipantModelAccess } from "@/api/model-access";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

const STATE_LABELS: Record<string, string> = {
  active: "Active",
  refresh_pending: "Refreshing",
  unavailable: "Not available",
};

/** The range-scoped detail line: unavailable notice, alias list, or empty state. */
function AccessDetail({ access }: Readonly<{ access: ParticipantModelAccess }>) {
  if (access.state === "unavailable") {
    return <p className="mt-2 text-sm text-muted-foreground">Model access is not enabled for your range.</p>;
  }
  if (access.aliases.length) {
    return (
      <ul className="mt-2 list-disc pl-5 text-sm">
        {access.aliases.map((alias) => (
          <li key={alias}>{alias}</li>
        ))}
      </ul>
    );
  }
  return <p className="mt-2 text-sm text-muted-foreground">No models are allocated to your range yet.</p>;
}

/**
 * Participant-facing model-access status for their own range (M09, #2126).
 *
 * Range-scoped and redacted: shows only the availability state and the logical
 * model aliases the participant may use — never provider, region, account or
 * source coordinates. Optional-unavailable and error states are shown, not hidden.
 */
export function ParticipantModelAccessCard() {
  const query = useParticipantModelAccess();
  if (query.isLoading) return <Skeleton className="h-20 w-full" />;
  if (query.error) {
    return (
      <Alert variant="destructive">
        <AlertDescription role="alert">Model access status is temporarily unavailable.</AlertDescription>
      </Alert>
    );
  }
  const access = query.data;
  if (!access) return null;
  return (
    <Card>
      <CardContent>
        <h2 className="text-sm font-semibold">Model access</h2>
        <div className="mt-2 flex items-center gap-2">
          <span className="text-sm text-muted-foreground">Status</span>
          <Badge variant="secondary">{STATE_LABELS[access.state] ?? access.state}</Badge>
        </div>
        <AccessDetail access={access} />
      </CardContent>
    </Card>
  );
}
