import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { Loader2 } from "lucide-react";

import { useCreateCtfChallenge, useCtfOrganizerChallenge, useUpdateCtfChallenge } from "@/api/ctfAdmin";
import { ApiError } from "@/api/errors";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

import { ctfAdminChallengePath, ctfAdminEventChallengesPath, ctfAdminEventsPath } from "../routes";
import { EMPTY, type FormState, fromChallenge, toPayload } from "./challenge-form-state";
import { BasicFields, FilesSection, FlagsSection, HintsSection, PrerequisitesSection } from "./ChallengeFormSections";

/** Render the edit-mode loading / not-found states, or null when the form itself should render. */
function renderEditLoadState(
  mode: "create" | "edit",
  existing: ReturnType<typeof useCtfOrganizerChallenge>,
): React.ReactNode {
  if (mode !== "edit") return null;
  if (existing.isLoading) {
    return (
      <div className="grid place-items-center py-24 text-muted-foreground">
        <Loader2 className="size-6 animate-spin" aria-label="Loading challenge" />
      </div>
    );
  }
  if (existing.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Challenge not found</AlertTitle>
        <AlertDescription>
          This challenge may have been deleted.{" "}
          <Link className="underline" to={ctfAdminEventsPath()}>
            Back to events
          </Link>
          .
        </AlertDescription>
      </Alert>
    );
  }
  return null;
}

function submitChallengeForm(
  event: React.FormEvent,
  opts: Readonly<{
    state: FormState;
    mode: "create" | "edit";
    challengeId: string;
    create: ReturnType<typeof useCreateCtfChallenge>;
    update: ReturnType<typeof useUpdateCtfChallenge>;
    navigate: ReturnType<typeof useNavigate>;
  }>,
) {
  event.preventDefault();
  const payload = toPayload(opts.state, opts.mode);
  if (opts.mode === "create") {
    opts.create.mutate(payload, { onSuccess: (result) => opts.navigate(ctfAdminChallengePath(result.id)) });
  } else if (opts.challengeId) {
    opts.update.mutate(payload, { onSuccess: () => opts.navigate(ctfAdminChallengePath(opts.challengeId)) });
  }
}

export function ChallengeFormPage({ mode }: Readonly<{ mode: "create" | "edit" }>) {
  const navigate = useNavigate();
  const params = useParams();
  const eventId = params.eventId ?? "";
  const challengeId = mode === "edit" ? (params.challengeId ?? "") : "";

  const existing = useCtfOrganizerChallenge(challengeId, mode === "edit");
  const create = useCreateCtfChallenge(eventId);
  const update = useUpdateCtfChallenge(challengeId);
  const mutation = mode === "create" ? create : update;

  const [state, setState] = useState<FormState>(EMPTY);
  const [initialized, setInitialized] = useState(mode === "create");
  const formRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    if (mode === "edit" && existing.data && !initialized) {
      setState(fromChallenge(existing.data));
      setInitialized(true);
    }
  }, [mode, existing.data, initialized]);

  const fieldErrors = useMemo(
    () => (mutation.error instanceof ApiError ? mutation.error.fieldErrors() : {}),
    [mutation.error],
  );

  useEffect(() => {
    if (Object.keys(fieldErrors).length > 0) {
      formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
    }
  }, [fieldErrors]);

  const nonFieldError =
    mutation.error instanceof ApiError && Object.keys(fieldErrors).length === 0 ? mutation.error.message : null;

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setState((prev) => ({ ...prev, [key]: value }));
  }

  function firstError(field: string): string | undefined {
    return fieldErrors[field]?.[0];
  }

  function onSubmit(event: React.FormEvent) {
    submitChallengeForm(event, { state, mode, challengeId, create, update, navigate });
  }

  const editLoadState = renderEditLoadState(mode, existing);
  if (editLoadState) return <>{editLoadState}</>;

  const cancelHref =
    mode === "edit" && challengeId ? ctfAdminChallengePath(challengeId) : ctfAdminEventChallengesPath(eventId);

  return (
    <div className="mx-auto max-w-3xl">
      <nav className="mb-3 text-sm text-muted-foreground" aria-label="Breadcrumb">
        <Link className="hover:text-foreground" to={ctfAdminEventsPath()}>
          Events
        </Link>
        <span className="px-1.5">/</span>
        <span className="text-foreground">{mode === "create" ? "New challenge" : "Edit challenge"}</span>
      </nav>
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">
        {mode === "create" ? "New challenge" : `Edit ${existing.data?.name ?? "challenge"}`}
      </h1>

      {nonFieldError ? (
        <Alert variant="destructive" className="mb-4">
          <AlertTitle>Could not save</AlertTitle>
          <AlertDescription>{nonFieldError}</AlertDescription>
        </Alert>
      ) : null}

      <form ref={formRef} onSubmit={onSubmit} noValidate>
        <BasicFields state={state} set={set} firstError={firstError} mode={mode} />
        <div className="mt-4 flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={() => navigate(cancelHref)}>
            Cancel
          </Button>
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? <Loader2 className="size-4 animate-spin" /> : null}
            {mode === "create" ? "Create challenge" : "Save changes"}
          </Button>
        </div>
      </form>

      {mode === "edit" && challengeId ? (
        <div className="mt-8 space-y-6">
          <FlagsSection challengeId={challengeId} />
          <HintsSection challengeId={challengeId} />
          <FilesSection challengeId={challengeId} />
          <PrerequisitesSection challengeId={challengeId} />
        </div>
      ) : (
        <p className="mt-6 text-sm text-muted-foreground">
          Save the challenge to manage its flags, hints, files, and prerequisites.
        </p>
      )}
    </div>
  );
}
