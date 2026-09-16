import { Link } from "react-router";

import { useCtfBriefing } from "@/api/ctf";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

import { MarkdownContent } from "./MarkdownContent";
import { ctfHelpPath } from "./routes";

/**
 * The event's participant briefing (#1854): organizer-authored guidance for
 * this specific event, rendered as sanitized Markdown. It is a surface separate
 * from generic Help — when the organizer has published nothing, participants
 * simply keep using Help, and this page shows a pointer there rather than an
 * error. A failed fetch (as opposed to a proven absence) shows a retry state so
 * a transient error never masquerades as "no briefing".
 */
export function BriefingPage() {
  const query = useCtfBriefing();

  if (query.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-9 w-64" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (query.isError) {
    return (
      <>
        <PageHeader title="Briefing" />
        <Alert variant="destructive">
          <AlertTitle>Could not load the briefing</AlertTitle>
          <AlertDescription>Please retry.</AlertDescription>
        </Alert>
      </>
    );
  }

  const briefing = query.data;
  if (!briefing) {
    return (
      <>
        <PageHeader title="Briefing" description="Event briefing" />
        <Alert>
          <AlertTitle>No briefing for this event</AlertTitle>
          <AlertDescription>
            The organizer has not published a briefing for this event. See the{" "}
            <Link className="underline" to={ctfHelpPath()}>
              Help
            </Link>{" "}
            page for general guidance.
          </AlertDescription>
        </Alert>
      </>
    );
  }

  return (
    <>
      <PageHeader title={briefing.title} description="Event briefing" />
      <Card>
        <CardContent>
          <MarkdownContent text={briefing.body} disallowedElements={["img"]} />
        </CardContent>
      </Card>
    </>
  );
}
