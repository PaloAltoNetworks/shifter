import { Link, useParams } from "react-router";

import { useScenario, useUpdateScenarioMetadata } from "@/api/scenarios";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import { EnabledBadge, SourceBadge, StaffOnlyBadge } from "./badges";
import { RealizabilityPanel } from "./RealizabilityPanel";
import { scenarioListPath } from "./routes";

export function ScenarioDetailPage() {
  const scenarioId = useParams<{ scenarioId: string }>().scenarioId ?? "";
  const query = useScenario(scenarioId, Boolean(scenarioId));
  const metadata = useUpdateScenarioMetadata(scenarioId);

  if (query.isLoading) return <Skeleton className="h-64 w-full" />;
  if (query.isError || !query.data) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Could not load scenario</AlertTitle>
        <AlertDescription>The RAES package source is unavailable.</AlertDescription>
      </Alert>
    );
  }

  const scenario = query.data;
  return (
    <>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link className={cn(buttonVariants({ variant: "link", size: "sm" }), "-ml-3 mb-1")} to={scenarioListPath()}>
            Back to scenarios
          </Link>
          <h1 className="text-2xl font-semibold tracking-tight">{scenario.name}</h1>
          <p className="font-mono text-sm text-muted-foreground">{scenario.id}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => metadata.mutate({ enabled: !scenario.enabled })}
            disabled={metadata.isPending}
          >
            {scenario.enabled ? "Disable" : "Enable"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => metadata.mutate({ staff_only: !scenario.staff_only })}
            disabled={metadata.isPending}
          >
            {scenario.staff_only ? "Make available to all" : "Make staff-only"}
          </Button>
        </div>
      </div>

      {metadata.isError ? (
        <Alert variant="destructive" className="mb-4">
          <AlertTitle>Could not update availability</AlertTitle>
          <AlertDescription>{metadata.error.message}</AlertDescription>
        </Alert>
      ) : null}

      <Card>
        <CardContent>
          <dl className="grid gap-3 text-sm sm:grid-cols-2">
            <div><dt className="text-muted-foreground">Source</dt><dd><SourceBadge source={scenario.source} /></dd></div>
            <div><dt className="text-muted-foreground">Type</dt><dd>{scenario.scenario_type}</dd></div>
            <div><dt className="text-muted-foreground">Availability</dt><dd className="flex gap-2"><EnabledBadge enabled={scenario.enabled} />{scenario.staff_only ? <StaffOnlyBadge /> : null}</dd></div>
            <div><dt className="text-muted-foreground">Launchable</dt><dd>{scenario.launchable ? "Yes" : "No"}</dd></div>
            <div><dt className="text-muted-foreground">Package</dt><dd>{scenario.raes?.package_ref ?? "—"}</dd></div>
            <div><dt className="text-muted-foreground">Version</dt><dd>{scenario.raes?.package_version ?? "—"}</dd></div>
            <div><dt className="text-muted-foreground">Conformance</dt><dd>{scenario.raes?.conformance_status ?? "—"}</dd></div>
            <div><dt className="text-muted-foreground">Digest</dt><dd className="break-all font-mono text-xs">{scenario.raes?.package_digest ?? "—"}</dd></div>
          </dl>
        </CardContent>
      </Card>

      <div className="mt-6">
        <RealizabilityPanel scenarioId={scenario.id} enabled={scenario.source === "raes"} />
      </div>
    </>
  );
}
