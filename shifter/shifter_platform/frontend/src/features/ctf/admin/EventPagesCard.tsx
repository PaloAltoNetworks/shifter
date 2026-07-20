import { useState } from "react";

import { useCreateCtfEventPage, useCtfEventPages, useDeleteCtfEventPage } from "@/api/ctfAdmin";
import { describeMutationError } from "@/api/errors";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

/** Organizer-authored informational pages (CTF-1303). */
export function EventPagesCard({ eventId }: Readonly<{ eventId: string }>) {
  const pages = useCtfEventPages(eventId);
  const create = useCreateCtfEventPage(eventId);
  const remove = useDeleteCtfEventPage(eventId);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const errorMessage = describeMutationError(create.error, "Could not create the page.");

  return (
    <Card>
      <CardContent className="space-y-4">
        <div>
          <h2 className="text-sm font-semibold">Custom pages</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Markdown pages (rules, FAQ, getting started, sponsors) shown on the participant home page.
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
        {create.error ? <p className="text-xs text-destructive">{errorMessage}</p> : null}
        {pages.data?.pages?.length ? (
          <ul className="divide-y divide-border/60">
            {pages.data.pages.map((page) => (
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
      </CardContent>
    </Card>
  );
}
