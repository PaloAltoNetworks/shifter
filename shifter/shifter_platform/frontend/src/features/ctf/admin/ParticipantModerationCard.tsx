import { useState } from "react";

import {
  useBanCtfParticipant,
  useDisqualifyCtfParticipant,
  useRenameCtfParticipant,
  useRequalifyCtfParticipant,
  useSetCtfParticipantHidden,
  useSetCtfParticipantRole,
  useUnbanCtfParticipant,
} from "@/api/ctfAdmin";
import { describeMutationError } from "@/api/errors";
import type { CtfOrganizerParticipantDetail } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

function ActionError({ errors }: Readonly<{ errors: unknown[] }>) {
  const first = errors.find(Boolean);
  const message = first ? describeMutationError(first, "That did not work. Try again.") : null;
  if (!message) return null;
  return <p className="mt-2 text-xs text-destructive">{message}</p>;
}

/** Standing controls: ban/unban and disqualify/requalify with a shared reason (CTF-605/609). */
function StandingControls({ participant }: Readonly<{ participant: CtfOrganizerParticipantDetail }>) {
  const ban = useBanCtfParticipant(participant.id);
  const unban = useUnbanCtfParticipant(participant.id);
  const disqualify = useDisqualifyCtfParticipant(participant.id);
  const requalify = useRequalifyCtfParticipant(participant.id);
  const [reason, setReason] = useState("");
  const busy = ban.isPending || unban.isPending || disqualify.isPending || requalify.isPending;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex min-w-64 flex-col gap-1">
        <Label htmlFor="moderation-reason">Reason (recorded)</Label>
        <Input
          id="moderation-reason"
          value={reason}
          placeholder="Why this action is being taken"
          onChange={(event) => setReason(event.target.value)}
        />
      </div>
      <div className="flex flex-wrap gap-2">
        {participant.status === "banned" ? (
          <Button type="button" variant="outline" disabled={busy} onClick={() => unban.mutate({})}>
            Lift ban
          </Button>
        ) : (
          <Button
            type="button"
            variant="destructive"
            disabled={busy}
            onClick={() => ban.mutate({ reason: reason.trim() || undefined })}
          >
            Ban
          </Button>
        )}
        {participant.status === "disqualified" ? (
          <Button type="button" variant="outline" disabled={busy} onClick={() => requalify.mutate({})}>
            Requalify
          </Button>
        ) : (
          <Button
            type="button"
            variant="destructive"
            disabled={busy || participant.status === "banned"}
            onClick={() => disqualify.mutate({ reason: reason.trim() || undefined })}
          >
            Disqualify
          </Button>
        )}
      </div>
      {participant.status_reason ? (
        <p className="text-xs text-muted-foreground">Recorded reason: {participant.status_reason}</p>
      ) : null}
      <ActionError errors={[ban.error, unban.error, disqualify.error, requalify.error]} />
    </div>
  );
}

/** Role + ranking-visibility toggles (CTF-604/606). */
function VisibilityControls({ participant }: Readonly<{ participant: CtfOrganizerParticipantDetail }>) {
  const setRole = useSetCtfParticipantRole(participant.id);
  const setHidden = useSetCtfParticipantHidden(participant.id);

  return (
    <div className="flex flex-wrap gap-2">
      {participant.role === "observer" ? (
        <Button type="button" variant="outline" disabled={setRole.isPending} onClick={() => setRole.mutate({ role: "player" })}>
          Make player
        </Button>
      ) : (
        <Button type="button" variant="outline" disabled={setRole.isPending} onClick={() => setRole.mutate({ role: "observer" })}>
          Make observer
        </Button>
      )}
      <Button
        type="button"
        variant="outline"
        disabled={setHidden.isPending}
        onClick={() => setHidden.mutate({ hidden: !participant.hidden })}
      >
        {participant.hidden ? "Show on scoreboard" : "Hide from scoreboard"}
      </Button>
      <ActionError errors={[setRole.error, setHidden.error]} />
    </div>
  );
}

/** Login-handle rename for isolated CTF accounts (#1206). */
function RenameControl({ participant }: Readonly<{ participant: CtfOrganizerParticipantDetail }>) {
  const rename = useRenameCtfParticipant(participant.id);
  const [username, setUsername] = useState(participant.username ?? "");

  if (!participant.username) return null;
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        if (username.trim() && username.trim() !== participant.username) {
          rename.mutate({ username: username.trim() });
        }
      }}
    >
      <div className="flex min-w-56 flex-1 flex-col gap-1">
        <Label htmlFor="moderation-username">Login username</Label>
        <Input id="moderation-username" value={username} onChange={(event) => setUsername(event.target.value)} />
      </div>
      <Button
        type="submit"
        variant="outline"
        disabled={!username.trim() || username.trim() === participant.username || rename.isPending}
      >
        Rename
      </Button>
      <ActionError errors={[rename.error]} />
    </form>
  );
}

export function ParticipantModerationCard({
  participant,
}: Readonly<{ participant: CtfOrganizerParticipantDetail }>) {
  return (
    <Card>
      <CardContent className="space-y-5">
        <div>
          <h2 className="text-sm font-semibold">Moderation</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Banning blocks all event access; disqualification removes scoring but keeps view access. Observers
            watch without competing; hidden participants play without ranking. All actions are reversible.
          </p>
        </div>
        <StandingControls participant={participant} />
        <VisibilityControls participant={participant} />
        <RenameControl participant={participant} />
      </CardContent>
    </Card>
  );
}
