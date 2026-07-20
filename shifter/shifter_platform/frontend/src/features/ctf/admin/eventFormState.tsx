import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Loader2 } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

import { useCreateCtfEvent, useCtfEvent, useCtfScenarios, useUpdateCtfEvent } from "@/api/ctfAdmin";
import { ApiError } from "@/api/errors";
import type { CtfEventDetail, CtfEventWrite } from "@/api/types";

import { fromDateTimeLocalValue, toDateTimeLocalValue } from "../format";
import { ctfAdminEventPath, ctfAdminEventsPath } from "../routes";

export const NO_SCENARIO = "__none__";

interface FormState {
  name: string;
  description: string;
  event_start: string;
  event_end: string;
  registration_deadline: string;
  scenario_id: string;
  team_mode: boolean;
  team_size_limit: string;
  max_participants: string;
  range_spinup_minutes: string;
  submission_cooldown_seconds: string;
  attempt_limit_mode: string;
  attempt_limit_cooldown_seconds: string;
  auto_cleanup: boolean;
  cleanup_delay_hours: string;
  rules: string;
  reminder_hours: string;
  event_timezone: string;
  capacity_hints: string;
  logo_url: string;
  theme_color: string;
  visible_os_types: string;
  scoreboard_visibility: string;
  rating_visibility: string;
  scoring_mode: string;
}

const EMPTY: FormState = {
  name: "",
  description: "",
  event_start: "",
  event_end: "",
  registration_deadline: "",
  scenario_id: "",
  team_mode: false,
  team_size_limit: "",
  max_participants: "",
  range_spinup_minutes: "30",
  submission_cooldown_seconds: "0",
  attempt_limit_mode: "lockout",
  attempt_limit_cooldown_seconds: "300",
  auto_cleanup: true,
  cleanup_delay_hours: "24",
  rules: "",
  reminder_hours: "24, 1",
  event_timezone: "UTC",
  capacity_hints: "",
  logo_url: "",
  theme_color: "",
  visible_os_types: "kali",
  scoreboard_visibility: "public",
  rating_visibility: "public",
  scoring_mode: "standard",
};

function fromEvent(event: CtfEventDetail): FormState {
  return {
    name: event.name ?? "",
    description: event.description ?? "",
    event_start: toDateTimeLocalValue(event.event_start),
    event_end: toDateTimeLocalValue(event.event_end),
    registration_deadline: toDateTimeLocalValue(event.registration_deadline),
    scenario_id: event.scenario_id ?? "",
    team_mode: Boolean(event.team_mode),
    team_size_limit: event.team_size_limit == null ? "" : String(event.team_size_limit),
    max_participants: event.max_participants == null ? "" : String(event.max_participants),
    range_spinup_minutes: String(event.range_spinup_minutes ?? 30),
    submission_cooldown_seconds: String(event.submission_cooldown_seconds ?? 0),
    attempt_limit_mode: event.attempt_limit_mode || "lockout",
    attempt_limit_cooldown_seconds: String(event.attempt_limit_cooldown_seconds ?? 300),
    auto_cleanup: Boolean(event.auto_cleanup),
    cleanup_delay_hours: String(event.cleanup_delay_hours ?? 24),
    rules: event.rules ?? "",
    reminder_hours: (event.reminder_hours ?? [24, 1]).join(", "),
    event_timezone: event.event_timezone || "UTC",
    capacity_hints: Object.keys(event.capacity_hints ?? {}).length
      ? JSON.stringify(event.capacity_hints, null, 2)
      : "",
    logo_url: event.logo_url ?? "",
    theme_color: event.theme_color ?? "",
    visible_os_types: (event.visible_os_types ?? ["kali"]).join(", "),
    scoreboard_visibility: event.scoreboard_visibility || "public",
    rating_visibility: event.rating_visibility || "public",
    scoring_mode: event.scoring_mode || "standard",
  };
}

function intOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

function intOr(value: string, fallback: number): number {
  return intOrNull(value) ?? fallback;
}

/** Parse "24, 1"-style input into the reminder-hours list (CTF-1005). */
function parseReminderHours(text: string): number[] {
  return text
    .split(",")
    .map((part) => Number.parseInt(part.trim(), 10))
    .filter((n) => Number.isFinite(n) && n > 0 && n <= 720);
}

/** Parse the organizer's capacity-hints JSON; invalid or empty input becomes {}. */
function parseCapacityHints(text: string): Record<string, unknown> {
  if (!text.trim()) return {};
  try {
    const parsed: unknown = JSON.parse(text);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

function toPayload(state: FormState): CtfEventWrite {
  return {
    name: state.name,
    description: state.description,
    event_start: fromDateTimeLocalValue(state.event_start) ?? "",
    event_end: fromDateTimeLocalValue(state.event_end) ?? "",
    registration_deadline: fromDateTimeLocalValue(state.registration_deadline),
    scenario_id: state.scenario_id,
    team_mode: state.team_mode,
    team_size_limit: intOrNull(state.team_size_limit),
    max_participants: intOrNull(state.max_participants),
    range_spinup_minutes: intOr(state.range_spinup_minutes, 30),
    submission_cooldown_seconds: intOr(state.submission_cooldown_seconds, 0),
    attempt_limit_mode: state.attempt_limit_mode,
    attempt_limit_cooldown_seconds: intOr(state.attempt_limit_cooldown_seconds, 300),
    auto_cleanup: state.auto_cleanup,
    cleanup_delay_hours: intOr(state.cleanup_delay_hours, 24),
    rules: state.rules,
    reminder_hours: parseReminderHours(state.reminder_hours),
    event_timezone: state.event_timezone.trim() || "UTC",
    capacity_hints: parseCapacityHints(state.capacity_hints),
    logo_url: state.logo_url.trim(),
    theme_color: state.theme_color.trim(),
    visible_os_types: state.visible_os_types
      .split(",")
      .map((part) => part.trim().toLowerCase())
      .filter(Boolean),
    scoreboard_visibility: state.scoreboard_visibility,
    rating_visibility: state.rating_visibility,
    scoring_mode: state.scoring_mode,
  };
}

/** Render the edit-mode loading / not-found states, or null when the form itself should render. */
export function renderEditLoadState(
  mode: "create" | "edit",
  existing: ReturnType<typeof useCtfEvent>,
): React.ReactNode {
  if (mode !== "edit") return null;
  if (existing.isLoading) {
    return (
      <div className="grid place-items-center py-24 text-muted-foreground">
        <Loader2 className="size-6 animate-spin" aria-label="Loading event" />
      </div>
    );
  }
  if (existing.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Event not found</AlertTitle>
        <AlertDescription>
          This event may have been deleted.{" "}
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

function submitEventForm(
  event: React.FormEvent,
  opts: Readonly<{
    state: FormState;
    mode: "create" | "edit";
    eventId: string;
    create: ReturnType<typeof useCreateCtfEvent>;
    update: ReturnType<typeof useUpdateCtfEvent>;
    navigate: ReturnType<typeof useNavigate>;
  }>,
) {
  event.preventDefault();
  const payload = toPayload(opts.state);
  if (opts.mode === "create") {
    opts.create.mutate(payload, { onSuccess: (result) => opts.navigate(ctfAdminEventPath(result.id)) });
  } else if (opts.eventId) {
    opts.update.mutate(payload, { onSuccess: () => opts.navigate(ctfAdminEventPath(opts.eventId)) });
  }
}

/** Form state, error mapping, and submit plumbing for EventFormPage. */
export function useEventFormState(mode: "create" | "edit") {
  const navigate = useNavigate();
  const params = useParams();
  const eventId = mode === "edit" ? (params.eventId ?? "") : "";

  const existing = useCtfEvent(eventId, mode === "edit");
  const scenarios = useCtfScenarios();
  const create = useCreateCtfEvent();
  const update = useUpdateCtfEvent(eventId);
  const mutation = mode === "create" ? create : update;

  const [state, setState] = useState<FormState>(EMPTY);
  const [initialized, setInitialized] = useState(mode === "create");
  const formRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    if (mode === "edit" && existing.data && !initialized) {
      setState(fromEvent(existing.data));
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
    submitEventForm(event, { state, mode, eventId, create, update, navigate });
  }

  return { eventId, existing, scenarios, mutation, state, formRef, nonFieldError, set, firstError, onSubmit, navigate };
}
