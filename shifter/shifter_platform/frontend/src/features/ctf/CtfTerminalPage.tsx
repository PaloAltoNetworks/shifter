import { Link } from "react-router";

import { useCtfRangeStatus } from "@/api/ctf";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { TerminalPage } from "@/features/mission-control/TerminalPage";
import { cn } from "@/lib/utils";

import { ctfRangePath } from "./routes";

/** CTF-owned terminal landing page that keeps participants inside the CTF shell. */
export function CtfTerminalPage() {
  const query = useCtfRangeStatus();

  if (query.isLoading) {
    return (
      <>
        <PageHeader title="Terminal" description="Connecting to your range." />
        <Skeleton className="h-[34rem] w-full" />
      </>
    );
  }

  if (query.isError || !query.data) {
    return (
      <>
        <PageHeader title="Terminal" />
        <Alert variant="destructive">
          <AlertTitle>Could not load terminal access</AlertTitle>
          <AlertDescription>Return to Range and retry.</AlertDescription>
        </Alert>
      </>
    );
  }

  const target = query.data.status === "ready" ? query.data.target_instances[0] : undefined;
  if (!target?.uuid) {
    return (
      <>
        <PageHeader title="Terminal" description="SSH session on your participant range." />
        <Alert>
          <AlertTitle>Terminal is not ready</AlertTitle>
          <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
            <span>Terminal access becomes available when your range is ready.</span>
            <Link to={ctfRangePath()} className={cn(buttonVariants({ variant: "outline", size: "sm" }))}>
              View range
            </Link>
          </AlertDescription>
        </Alert>
      </>
    );
  }

  return <TerminalPage instanceUuid={target.uuid} tmuxWheelScrolling />;
}
