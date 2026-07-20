import { useState } from "react";

import { useCtfEventLifecycle } from "@/api/ctfAdmin";
import { describeMutationError } from "@/api/errors";
import type { CtfEventDetail, CtfEventLifecycleAction } from "@/api/types";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

import { titleCase } from "../format";

/** Valid transitions from each status (mirrors the service state machine). */
const ACTIONS_BY_STATUS: Readonly<Record<string, ReadonlyArray<{ action: CtfEventLifecycleAction; label: string }>>> = {
  draft: [{ action: "open_registration", label: "Open registration" }],
  registration: [{ action: "activate", label: "Activate" }],
  active: [
    { action: "pause", label: "Pause" },
    { action: "end", label: "End event" },
  ],
  paused: [{ action: "resume", label: "Resume" }],
};

const CANCELLABLE = new Set(["draft", "registration", "active", "paused"]);

/** Lifecycle transitions for an owned event (CTF-007): forward actions plus cancel. */
export function EventLifecycleCard({ event }: Readonly<{ event: CtfEventDetail }>) {
  const lifecycle = useCtfEventLifecycle(event.id);
  const [confirmingCancel, setConfirmingCancel] = useState(false);
  const actions = ACTIONS_BY_STATUS[event.status] ?? [];
  const errorMessage = describeMutationError(lifecycle.error, "That transition was refused.");

  if (!actions.length && !CANCELLABLE.has(event.status)) return null;
  return (
    <Card>
      <CardContent className="space-y-3">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold">Lifecycle</h2>
          <Badge variant="secondary">{titleCase(event.status)}</Badge>
        </div>
        <div className="flex flex-wrap gap-2">
          {actions.map(({ action, label }) => (
            <Button
              key={action}
              type="button"
              variant="outline"
              disabled={lifecycle.isPending}
              onClick={() => lifecycle.mutate(action)}
            >
              {label}
            </Button>
          ))}
          {CANCELLABLE.has(event.status) ? (
            <Button
              type="button"
              variant="destructive"
              disabled={lifecycle.isPending}
              onClick={() => setConfirmingCancel(true)}
            >
              Cancel event
            </Button>
          ) : null}
        </div>
        {lifecycle.error ? <p className="text-xs text-destructive">{errorMessage}</p> : null}

        <ConfirmDialog
          open={confirmingCancel}
          title="Cancel this event?"
          confirmLabel="Cancel event"
          destructive
          pending={lifecycle.isPending}
          error={lifecycle.error}
          onOpenChange={(open) => {
            if (!open) {
              lifecycle.reset();
              setConfirmingCancel(false);
            }
          }}
          onConfirm={() =>
            lifecycle.mutate("cancel", {
              onSuccess: () => setConfirmingCancel(false),
            })
          }
        >
          Participants are notified, all provisioned ranges are destroyed, and no further submissions are
          possible. This cannot be undone.
        </ConfirmDialog>
      </CardContent>
    </Card>
  );
}
