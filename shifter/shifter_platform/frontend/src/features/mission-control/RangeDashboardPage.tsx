import { Link } from "react-router-dom";

import { ApiError } from "@/api/errors";
import { useCurrentRange } from "@/api/mission-control";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import { ActiveRangePanel } from "./ActiveRangePanel";
import { missionControlLaunchPath } from "./routes";

function EmptyRangeState() {
  return (
    <Card className="grid place-items-center px-6 py-16 text-center">
      <p className="text-sm font-medium">No active range</p>
      <p className="mt-1 text-sm text-muted-foreground">Launch a range to get started.</p>
      <Link to={missionControlLaunchPath()} className={cn(buttonVariants({ size: "sm" }), "mt-4")}>
        Launch a range
      </Link>
    </Card>
  );
}

export function RangeDashboardPage() {
  const query = useCurrentRange();

  if (query.isLoading) {
    return (
      <>
        <PageHeader title="Ranges" description="Launch and monitor your range" />
        <div className="space-y-3">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-40 w-full" />
        </div>
      </>
    );
  }

  if (query.isError) {
    const message = query.error instanceof ApiError ? query.error.message : "Please retry.";
    return (
      <>
        <PageHeader title="Ranges" description="Launch and monitor your range" />
        <Alert variant="destructive">
          <AlertTitle>Could not load your range</AlertTitle>
          <AlertDescription>{message}</AlertDescription>
        </Alert>
      </>
    );
  }

  const data = query.data;
  if (!data?.has_range || !data.range) {
    return (
      <>
        <PageHeader title="Ranges" description="Launch and monitor your range" />
        <EmptyRangeState />
      </>
    );
  }

  return (
    <ActiveRangePanel
      range={data.range}
      lifecycle={data.lifecycle}
      vpnProfileAvailable={data.vpn_profile_available}
      isFetching={query.isFetching}
      title="Ranges"
      description="Your current range"
    />
  );
}
