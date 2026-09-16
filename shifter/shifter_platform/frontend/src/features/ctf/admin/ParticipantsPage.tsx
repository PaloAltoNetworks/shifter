import { useState } from "react";
import { Link, useParams } from "react-router";

import { UserPlus } from "lucide-react";

import {
  useAddCtfParticipant,
  useCtfParticipants,
  useCtfPublicRegistrationRequests,
  useDispositionCtfPublicRegistrationRequest,
} from "@/api/ctfAdmin";
import { describeMutationError } from "@/api/errors";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

import { ParticipantImportDialog } from "./ParticipantImportDialog";
import { ParticipantPasswordDialog } from "./ParticipantPasswordDialog";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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

import { formatDateTime, titleCase } from "../format";
import { ctfAdminEventPath, ctfAdminEventsPath, ctfAdminParticipantPath } from "../routes";

function InviteDialog({ eventId, open, onOpenChange }: Readonly<{ eventId: string; open: boolean; onOpenChange: (open: boolean) => void }>) {
  const invite = useAddCtfParticipant(eventId);
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
              <ParticipantPasswordDialog participantId={participant.id} participantName={participant.name} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function RegistrationRequestsCard({ eventId }: Readonly<{ eventId: string }>) {
  const query = useCtfPublicRegistrationRequests(eventId);
  const disposition = useDispositionCtfPublicRegistrationRequest(eventId);
  const requests = query.data?.requests ?? [];

  if (!query.isLoading && !query.isError && requests.length === 0) return null;

  return (
    <Card aria-busy={query.isFetching}>
      <CardHeader>
        <CardTitle className="text-base">Pending public registration requests</CardTitle>
      </CardHeader>
      <CardContent>
        {query.isLoading ? <Skeleton className="h-16 w-full" /> : null}
        {query.isError ? (
          <Alert variant="destructive">
            <AlertDescription>Could not load public registration requests.</AlertDescription>
          </Alert>
        ) : null}
        {disposition.error ? (
          <Alert variant="destructive" className="mb-3">
            <AlertDescription>
              {describeMutationError(disposition.error, "Could not review the registration request.")}
            </AlertDescription>
          </Alert>
        ) : null}
        {requests.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Name</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>Submitted</TableHead>
                <TableHead className="text-right">Review</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {requests.map((registration) => (
                <TableRow key={registration.id}>
                  <TableCell className="font-medium">{registration.name}</TableCell>
                  <TableCell className="text-sm text-muted-foreground">{registration.email}</TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {formatDateTime(registration.created_at)}
                  </TableCell>
                  <TableCell className="space-x-2 text-right">
                    <Button
                      size="sm"
                      disabled={disposition.isPending}
                      aria-label={`Approve ${registration.name}`}
                      onClick={() => disposition.mutate({ requestId: registration.id, action: "approve" })}
                    >
                      Approve
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={disposition.isPending}
                      aria-label={`Reject ${registration.name}`}
                      onClick={() => disposition.mutate({ requestId: registration.id, action: "reject" })}
                    >
                      Reject
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : null}
      </CardContent>
    </Card>
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
      <div className="space-y-6">
        <RegistrationRequestsCard eventId={eventId} />
        <Card className="overflow-hidden py-0" aria-busy={query.isFetching}>
          <ParticipantsBody query={query} />
        </Card>
      </div>

      <InviteDialog eventId={eventId} open={inviting} onOpenChange={setInviting} />
    </>
  );
}
