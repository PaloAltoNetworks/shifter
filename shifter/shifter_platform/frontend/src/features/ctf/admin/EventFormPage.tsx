import { Link } from "react-router-dom";

import { Loader2 } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

import { ctfAdminEventPath, ctfAdminEventsPath } from "../routes";
import { CheckboxField, FieldError, TextAreaField, TextField } from "./form-fields";
import { NO_SCENARIO, renderEditLoadState, useEventFormState } from "./eventFormState";

export function EventFormPage({ mode }: Readonly<{ mode: "create" | "edit" }>) {
  const { eventId, existing, scenarios, mutation, state, formRef, nonFieldError, set, firstError, onSubmit, navigate } =
    useEventFormState(mode);

  const editLoadState = renderEditLoadState(mode, existing);
  if (editLoadState) return <>{editLoadState}</>;

  const cancelHref = mode === "edit" && eventId ? ctfAdminEventPath(eventId) : ctfAdminEventsPath();
  const scenarioOptions = scenarios.data?.scenarios ?? [];

  return (
    <div className="mx-auto max-w-3xl">
      <nav className="mb-3 text-sm text-muted-foreground" aria-label="Breadcrumb">
        <Link className="hover:text-foreground" to={ctfAdminEventsPath()}>
          Events
        </Link>
        <span className="px-1.5">/</span>
        <span className="text-foreground">{mode === "create" ? "New event" : "Edit"}</span>
      </nav>
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">
        {mode === "create" ? "New event" : `Edit ${existing.data?.name ?? "event"}`}
      </h1>

      {nonFieldError ? (
        <Alert variant="destructive" className="mb-4">
          <AlertTitle>Could not save</AlertTitle>
          <AlertDescription>{nonFieldError}</AlertDescription>
        </Alert>
      ) : null}

      <form ref={formRef} onSubmit={onSubmit} noValidate>
        <Card>
          <CardContent className="flex flex-col gap-5">
            <TextField id="e-name" label="Name" value={state.name} error={firstError("name")} onChange={(v) => set("name", v)} />
            <TextAreaField
              id="e-desc"
              label="Description"
              rows={3}
              value={state.description}
              error={firstError("description")}
              onChange={(v) => set("description", v)}
            />
            <TextAreaField
              id="e-rules"
              label="Rules (markdown, shown to participants)"
              rows={5}
              value={state.rules}
              error={firstError("rules")}
              onChange={(v) => set("rules", v)}
            />

            <div className="grid gap-5 sm:grid-cols-2">
              <TextField
                id="e-start"
                label="Event start"
                type="datetime-local"
                value={state.event_start}
                error={firstError("event_start")}
                onChange={(v) => set("event_start", v)}
              />
              <TextField
                id="e-end"
                label="Event end"
                type="datetime-local"
                value={state.event_end}
                error={firstError("event_end")}
                onChange={(v) => set("event_end", v)}
              />
            </div>

            <TextField
              id="e-regdeadline"
              label="Registration deadline (optional)"
              type="datetime-local"
              value={state.registration_deadline}
              error={firstError("registration_deadline")}
              onChange={(v) => set("registration_deadline", v)}
            />

            <div className="flex flex-col gap-2">
              <Label htmlFor="e-scenario">Scenario</Label>
              <Select
                value={state.scenario_id === "" ? NO_SCENARIO : state.scenario_id}
                onValueChange={(v) => set("scenario_id", v === NO_SCENARIO ? "" : v)}
              >
                <SelectTrigger
                  id="e-scenario"
                  className="w-full"
                  aria-invalid={firstError("scenario_id") ? true : undefined}
                >
                  <SelectValue placeholder="Select a scenario" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_SCENARIO}>No scenario</SelectItem>
                  {scenarioOptions.map((scenario) => (
                    <SelectItem key={scenario.id} value={scenario.id}>
                      {scenario.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <FieldError id="e-scenario-e" error={firstError("scenario_id")} />
            </div>

            <div className="grid gap-5 sm:grid-cols-2">
              <TextField
                id="e-maxpart"
                label="Max participants (optional)"
                type="number"
                min={1}
                value={state.max_participants}
                error={firstError("max_participants")}
                onChange={(v) => set("max_participants", v)}
              />
              <TextField
                id="e-spinup"
                label="Range spin-up (minutes)"
                type="number"
                min={0}
                value={state.range_spinup_minutes}
                error={firstError("range_spinup_minutes")}
                onChange={(v) => set("range_spinup_minutes", v)}
              />
            </div>

            <fieldset className="flex flex-col gap-3">
              <legend className="mb-1 text-sm font-medium">Submission limits</legend>
              <div className="grid gap-5 sm:grid-cols-2">
                <TextField
                  id="e-subcooldown"
                  label="Cooldown between submissions (seconds)"
                  type="number"
                  min={0}
                  value={state.submission_cooldown_seconds}
                  error={firstError("submission_cooldown_seconds")}
                  onChange={(v) => set("submission_cooldown_seconds", v)}
                />
                <div className="flex flex-col gap-2">
                  <Label htmlFor="e-attemptmode">When max attempts is reached</Label>
                  <Select value={state.attempt_limit_mode} onValueChange={(v) => set("attempt_limit_mode", v)}>
                    <SelectTrigger id="e-attemptmode" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="lockout">Lock out permanently</SelectItem>
                      <SelectItem value="timeout">Time out, then allow retries</SelectItem>
                    </SelectContent>
                  </Select>
                  <FieldError id="e-attemptmode-e" error={firstError("attempt_limit_mode")} />
                </div>
              </div>
              {state.attempt_limit_mode === "timeout" ? (
                <TextField
                  id="e-attemptcooldown"
                  label="Attempt-limit timeout (seconds)"
                  type="number"
                  min={1}
                  value={state.attempt_limit_cooldown_seconds}
                  error={firstError("attempt_limit_cooldown_seconds")}
                  onChange={(v) => set("attempt_limit_cooldown_seconds", v)}
                />
              ) : null}
            </fieldset>

            <fieldset className="flex flex-col gap-3">
              <legend className="mb-1 text-sm font-medium">Options</legend>
              <CheckboxField id="e-team" label="Team mode" checked={state.team_mode} onChange={(c) => set("team_mode", c)} />
              {state.team_mode ? (
                <TextField
                  id="e-teamsize"
                  label="Team size limit (optional)"
                  type="number"
                  min={1}
                  value={state.team_size_limit}
                  error={firstError("team_size_limit")}
                  onChange={(v) => set("team_size_limit", v)}
                />
              ) : null}
              <div className="flex flex-col gap-2">
                <Label htmlFor="e-scoreboardvis">Scoreboard visibility</Label>
                <Select value={state.scoreboard_visibility} onValueChange={(v) => set("scoreboard_visibility", v)}>
                  <SelectTrigger id="e-scoreboardvis" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="public">Public (anyone with the link)</SelectItem>
                    <SelectItem value="participants">Participants and organizers only</SelectItem>
                    <SelectItem value="hidden">Hidden (organizers only)</SelectItem>
                  </SelectContent>
                </Select>
                <FieldError id="e-scoreboardvis-e" error={firstError("scoreboard_visibility")} />
              </div>
              <CheckboxField
                id="e-cleanup"
                label="Auto-clean up ranges after the event"
                checked={state.auto_cleanup}
                onChange={(c) => set("auto_cleanup", c)}
              />
              <TextField
                id="e-cleanupdelay"
                label="Cleanup delay (hours after end)"
                type="number"
                value={state.cleanup_delay_hours}
                error={firstError("cleanup_delay_hours")}
                onChange={(v) => set("cleanup_delay_hours", v)}
              />
              <TextField
                id="e-reminders"
                label="Reminder hours before start (comma-separated)"
                value={state.reminder_hours}
                error={firstError("reminder_hours")}
                onChange={(v) => set("reminder_hours", v)}
              />
              <TextField
                id="e-timezone"
                label="Event timezone (for emails)"
                value={state.event_timezone}
                error={firstError("event_timezone")}
                onChange={(v) => set("event_timezone", v)}
              />
              <div className="flex flex-col gap-2">
                <Label htmlFor="e-scoringmode">Scoring mode</Label>
                <Select value={state.scoring_mode} onValueChange={(v) => set("scoring_mode", v)}>
                  <SelectTrigger id="e-scoringmode" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="standard">Standard (fixed challenge values)</SelectItem>
                    <SelectItem value="dynamic">Dynamic (values decay as solves accrue)</SelectItem>
                  </SelectContent>
                </Select>
                <FieldError id="e-scoringmode-e" error={firstError("scoring_mode")} />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="e-ratingvis">Challenge ratings</Label>
                <Select value={state.rating_visibility} onValueChange={(v) => set("rating_visibility", v)}>
                  <SelectTrigger id="e-ratingvis" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="public">Public (participants see averages)</SelectItem>
                    <SelectItem value="organizer">Organizer-only</SelectItem>
                    <SelectItem value="disabled">Disabled</SelectItem>
                  </SelectContent>
                </Select>
                <FieldError id="e-ratingvis-e" error={firstError("rating_visibility")} />
              </div>
            </fieldset>
          </CardContent>
          <CardFooter className="justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => navigate(cancelHref)}>
              Cancel
            </Button>
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? <Loader2 className="size-4 animate-spin" /> : null}
              {mode === "create" ? "Create event" : "Save changes"}
            </Button>
          </CardFooter>
        </Card>
      </form>
    </div>
  );
}
