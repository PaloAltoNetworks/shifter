import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, Download, Loader2 } from "lucide-react";

import { fetchCtfFileDownload, useCtfChallenge, useRateChallenge, useSubmitFlag, useUseHint } from "@/api/ctf";
import { ApiError } from "@/api/errors";
import type { CtfChallengeDetail, CtfChallengeFile, CtfHint } from "@/api/types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { titleCase } from "./format";
import { MarkdownContent } from "./MarkdownContent";
import { ctfChallengeDetailPath, ctfChallengesPath } from "./routes";

function ChallengeMeta({ challenge }: Readonly<{ challenge: CtfChallengeDetail }>) {
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
      {challenge.category ? <Badge variant="secondary">{titleCase(challenge.category)}</Badge> : null}
      {challenge.difficulty ? <span>{titleCase(challenge.difficulty)}</span> : null}
      <span>· {challenge.points} pts</span>
      {challenge.attempts_remaining === null ? null : <span>· {challenge.attempts_remaining} attempts left</span>}
      {challenge.solved ? (
        <Badge variant="secondary" className="gap-1">
          <CheckCircle2 className="size-3" aria-hidden="true" />
          Solved
        </Badge>
      ) : null}
    </div>
  );
}

function PrereqAlert({ challenge }: Readonly<{ challenge: CtfChallengeDetail }>) {
  if (challenge.prerequisites_met) return null;
  return (
    <Alert className="mb-4">
      <AlertTitle>Locked by prerequisites</AlertTitle>
      <AlertDescription>
        Solve these challenges first:{" "}
        {challenge.unmet_prerequisites.map((required, index) => (
          <span key={required.id}>
            {index > 0 ? ", " : ""}
            <Link className="underline" to={ctfChallengeDetailPath(required.id)}>
              {required.name}
            </Link>
          </span>
        ))}
      </AlertDescription>
    </Alert>
  );
}

function ConnectionInfoCard({ challenge }: Readonly<{ challenge: CtfChallengeDetail }>) {
  const info = challenge.connection_info;
  if (!info) return null;
  return (
    <Card className="mt-6">
      <CardContent>
        <h2 className="mb-3 text-sm font-semibold">Connection</h2>
        <dl className="grid gap-2 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-xs text-muted-foreground">Host</dt>
            <dd className="font-mono">{info.host}</dd>
          </div>
          {info.port === null ? null : (
            <div>
              <dt className="text-xs text-muted-foreground">Port</dt>
              <dd className="font-mono">{info.port}</dd>
            </div>
          )}
          <div>
            <dt className="text-xs text-muted-foreground">Instance</dt>
            <dd>{info.instance_name}</dd>
          </div>
          {info.os_type ? (
            <div>
              <dt className="text-xs text-muted-foreground">OS</dt>
              <dd>{titleCase(info.os_type)}</dd>
            </div>
          ) : null}
        </dl>
      </CardContent>
    </Card>
  );
}

function AttachmentRow({ file }: Readonly<{ file: CtfChallengeFile }>) {
  const download = useMutation({
    mutationFn: () => fetchCtfFileDownload(file.id),
    onSuccess: (result) => globalThis.open(result.url, "_blank", "noopener,noreferrer"),
  });
  return (
    <li className="flex items-center justify-between gap-3 py-2">
      <span className="min-w-0">
        <span className="block truncate text-sm font-medium">{file.display_name || file.filename}</span>
        <span className="text-xs text-muted-foreground">{file.filename}</span>
      </span>
      <Button variant="outline" size="sm" onClick={() => download.mutate()} disabled={download.isPending}>
        {download.isPending ? <Loader2 className="size-4 animate-spin" /> : <Download className="size-4" />}
        Download
      </Button>
    </li>
  );
}

function AttachmentsCard({ challenge }: Readonly<{ challenge: CtfChallengeDetail }>) {
  if (challenge.files.length === 0) return null;
  return (
    <Card className="mt-6">
      <CardContent>
        <h2 className="mb-1 text-sm font-semibold">Attachments</h2>
        <ul className="divide-y divide-border/60">
          {challenge.files.map((file) => (
            <AttachmentRow key={file.id} file={file} />
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function HintRow({ hint }: Readonly<{ hint: CtfHint }>) {
  return (
    <li className="rounded-md border border-border/60 p-3">
      <div className="flex items-center justify-between gap-2 text-sm">
        <span className="font-medium">Hint {hint.order + 1}</span>
        <span className="text-xs text-muted-foreground">−{hint.penalty} pts</span>
      </div>
      {hint.unlocked ? <p className="mt-2 text-sm whitespace-pre-wrap">{hint.text}</p> : null}
    </li>
  );
}

function HintsSection({ challenge }: Readonly<{ challenge: CtfChallengeDetail }>) {
  const unlock = useUseHint(challenge.id);
  const [confirming, setConfirming] = useState(false);

  if (challenge.hints.length === 0) return null;

  return (
    <Card className="mt-6">
      <CardContent>
        <div className="mb-3 flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">Hints</h2>
          {challenge.total_hint_penalty > 0 ? (
            <span className="text-xs text-muted-foreground">−{challenge.total_hint_penalty} pts used</span>
          ) : null}
        </div>
        <ul className="flex flex-col gap-2">
          {challenge.hints.map((hint) => (
            <HintRow key={hint.id} hint={hint} />
          ))}
        </ul>
        {challenge.next_hint_id ? (
          <Button
            variant="outline"
            size="sm"
            className="mt-4"
            onClick={() => setConfirming(true)}
            disabled={unlock.isPending}
          >
            Unlock next hint (−{challenge.next_hint_cost} pts)
          </Button>
        ) : null}
      </CardContent>

      <ConfirmDialog
        open={confirming}
        title="Unlock this hint?"
        confirmLabel="Unlock"
        pending={unlock.isPending}
        error={unlock.error}
        onOpenChange={(open) => {
          if (!open) {
            unlock.reset();
            setConfirming(false);
          }
        }}
        onConfirm={() =>
          unlock.mutate(challenge.next_hint_id ?? undefined, {
            onSuccess: () => setConfirming(false),
          })
        }
      >
        Unlocking costs {challenge.next_hint_cost} points; your score for this challenge would drop to{" "}
        {challenge.points_after_next_hint} points if solved.
      </ConfirmDialog>
    </Card>
  );
}

function submissionFeedback(submit: ReturnType<typeof useSubmitFlag>) {
  if (submit.data) {
    return (
      <Alert variant={submit.data.correct ? "default" : "destructive"} className="mt-3">
        <AlertTitle>{submit.data.correct ? "Correct!" : "Incorrect flag"}</AlertTitle>
        <AlertDescription>
          {submit.data.message}
          {submit.data.correct ? ` (+${submit.data.points_awarded} pts)` : null}
        </AlertDescription>
      </Alert>
    );
  }
  if (submit.error instanceof ApiError) {
    const throttled = submit.error.status === 429;
    return (
      <Alert variant="destructive" className="mt-3">
        <AlertTitle>{throttled ? "Too many attempts" : "Could not submit"}</AlertTitle>
        <AlertDescription>
          {throttled ? "Rate limit exceeded. Please wait a moment before trying again." : submit.error.message}
        </AlertDescription>
      </Alert>
    );
  }
  return null;
}


const RATING_VALUES = [1, 2, 3, 4, 5] as const;

function RatingCard({ challenge }: Readonly<{ challenge: CtfChallengeDetail }>) {
  const rate = useRateChallenge(challenge.id);
  const rating = challenge.rating;
  // The service only accepts ratings from participants who solved the
  // challenge, so the card renders after a solve (and never when disabled).
  if (!rating || !challenge.solved) return null;
  return (
    <Card className="mt-6">
      <CardContent>
        <h2 className="text-sm font-semibold">Rate this challenge</h2>
        <fieldset className="mt-2 flex items-center gap-1.5 border-0 p-0">
          <legend className="sr-only">Rate this challenge from 1 to 5</legend>
          {RATING_VALUES.map((value) => (
            <Button
              key={value}
              type="button"
              size="sm"
              variant={rating.own_rating === value ? "default" : "outline"}
              aria-pressed={rating.own_rating === value}
              disabled={rate.isPending}
              onClick={() => rate.mutate(value)}
            >
              {value}
            </Button>
          ))}
          {rating.public && rating.count > 0 ? (
            <span className="ml-2 text-xs text-muted-foreground">
              Average {rating.average ?? "—"} from {rating.count} rating{rating.count === 1 ? "" : "s"}
            </span>
          ) : null}
        </fieldset>
        {rate.isError ? <p className="mt-2 text-xs text-destructive">Could not save your rating. Try again.</p> : null}
      </CardContent>
    </Card>
  );
}

function FlagSubmission({ challenge }: Readonly<{ challenge: CtfChallengeDetail }>) {
  const submit = useSubmitFlag(challenge.id);
  const [flag, setFlag] = useState("");

  if (challenge.solved) {
    return (
      <Alert className="mt-6">
        <AlertTitle>Solved</AlertTitle>
        <AlertDescription>You have already captured this flag.</AlertDescription>
      </Alert>
    );
  }

  if (challenge.locked) {
    return (
      <Alert className="mt-6">
        <AlertTitle>Locked</AlertTitle>
        <AlertDescription>
          This challenge is visible but not yet open for submissions.
        </AlertDescription>
      </Alert>
    );
  }

  const disabled = submit.isPending || !flag.trim();

  return (
    <Card className="mt-6">
      <CardContent>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!flag.trim()) return;
            submit.mutate(flag.trim());
          }}
        >
          <Label htmlFor="ctf-flag">Submit flag</Label>
          <div className="mt-2 flex gap-2">
            <Input
              id="ctf-flag"
              value={flag}
              onChange={(event) => setFlag(event.target.value)}
              placeholder="FLAG{...}"
              autoComplete="off"
            />
            <Button type="submit" disabled={disabled}>
              {submit.isPending ? <Loader2 className="size-4 animate-spin" /> : null}
              Submit
            </Button>
          </div>
        </form>
        {submissionFeedback(submit)}
      </CardContent>
    </Card>
  );
}

export function ChallengeDetailPage() {
  const params = useParams();
  const challengeId = params.id ?? "";
  const query = useCtfChallenge(challengeId);

  if (query.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-9 w-72" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (query.isError || !query.data) {
    const forbidden = query.error instanceof ApiError && query.error.status === 403;
    return (
      <Alert variant="destructive">
        <AlertTitle>{forbidden ? "Challenge locked" : "Challenge unavailable"}</AlertTitle>
        <AlertDescription>
          {forbidden
            ? "This challenge is not available to you yet."
            : "This challenge was not found or has been removed."}{" "}
          <Link className="underline" to={ctfChallengesPath()}>
            Back to challenges
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
        <Link className="hover:text-foreground" to={ctfChallengesPath()}>
          Challenges
        </Link>
        <span className="px-1.5">/</span>
        <span className="text-foreground">{challenge.name}</span>
      </nav>

      <h1 className="text-2xl font-semibold tracking-tight">{challenge.name}</h1>
      <ChallengeMeta challenge={challenge} />

      <div className="mt-6">
        <PrereqAlert challenge={challenge} />
        <Card>
          <CardContent>
            {challenge.description ? (
              <MarkdownContent text={challenge.description} />
            ) : (
              <p className="text-sm">No description provided.</p>
            )}
          </CardContent>
        </Card>
      </div>

      <ConnectionInfoCard challenge={challenge} />
      <AttachmentsCard challenge={challenge} />
      <HintsSection challenge={challenge} />
      <FlagSubmission challenge={challenge} />
      <RatingCard challenge={challenge} />

      {challenge.show_solution && challenge.solution ? (
        <Card className="mt-6">
          <CardContent>
            <h2 className="mb-2 text-sm font-semibold">Solution</h2>
            <MarkdownContent text={challenge.solution} />
          </CardContent>
        </Card>
      ) : null}
    </>
  );
}
