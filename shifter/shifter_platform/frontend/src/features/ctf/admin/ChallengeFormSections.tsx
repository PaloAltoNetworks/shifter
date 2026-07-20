/**
 * Section components for the CTF organizer challenge create/edit form. Split out
 * of ChallengeFormPage to keep that file small: `BasicFields` renders the core
 * challenge fields, and the edit-only sub-sections manage flags, hints, files,
 * and prerequisites. All mutations route through the shared `/api/v1/ctf/` hooks.
 */
import { useRef, useState } from "react";

import { Loader2, Trash2 } from "lucide-react";

import { useAddCtfFlag, useAddCtfHint, useAddCtfPrerequisite, useCtfChallengeFiles, useCtfChallengeHints, useCtfChallengePrerequisites, useDeleteCtfChallengeFile, useDeleteCtfHint, useDeleteCtfPrerequisite, useRemoveCtfFlag, useUploadCtfChallengeFile } from "@/api/ctfAdmin";
import { describeMutationError } from "@/api/errors";
import { CTF_CHALLENGE_CATEGORIES, CTF_CHALLENGE_DIFFICULTIES } from "@/api/types";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";

import { titleCase } from "../format";
import { intOr, type FormState } from "./challenge-form-state";
import { CheckboxField, SelectField, TextAreaField, TextField } from "./form-fields";

const VISIBILITY_OPTIONS = ["visible", "hidden", "locked"] as const;

export function BasicFields({
  state,
  set,
  firstError,
  mode,
}: Readonly<{
  state: FormState;
  set: <K extends keyof FormState>(key: K, value: FormState[K]) => void;
  firstError: (field: string) => string | undefined;
  mode: "create" | "edit";
}>) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-5">
        <TextField id="c-name" label="Name" value={state.name} error={firstError("name")} onChange={(v) => set("name", v)} />
        <TextAreaField
          id="c-desc"
          label="Description"
          rows={4}
          value={state.description}
          error={firstError("description")}
          onChange={(v) => set("description", v)}
        />
        <div className="grid gap-5 sm:grid-cols-2">
          <SelectField
            id="c-cat"
            label="Category"
            value={state.category}
            error={firstError("category")}
            options={CTF_CHALLENGE_CATEGORIES}
            labelFor={titleCase}
            onChange={(v) => set("category", v)}
          />
          <SelectField
            id="c-diff"
            label="Difficulty"
            value={state.difficulty}
            error={firstError("difficulty")}
            options={CTF_CHALLENGE_DIFFICULTIES}
            labelFor={titleCase}
            onChange={(v) => set("difficulty", v)}
          />
        </div>
        <div className="grid gap-5 sm:grid-cols-3">
          <TextField id="c-points" label="Points" type="number" min={0} value={state.points} error={firstError("points")} onChange={(v) => set("points", v)} />
          <TextField id="c-order" label="Order" type="number" min={0} value={state.order} error={firstError("order")} onChange={(v) => set("order", v)} />
          <TextField
            id="c-attempts"
            label="Max attempts (0 = ∞)"
            type="number"
            min={0}
            value={state.max_attempts}
            error={firstError("max_attempts")}
            onChange={(v) => set("max_attempts", v)}
          />
        </div>
        <div className="grid gap-5 sm:grid-cols-3">
          <TextField
            id="c-minpoints"
            label="Minimum points (dynamic scoring)"
            type="number"
            min={0}
            value={state.minimum_points}
            error={firstError("minimum_points")}
            onChange={(v) => set("minimum_points", v)}
          />
          <SelectField
            id="c-decayfn"
            label="Decay curve"
            value={state.decay_function}
            error={firstError("decay_function")}
            options={["linear", "logarithmic"]}
            labelFor={titleCase}
            onChange={(v) => set("decay_function", v)}
          />
          <TextField
            id="c-decaycount"
            label="Solves to reach minimum (0 = no decay)"
            type="number"
            min={0}
            value={state.decay_solve_count}
            error={firstError("decay_solve_count")}
            onChange={(v) => set("decay_solve_count", v)}
          />
        </div>
        <TextField
          id="c-format"
          label="Flag format (hint shown to participants)"
          value={state.flag_format}
          placeholder="FLAG{...}"
          error={firstError("flag_format")}
          onChange={(v) => set("flag_format", v)}
        />
        {mode === "create" ? (
          <TextField
            id="c-flag"
            label="Flag"
            value={state.flag}
            placeholder="FLAG{the_answer}"
            error={firstError("flag")}
            onChange={(v) => set("flag", v)}
          />
        ) : null}
        <div className="grid gap-5 sm:grid-cols-2">
          <TextField
            id="c-target"
            label="Target instance (optional)"
            value={state.target_instance_name}
            error={firstError("target_instance_name")}
            onChange={(v) => set("target_instance_name", v)}
          />
          <TextField
            id="c-port"
            label="Target port (optional)"
            type="number"
            min={0}
            value={state.target_port}
            error={firstError("target_port")}
            onChange={(v) => set("target_port", v)}
          />
        </div>
        <div className="grid gap-5 sm:grid-cols-2">
          <SelectField
            id="c-vis"
            label="Visibility"
            value={state.visibility}
            error={firstError("visibility")}
            options={VISIBILITY_OPTIONS}
            labelFor={titleCase}
            onChange={(v) => set("visibility", v)}
          />
          <TextField
            id="c-release"
            label="Release time (optional, auto-reveals a hidden challenge)"
            type="datetime-local"
            value={state.release_time}
            error={firstError("release_time")}
            onChange={(v) => set("release_time", v)}
          />
        </div>
        <div className="grid gap-5 sm:grid-cols-2">
          <TextField id="c-tags" label="Tags (comma separated)" value={state.tags} onChange={(v) => set("tags", v)} />
          <TextField id="c-topics" label="Topics (comma separated)" value={state.topics} onChange={(v) => set("topics", v)} />
        </div>
        <TextAreaField
          id="c-solution"
          label="Solution / writeup (organizer-only)"
          rows={3}
          value={state.solution}
          error={firstError("solution")}
          onChange={(v) => set("solution", v)}
        />
      </CardContent>
    </Card>
  );
}

function SectionCard({ title, children }: Readonly<{ title: string; children: React.ReactNode }>) {
  return (
    <Card>
      <CardContent>
        <h2 className="mb-4 text-sm font-semibold">{title}</h2>
        {children}
      </CardContent>
    </Card>
  );
}

type AddedFlag = { id: string; flag_type: string; order: number };

function AddedFlagRow({
  entry,
  disabled,
  onRemove,
}: Readonly<{ entry: AddedFlag; disabled: boolean; onRemove: (id: string) => void }>) {
  return (
    <li className="flex items-center justify-between gap-3 py-2 text-sm">
      <span className="text-muted-foreground">
        Flag added ({titleCase(entry.flag_type)}, order {entry.order})
      </span>
      <Button variant="ghost" size="sm" disabled={disabled} onClick={() => onRemove(entry.id)}>
        <Trash2 className="size-4" aria-hidden="true" />
        Remove
      </Button>
    </li>
  );
}

export function FlagsSection({ challengeId }: Readonly<{ challengeId: string }>) {
  const add = useAddCtfFlag(challengeId);
  const remove = useRemoveCtfFlag(challengeId);
  const [flag, setFlag] = useState("");
  const [caseSensitive, setCaseSensitive] = useState(true);
  // No flags list endpoint exists (flags are secret); track this session's adds
  // so they can be removed without exposing stored flag values.
  const [added, setAdded] = useState<AddedFlag[]>([]);
  const error = describeMutationError(add.error ?? remove.error, "Could not update flags.");

  const dropAdded = (id: string) => setAdded((prev) => prev.filter((f) => f.id !== id));

  function handleRemove(id: string) {
    remove.mutate(id, { onSuccess: () => dropAdded(id) });
  }

  function recordAdded(result: { id: string; flag_type: string; order: number }) {
    setAdded((prev) => [...prev, { id: result.id, flag_type: result.flag_type, order: result.order }]);
    setFlag("");
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = flag.trim();
    if (!trimmed) return;
    add.mutate(
      { flag: trimmed, flag_type: "static", case_sensitive: caseSensitive, order: added.length },
      { onSuccess: recordAdded },
    );
  }

  return (
    <SectionCard title="Flags">
      <form className="flex flex-col gap-3" onSubmit={handleSubmit}>
        <Label htmlFor="flag-add">Add a flag</Label>
        <div className="flex gap-2">
          <Input id="flag-add" value={flag} autoComplete="off" placeholder="FLAG{...}" onChange={(e) => setFlag(e.target.value)} />
          <Button type="submit" disabled={add.isPending || !flag.trim()}>
            Add
          </Button>
        </div>
        <CheckboxField id="flag-cs" label="Case sensitive" checked={caseSensitive} onChange={setCaseSensitive} />
      </form>
      {added.length > 0 ? (
        <ul className="mt-4 divide-y divide-border/60">
          {added.map((entry) => (
            <AddedFlagRow key={entry.id} entry={entry} disabled={remove.isPending} onRemove={handleRemove} />
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-xs text-muted-foreground">Stored flags are hidden. Flags you add this session appear here.</p>
      )}
      {error ? (
        <Alert variant="destructive" className="mt-3">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
    </SectionCard>
  );
}

export function HintsSection({ challengeId }: Readonly<{ challengeId: string }>) {
  const query = useCtfChallengeHints(challengeId);
  const add = useAddCtfHint(challengeId);
  const remove = useDeleteCtfHint(challengeId);
  const [text, setText] = useState("");
  const [penalty, setPenalty] = useState("0");
  const error = describeMutationError(add.error ?? remove.error, "Could not update hints.");
  const hints = query.data?.hints ?? [];

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = text.trim();
    if (!trimmed) return;
    add.mutate({ text: trimmed, penalty: intOr(penalty, 0), order: hints.length }, { onSuccess: () => setText("") });
  }

  let body: React.ReactNode;
  if (query.isLoading) {
    body = <Skeleton className="h-10 w-full" />;
  } else if (hints.length === 0) {
    body = <p className="text-sm text-muted-foreground">No hints yet.</p>;
  } else {
    body = (
      <ul className="divide-y divide-border/60">
        {hints.map((hint) => (
          <li key={hint.id} className="flex items-start justify-between gap-3 py-2">
            <span className="min-w-0 text-sm">
              <span className="block whitespace-pre-wrap">{hint.text}</span>
              <span className="text-xs text-muted-foreground">−{hint.penalty} pts</span>
            </span>
            <Button
              variant="ghost"
              size="sm"
              disabled={remove.isPending}
              onClick={() => remove.mutate(hint.id)}
              aria-label={`Delete hint ${hint.order + 1}`}
            >
              <Trash2 className="size-4" aria-hidden="true" />
            </Button>
          </li>
        ))}
      </ul>
    );
  }

  return (
    <SectionCard title="Hints">
      {body}
      <form className="mt-4 flex flex-col gap-3" onSubmit={handleSubmit}>
        <div className="flex flex-col gap-2">
          <Label htmlFor="hint-text">Add a hint</Label>
          <Input id="hint-text" value={text} onChange={(e) => setText(e.target.value)} placeholder="Hint text" />
        </div>
        <div className="flex items-end gap-2">
          <div className="flex flex-col gap-2">
            <Label htmlFor="hint-penalty">Penalty</Label>
            <Input id="hint-penalty" type="number" min={0} value={penalty} onChange={(e) => setPenalty(e.target.value)} className="w-28" />
          </div>
          <Button type="submit" disabled={add.isPending || !text.trim()}>
            Add hint
          </Button>
        </div>
      </form>
      {error ? (
        <Alert variant="destructive" className="mt-3">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
    </SectionCard>
  );
}

export function FilesSection({ challengeId }: Readonly<{ challengeId: string }>) {
  const query = useCtfChallengeFiles(challengeId);
  const upload = useUploadCtfChallengeFile(challengeId);
  const remove = useDeleteCtfChallengeFile(challengeId);
  const [displayName, setDisplayName] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const error = describeMutationError(upload.error ?? remove.error, "Could not update files.");
  const files = query.data?.files ?? [];

  function resetUpload() {
    setDisplayName("");
    if (fileRef.current) fileRef.current.value = "";
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    upload.mutate({ file, displayName: displayName.trim() || undefined }, { onSuccess: resetUpload });
  }

  let body: React.ReactNode;
  if (query.isLoading) {
    body = <Skeleton className="h-10 w-full" />;
  } else if (files.length === 0) {
    body = <p className="text-sm text-muted-foreground">No attachments yet.</p>;
  } else {
    body = (
      <ul className="divide-y divide-border/60">
        {files.map((file) => (
          <li key={file.id} className="flex items-center justify-between gap-3 py-2">
            <span className="min-w-0 text-sm">
              <span className="block truncate font-medium">{file.display_name || file.filename}</span>
              <span className="text-xs text-muted-foreground">{file.file_size_display}</span>
            </span>
            <Button
              variant="ghost"
              size="sm"
              disabled={remove.isPending}
              onClick={() => remove.mutate(file.id)}
              aria-label={`Delete ${file.display_name || file.filename}`}
            >
              <Trash2 className="size-4" aria-hidden="true" />
            </Button>
          </li>
        ))}
      </ul>
    );
  }

  return (
    <SectionCard title="Files">
      {body}
      <form className="mt-4 flex flex-col gap-3" onSubmit={handleSubmit}>
        <div className="flex flex-col gap-2">
          <Label htmlFor="file-input">Upload an attachment</Label>
          <Input id="file-input" type="file" ref={fileRef} />
        </div>
        <div className="flex items-end gap-2">
          <div className="flex flex-1 flex-col gap-2">
            <Label htmlFor="file-name">Display name (optional)</Label>
            <Input id="file-name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          </div>
          <Button type="submit" disabled={upload.isPending}>
            {upload.isPending ? <Loader2 className="size-4 animate-spin" /> : null}
            Upload
          </Button>
        </div>
      </form>
      {error ? (
        <Alert variant="destructive" className="mt-3">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
    </SectionCard>
  );
}

export function PrerequisitesSection({ challengeId }: Readonly<{ challengeId: string }>) {
  const query = useCtfChallengePrerequisites(challengeId);
  const add = useAddCtfPrerequisite(challengeId);
  const remove = useDeleteCtfPrerequisite(challengeId);
  const [requiredId, setRequiredId] = useState("");
  const error = describeMutationError(add.error ?? remove.error, "Could not update prerequisites.");
  const prerequisites = query.data?.prerequisites ?? [];

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = requiredId.trim();
    if (!trimmed) return;
    add.mutate({ required_challenge_id: trimmed }, { onSuccess: () => setRequiredId("") });
  }

  let body: React.ReactNode;
  if (query.isLoading) {
    body = <Skeleton className="h-10 w-full" />;
  } else if (prerequisites.length === 0) {
    body = <p className="text-sm text-muted-foreground">No prerequisites. This challenge unlocks immediately.</p>;
  } else {
    body = (
      <ul className="divide-y divide-border/60">
        {prerequisites.map((prereq) => (
          <li key={prereq.id} className="flex items-center justify-between gap-3 py-2 text-sm">
            <span className="min-w-0">
              <span className="block truncate font-medium">{prereq.required_challenge_name}</span>
              <span className="text-xs text-muted-foreground">{titleCase(prereq.required_challenge_category)}</span>
            </span>
            <Button
              variant="ghost"
              size="sm"
              disabled={remove.isPending}
              onClick={() => remove.mutate(prereq.id)}
              aria-label={`Remove prerequisite ${prereq.required_challenge_name}`}
            >
              <Trash2 className="size-4" aria-hidden="true" />
            </Button>
          </li>
        ))}
      </ul>
    );
  }

  return (
    <SectionCard title="Prerequisites">
      {body}
      <form className="mt-4 flex items-end gap-2" onSubmit={handleSubmit}>
        <div className="flex flex-1 flex-col gap-2">
          <Label htmlFor="prereq-id">Required challenge ID</Label>
          <Input id="prereq-id" value={requiredId} onChange={(e) => setRequiredId(e.target.value)} placeholder="UUID" />
        </div>
        <Button type="submit" disabled={add.isPending || !requiredId.trim()}>
          Add
        </Button>
      </form>
      {error ? (
        <Alert variant="destructive" className="mt-3">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
    </SectionCard>
  );
}
