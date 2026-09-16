import { ArrowRight } from "lucide-react";

import { useBootstrapContext } from "@/app/bootstrap-context";
import { useMode } from "@/app/mode";
import { rangeStatusMapping } from "@/app/state-map";
import { useDashboardSummary } from "@/api/dashboard";
import { isApiError } from "@/api/errors";
import { PageHeader } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

function SummaryCard({
  title,
  children,
}: Readonly<{ title: string; children: React.ReactNode }>) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{title}</CardDescription>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function OperatorDashboard() {
  const query = useDashboardSummary();

  if (query.isLoading) {
    return (
      <div className="grid gap-4 sm:grid-cols-2">
        {["range", "event"].map((key) => (
          <Card key={key}>
            <CardHeader className="pb-2">
              <Skeleton className="h-4 w-24" />
            </CardHeader>
            <CardContent>
              <Skeleton className="h-6 w-32" />
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  if (query.isError || !query.data) {
    const requestId = isApiError(query.error) ? query.error.requestId : undefined;
    return (
      <Alert variant="destructive">
        <AlertTitle>Unable to load the dashboard</AlertTitle>
        <AlertDescription>
          Please retry. If the problem persists, contact an administrator{requestId ? ` (request ${requestId})` : ""}.
        </AlertDescription>
      </Alert>
    );
  }

  const { active_range, active_event } = query.data;
  const range = rangeStatusMapping(active_range.present ? active_range.status : null);

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <SummaryCard title="Active range">
        <StatusChip intent={range.intent} label={range.label} />
      </SummaryCard>
      <SummaryCard title="Active event">
        <p className="text-sm font-medium">
          {active_event.present ? (active_event.name ?? "Active event") : "No active event"}
        </p>
      </SummaryCard>
    </div>
  );
}

function OperatorQuickLinks() {
  return (
    <div className="mt-6 flex flex-wrap gap-2">
      <a href="/mission-control/" className={cn(buttonVariants({ variant: "outline", size: "sm" }), "gap-1.5")}>
        Ranges <ArrowRight className="size-4" />
      </a>
    </div>
  );
}

function ParticipantLanding() {
  const links: ReadonlyArray<{ label: string; href: string }> = [
    { label: "Event Home", href: "/ctf/" },
    { label: "Challenges", href: "/ctf/challenges/" },
    { label: "Scoreboard", href: "/ctf/scoreboard/" },
  ];
  return (
    <Card>
      <CardHeader>
        <CardTitle>Your event</CardTitle>
        <CardDescription>Jump back into the challenge experience.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-2">
        {links.map((link) => (
          <a
            key={link.href}
            href={link.href}
            className={cn(buttonVariants({ variant: "outline", size: "sm" }), "gap-1.5")}
          >
            {link.label} <ArrowRight className="size-4" />
          </a>
        ))}
      </CardContent>
    </Card>
  );
}

export function HomePage() {
  const bootstrap = useBootstrapContext();
  const { mode } = useMode();
  const isParticipant = mode === "participant";

  return (
    <>
      <PageHeader
        title={`Welcome, ${bootstrap.principal.display_name}`}
        description={isParticipant ? "Your participant home." : "Your operational overview."}
      />
      {isParticipant ? (
        <ParticipantLanding />
      ) : (
        <>
          <OperatorDashboard />
          <OperatorQuickLinks />
        </>
      )}
    </>
  );
}
