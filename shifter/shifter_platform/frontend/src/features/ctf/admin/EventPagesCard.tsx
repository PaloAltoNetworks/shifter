import { useState } from "react";

import {
  useCreateCtfEventPage,
  useCtfEventPages,
  useDeleteCtfEventPage,
  useUpdateCtfEventPage,
} from "@/api/ctfAdmin";
import { describeMutationError } from "@/api/errors";
import type { CtfEventPage } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

// The reserved event-page slug the platform surfaces as the participant briefing
// (mirrors ctf.models.event.RESERVED_BRIEFING_SLUG). Keyed on the slug, never
// the display title.
const RESERVED_BRIEFING_SLUG = "briefing";
const BRIEFING_TITLE = "Participant Briefing";

/** Edit or remove an already-published briefing; seeded from its current body. */
function BriefingEditor({
  page,
  onSave,
  onRemove,
  saving,
  removing,
}: Readonly<{
  page: CtfEventPage;
  onSave: (body: string) => void;
  onRemove: () => void;
  saving: boolean;
  removing: boolean;
}>) {
  const [body, setBody] = useState(() => page.body);
  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        if (!body.trim()) return;
        onSave(body);
      }}
    >
      <div className="flex flex-col gap-1">
        <Label htmlFor="briefing-body">Briefing (markdown)</Label>
        <Textarea id="briefing-body" rows={4} value={body} onChange={(e) => setBody(e.target.value)} />
      </div>
      <div className="flex gap-2">
        <Button type="submit" disabled={!body.trim() || saving}>
          Save briefing
        </Button>
        <Button type="button" size="sm" variant="ghost" disabled={removing} onClick={onRemove}>
          Remove briefing
        </Button>
      </div>
    </form>
  );
}

/** Organizer-authored informational pages and the participant briefing (CTF-1303 / #1854). */
export function EventPagesCard({ eventId }: Readonly<{ eventId: string }>) {
  const pages = useCtfEventPages(eventId);
  const create = useCreateCtfEventPage(eventId);
  const update = useUpdateCtfEventPage(eventId);
  const remove = useDeleteCtfEventPage(eventId);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [briefingBody, setBriefingBody] = useState("");
  const errorMessage = describeMutationError(create.error ?? update.error, "Could not save the page.");

  const allPages = pages.data?.pages ?? [];
  const briefingPage = allPages.find((page) => page.slug === RESERVED_BRIEFING_SLUG);
  const customPages = allPages.filter((page) => page.slug !== RESERVED_BRIEFING_SLUG);

  return (
    <Card>
      <CardContent className="space-y-6">
        <section className="space-y-3">
          <div>
            <h2 className="text-sm font-semibold">Participant briefing</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Event-specific onboarding shown to participants on the Briefing page — where they are, how the range is
              reached, where to start. Markdown. It is <strong>not translated</strong>; you own its language. Never
              include flags, passwords, invite/reset links, or any credential.
            </p>
          </div>
          {briefingPage ? (
            <BriefingEditor
              key={briefingPage.id}
              page={briefingPage}
              onSave={(nextBody) => update.mutate({ pageId: briefingPage.id, body: nextBody })}
              onRemove={() => remove.mutate(briefingPage.id)}
              saving={update.isPending}
              removing={remove.isPending}
            />
          ) : (
            <form
              className="flex flex-col gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                if (!briefingBody.trim()) return;
                create.mutate(
                  { title: BRIEFING_TITLE, body: briefingBody, slug: RESERVED_BRIEFING_SLUG },
                  { onSuccess: () => setBriefingBody("") },
                );
              }}
            >
              <div className="flex flex-col gap-1">
                <Label htmlFor="briefing-new-body">Briefing (markdown)</Label>
                <Textarea
                  id="briefing-new-body"
                  rows={4}
                  value={briefingBody}
                  onChange={(e) => setBriefingBody(e.target.value)}
                />
              </div>
              <div>
                <Button type="submit" disabled={!briefingBody.trim() || create.isPending}>
                  Add briefing
                </Button>
              </div>
            </form>
          )}
        </section>

        <section className="space-y-3">
          <div>
            <h2 className="text-sm font-semibold">Custom pages</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Markdown pages (rules, FAQ, getting started, sponsors) shown on the participant home page. Not translated.
            </p>
          </div>
          <form
            className="flex flex-col gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (!title.trim() || !body.trim()) return;
              create.mutate(
                { title: title.trim(), body },
                {
                  onSuccess: () => {
                    setTitle("");
                    setBody("");
                  },
                },
              );
            }}
          >
            <div className="flex flex-col gap-1">
              <Label htmlFor="page-title">Title</Label>
              <Input id="page-title" value={title} onChange={(e) => setTitle(e.target.value)} />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="page-body">Body (markdown)</Label>
              <Textarea id="page-body" rows={4} value={body} onChange={(e) => setBody(e.target.value)} />
            </div>
            <div>
              <Button type="submit" disabled={!title.trim() || !body.trim() || create.isPending}>
                Add page
              </Button>
            </div>
          </form>
          {customPages.length ? (
            <ul className="divide-y divide-border/60">
              {customPages.map((page) => (
                <li key={page.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                  <span>
                    {page.title} <span className="text-muted-foreground">/{page.slug}</span>
                  </span>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    disabled={remove.isPending}
                    onClick={() => remove.mutate(page.id)}
                  >
                    Remove
                  </Button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted-foreground">No custom pages yet.</p>
          )}
        </section>

        {create.error ?? update.error ? <p className="text-xs text-destructive">{errorMessage}</p> : null}
      </CardContent>
    </Card>
  );
}
