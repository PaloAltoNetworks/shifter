import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { UserPlus } from "lucide-react";

import { useCtfParticipants, useInviteCtfParticipant, useResendCtfInvite } from "@/api/ctfAdmin";
import { describeMutationError } from "@/api/errors";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

import { ParticipantImportDialog } from "./ParticipantImportDialog";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import { titleCase } from "../format";
import { ctfAdminEventPath, ctfAdminEventsPath, ctfAdminParticipantPath } from "../routes";

function InviteDialog({ eventId, open, onOpenChange }: Readonly<{ eventId: string; open: boolean; onOpenChange: (open: boolean) => void }>) {
  const invite = useInviteCtfParticipant(eventId);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const error = describeMutationError(invite.error, "Could not invite the participant.");

  function reset() {
    invite.reset();
    setName("");
    setEmail("");
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Invite participant</DialogTitle>
          <DialogDescription>Adds a participant to this event and sends them an invitation.</DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (!name.trim() || !email.trim()) return;
            invite.mutate(
              { name: name.trim(), email: email.trim() },
              {
                onSuccess: () => {
                  reset();
                  onOpenChange(false);
                },
              },
            );
          }}
        >
          <div className="flex flex-col gap-2">
            <Label htmlFor="invite-name">Name</Label>
            <Input id="invite-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="invite-email">Email</Label>
            <Input id="invite-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          {error ? (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)} disabled={invite.isPending}>
              Cancel
            </Button>
            <Button type="submit" disabled={invite.isPending || !name.trim() || !email.trim()}>
              Invite
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ResendButton({ participantId }: Readonly<{ participantId: string }>) {
  const resend = useResendCtfInvite(participantId);
  return (
    <Button variant="ghost" size="sm" disabled={resend.isPending} onClick={() => resend.mutate()}>
      {resend.isSuccess ? "Sent" : "Resend"}
    </Button>
  );
}

function ParticipantsBody({ query }: Readonly<{ query: ReturnType<typeof useCtfParticipants> }>) {
  if (query.isLoading) {
    return (
      <div className="space-y-3 p-4">
        {[0, 1, 2, 3].map((row) => (
          <Skeleton key={row} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  if (query.isError) {
    return (
      <div className="p-4">
        <Alert variant="destructive">
          <AlertTitle>Could not load participants</AlertTitle>
          <AlertDescription>Please retry.</AlertDescription>
        </Alert>
      </div>
    );
  }

  const participants = query.data?.participants ?? [];
  if (participants.length === 0) {
    return (
      <div className="grid place-items-center px-6 py-16 text-center">
        <p className="text-sm font-medium">No participants yet</p>
        <p className="mt-1 text-sm text-muted-foreground">Invite or import participants to this event.</p>
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead>Name</TableHead>
          <TableHead>Email</TableHead>
          <TableHead className="w-[130px]">Status</TableHead>
          <TableHead className="w-[80px] text-right">Score</TableHead>
          <TableHead className="w-[110px] text-right">Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {participants.map((participant) => (
          <TableRow key={participant.id}>
            <TableCell className="font-medium">
              <Link className="hover:underline" to={ctfAdminParticipantPath(participant.id)}>
                {participant.name}
              </Link>
            </TableCell>
            <TableCell className="text-sm text-muted-foreground">{participant.email}</TableCell>
            <TableCell>
              <Badge variant="secondary">{titleCase(participant.status)}</Badge>
            </TableCell>
            <TableCell className="text-right font-mono text-sm tabular-nums">{participant.total_score}</TableCell>
            <TableCell className="text-right">
              <ResendButton participantId={participant.id} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export function ParticipantsPage() {
  const params = useParams();
  const eventId = params.eventId ?? "";
  const query = useCtfParticipants(eventId);
  const [inviting, setInviting] = useState(false);
  const total = query.data?.total ?? query.data?.participants.length ?? 0;
  const totalNoun = total === 1 ? "participant" : "participants";
  const description = query.data ? `${total} ${totalNoun}` : "Event participants";
  // Import owns a Django POST form and stays server-rendered; link out to it.

  return (
    <>
      <nav className="mb-3 text-sm text-muted-foreground" aria-label="Breadcrumb">
        <Link className="hover:text-foreground" to={ctfAdminEventsPath()}>
          Events
        </Link>
        <span className="px-1.5">/</span>
        <Link className="hover:text-foreground" to={ctfAdminEventPath(eventId)}>
          Event
        </Link>
        <span className="px-1.5">/</span>
        <span className="text-foreground">Participants</span>
      </nav>

      <PageHeader
        title="Participants"
        description={description}
        actions={
          <div className="flex items-center gap-2">
            <ParticipantImportDialog eventId={eventId} />
            <Button size="sm" onClick={() => setInviting(true)}>
              <UserPlus className="size-4" />
              Invite
            </Button>
          </div>
        }
      />
      <Card className="overflow-hidden py-0" aria-busy={query.isFetching}>
        <ParticipantsBody query={query} />
      </Card>

      <InviteDialog eventId={eventId} open={inviting} onOpenChange={setInviting} />
    </>
  );
}
