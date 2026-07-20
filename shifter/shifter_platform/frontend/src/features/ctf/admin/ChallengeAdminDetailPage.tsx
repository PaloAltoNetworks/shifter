import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { useCtfOrganizerChallenge, useDeleteCtfChallenge } from "@/api/ctfAdmin";
import type { CtfOrganizerChallengeDetail } from "@/api/types";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { formatDateTime, titleCase } from "../format";
import { MarkdownContent } from "../MarkdownContent";
import { ctfAdminChallengeEditPath, ctfAdminEventsPath } from "../routes";

function ChallengeBody({ challenge }: Readonly<{ challenge: CtfOrganizerChallengeDetail }>) {
  return (
    <div className="space-y-6">
      <Card>
        <CardContent>
          <div className="mb-4 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            {challenge.category ? <Badge variant="secondary">{titleCase(challenge.category)}</Badge> : null}
            {challenge.difficulty ? <span>{titleCase(challenge.difficulty)}</span> : null}
            <span>· {challenge.points} pts</span>
            <span>· order {challenge.order}</span>
            <span>· max attempts {challenge.max_attempts || "∞"}</span>
          </div>
          <p className="text-sm whitespace-pre-wrap">{challenge.description || "No description provided."}</p>
          <dl className="mt-5 grid gap-4 sm:grid-cols-2">
            <div>
              <dt className="text-xs text-muted-foreground">Flag format</dt>
              <dd className="mt-0.5 font-mono text-sm">{challenge.flag_format || "—"}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Release time</dt>
              <dd className="mt-0.5 text-sm">{formatDateTime(challenge.release_time)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Visibility</dt>
              <dd className="mt-0.5 text-sm">{titleCase(challenge.visibility)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Target</dt>
              <dd className="mt-0.5 text-sm">{formatTarget(challenge)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Participant rating</dt>
              <dd className="mt-0.5 text-sm">{formatRatingSummary(challenge.rating)}</dd>
            </div>
          </dl>
          {challenge.tags.length > 0 || challenge.topics.length > 0 ? (
            <div className="mt-4 flex flex-wrap gap-1.5">
              {challenge.tags.map((tag) => (
                <Badge key={`tag-${tag}`} variant="outline">
                  {tag}
                </Badge>
              ))}
              {challenge.topics.map((topic) => (
                <Badge key={`topic-${topic}`} variant="outline">
                  {topic}
                </Badge>
              ))}
            </div>
          ) : null}
        </CardContent>
      </Card>

      {challenge.hints.length > 0 ? (
        <Card>
          <CardContent>
            <h2 className="mb-3 text-sm font-semibold">Hints</h2>
            <ul className="divide-y divide-border/60">
              {challenge.hints.map((hint) => (
                <li key={hint.id} className="py-2 text-sm">
                  <span className="block whitespace-pre-wrap">{hint.text}</span>
                  <span className="text-xs text-muted-foreground">−{hint.penalty} pts</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}

      {challenge.solution ? (
        <Card>
          <CardContent>
            <h2 className="mb-2 text-sm font-semibold">Solution (organizer-only)</h2>
            <MarkdownContent text={challenge.solution} />
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}


function formatTarget(challenge: CtfOrganizerChallengeDetail): string {
  if (!challenge.target_instance_name) return "—";
  const port = challenge.target_port == null ? "" : `:${challenge.target_port}`;
  return `${challenge.target_instance_name}${port}`;
}

function formatRatingSummary(rating: CtfOrganizerChallengeDetail["rating"]): string {
  if (!rating) return "Ratings disabled for this event";
  if (rating.count === 0) return "No ratings yet";
  const plural = rating.count === 1 ? "" : "s";
  return `${rating.average} average from ${rating.count} rating${plural}`;
}

export function ChallengeAdminDetailPage() {
  const params = useParams();
  const challengeId = params.challengeId ?? "";
  const query = useCtfOrganizerChallenge(challengeId);
  const navigate = useNavigate();
  const del = useDeleteCtfChallenge();
  const [confirming, setConfirming] = useState(false);

  if (query.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-9 w-72" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  if (query.isError || !query.data) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Challenge unavailable</AlertTitle>
        <AlertDescription>
          This challenge was not found or has been removed.{" "}
          <Link className="underline" to={ctfAdminEventsPath()}>
            Back to events
          </Link>
          .
        </AlertDescription>
      </Alert>
    );
  }

  const challenge = query.data;

  return (
    <>
      <nav className="mb-3 text-sm text-muted-foreground" aria-label="Breadcrumb">
        <Link className="hover:text-foreground" to={ctfAdminEventsPath()}>
          Events
        </Link>
        <span className="px-1.5">/</span>
        <span className="text-foreground">{challenge.name}</span>
      </nav>

      <PageHeader
        title={challenge.name}
        description="Challenge overview"
        actions={
          <div className="flex items-center gap-2">
            <Link
              to={ctfAdminChallengeEditPath(challenge.id)}
              className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
            >
              Edit
            </Link>
            <Button variant="destructive" size="sm" onClick={() => setConfirming(true)}>
              Delete
            </Button>
          </div>
        }
      />

      <ChallengeBody challenge={challenge} />

      <ConfirmDialog
        open={confirming}
        title="Delete challenge?"
        confirmLabel="Delete"
        destructive
        pending={del.isPending}
        error={del.error}
        onOpenChange={(open) => {
          if (!open) {
            del.reset();
            setConfirming(false);
          }
        }}
        onConfirm={() =>
          del.mutate(challenge.id, {
            onSuccess: () => {
              setConfirming(false);
              navigate(ctfAdminEventsPath());
            },
          })
        }
      >
        This permanently removes the challenge and its submissions. This cannot be undone.
      </ConfirmDialog>
    </>
  );
}
