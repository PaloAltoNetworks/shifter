/**
 * Managed-content revision card (#1971).
 *
 * Shows the event's current digest-pinned content revision and drift state, and
 * lets the organizer reconcile the event to the currently configured revision
 * of its scenario without tearing it down. On a live event only titles and
 * flags change; scoring and structure are never altered by refresh.
 */
import { useState } from "react";

import { useRefreshCtfEventContent } from "@/api/ctfAdmin";
import type { CtfEventDetail } from "@/api/types";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

import { titleCase } from "../format";

export function EventContentCard({ event }: Readonly<{ event: CtfEventDetail }>) {
  const managed = event.managed_content;
  const refresh = useRefreshCtfEventContent(event.id);
  const [confirming, setConfirming] = useState(false);
  const [outcome, setOutcome] = useState<string | null>(null);

  if (!managed) {
    return null;
  }

  const shortDigest = managed.declared_digest.replace(/^sha256:/, "").slice(0, 12);

  return (
    <Card>
      <CardContent>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="space-y-1">
            <h2 className="text-sm font-semibold">Managed content</h2>
            <p className="text-sm text-muted-foreground">
              Revision <code>{shortDigest}…</code>{" "}
              <Badge variant={managed.state === "pristine" ? "secondary" : "destructive"}>
                {titleCase(managed.state)}
              </Badge>
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            disabled={!managed.is_refreshable || refresh.isPending}
            onClick={() => setConfirming(true)}
          >
            Refresh to configured revision
          </Button>
        </div>
        {outcome ? (
          <Alert className="mt-3">
            <AlertTitle>Content {outcome}</AlertTitle>
            <AlertDescription>The event now matches the configured content revision.</AlertDescription>
          </Alert>
        ) : null}
      </CardContent>

      <ConfirmDialog
        open={confirming}
        title="Refresh event content?"
        confirmLabel="Refresh"
        pending={refresh.isPending}
        error={refresh.error}
        onOpenChange={(open) => {
          if (!open) {
            refresh.reset();
            setConfirming(false);
          }
        }}
        onConfirm={() =>
          refresh.mutate(managed.declared_digest, {
            onSuccess: (result) => {
              setOutcome(result.outcome);
              setConfirming(false);
            },
          })
        }
      >
        This reconciles the event to the configured content revision. On a live event only challenge titles and flags
        change; scoring, hints, and structure are never altered.
      </ConfirmDialog>
    </Card>
  );
}
