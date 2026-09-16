/** Workspace member invitation administration (#1942, PLAT-235). */
import { useState } from "react";
import { useParams } from "react-router";

import { ApiError, describeMutationError } from "@/api/errors";
import {
  useIssueWorkspaceInvitation,
  useResendWorkspaceInvitation,
  useRevokeWorkspaceInvitation,
  useWorkspaceInvitations,
} from "@/api/invitations";
import type { WorkspaceInvitation, WorkspaceRole } from "@/api/types";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import { formatTimestamp } from "../format";
import { useWorkspaceContext } from "./WorkspaceContext";

const ROLE_OPTIONS: readonly { value: WorkspaceRole; label: string }[] = [
  { value: "owner", label: "Owner" },
  { value: "admin", label: "Admin" },
  { value: "member", label: "Member" },
];

export function WorkspaceInvitationsPage() {
  const { workspaceUuid = "" } = useParams();
  const { selected } = useWorkspaceContext();
  const capabilities = selected?.capabilities ?? [];
  const canRead = capabilities.includes("read_invitations");
  const canIssue = capabilities.includes("issue_invitation");
  const invitations = useWorkspaceInvitations(workspaceUuid, canRead);

  if (!canRead) {
    return (
      <Alert variant="destructive" className="max-w-xl">
        <AlertTitle>Invitations are not available</AlertTitle>
        <AlertDescription>Your role in this workspace does not permit invitation administration.</AlertDescription>
      </Alert>
    );
  }
  if (invitations.isLoading) {
    return <Skeleton className="h-40 w-full max-w-4xl" />;
  }
  if (invitations.isError || !invitations.data) {
    const forbidden = invitations.error instanceof ApiError && invitations.error.status === 403;
    return (
      <Alert variant="destructive" className="max-w-xl">
        <AlertTitle>{forbidden ? "You do not have permission to view invitations" : "Could not load invitations"}</AlertTitle>
        <AlertDescription>Please retry. If the problem persists, contact an administrator.</AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Invitations"
        description={`Invite people to ${selected?.workspace_name ?? "this workspace"}`}
        actions={canIssue ? <IssueInvitationDialog uuid={workspaceUuid} /> : undefined}
      />
      <Card className="overflow-hidden py-0" aria-busy={invitations.isFetching}>
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Email</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Expires</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {invitations.data.length === 0 ? (
              <TableRow><TableCell colSpan={5} className="text-center text-muted-foreground">No invitations yet.</TableCell></TableRow>
            ) : invitations.data.map((invitation) => (
              <InvitationRow key={invitation.invitation_uuid} uuid={workspaceUuid} invitation={invitation} capabilities={capabilities} />
            ))}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}

function InvitationRow({ uuid, invitation, capabilities }: Readonly<{
  uuid: string;
  invitation: WorkspaceInvitation;
  capabilities: readonly string[];
}>) {
  const resend = useResendWorkspaceInvitation(uuid);
  const revoke = useRevokeWorkspaceInvitation(uuid);
  const [confirming, setConfirming] = useState(false);
  const current = invitation.status === "pending" || invitation.status === "expired";
  const error = describeMutationError(resend.error ?? revoke.error, "The invitation could not be updated.");
  return (
    <TableRow>
      <TableCell className="font-medium">{invitation.email}</TableCell>
      <TableCell>{ROLE_OPTIONS.find((item) => item.value === invitation.role)?.label ?? invitation.role}</TableCell>
      <TableCell><Badge variant="outline">{invitation.status}</Badge></TableCell>
      <TableCell className="text-sm text-muted-foreground">{formatTimestamp(invitation.expires_at)}</TableCell>
      <TableCell className="text-right">
        {current && capabilities.includes("resend_invitation") ? (
          <Button variant="ghost" size="sm" disabled={resend.isPending} onClick={() => resend.mutate(invitation.invitation_uuid)}>
            Resend
          </Button>
        ) : null}
        {current && capabilities.includes("revoke_invitation") ? (
          <Button variant="ghost" size="sm" className="text-destructive" onClick={() => setConfirming(true)}>Revoke</Button>
        ) : null}
        {error ? <p className="text-sm text-destructive">{error}</p> : null}
        <ConfirmDialog
          open={confirming}
          title={`Revoke invitation for ${invitation.email}?`}
          confirmLabel="Revoke"
          destructive
          pending={revoke.isPending}
          error={revoke.error}
          onOpenChange={setConfirming}
          onConfirm={() => revoke.mutate(invitation.invitation_uuid, { onSuccess: () => setConfirming(false) })}
        >
          The current invitation link will stop working immediately.
        </ConfirmDialog>
      </TableCell>
    </TableRow>
  );
}

function IssueInvitationDialog({ uuid }: Readonly<{ uuid: string }>) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<WorkspaceRole>("member");
  const mutation = useIssueWorkspaceInvitation(uuid);
  const fields = mutation.error instanceof ApiError ? mutation.error.fieldErrors() : {};
  const error = Object.keys(fields).length ? null : describeMutationError(mutation.error, "The invitation could not be sent.");

  function close(next: boolean) {
    setOpen(next);
    if (!next) {
      setEmail("");
      setRole("member");
      mutation.reset();
    }
  }
  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogTrigger asChild><Button size="sm">Invite member</Button></DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Invite member</DialogTitle>
          <DialogDescription>Send a time-limited invitation. The recipient signs in with this email to accept.</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" aria-label="Invite member" onSubmit={(event) => {
          event.preventDefault();
          mutation.mutate({ email: email.trim(), role }, { onSuccess: () => close(false) });
        }}>
          <div className="flex flex-col gap-2">
            <Label htmlFor="invitation-email">Email</Label>
            <Input id="invitation-email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} />
            {fields.email?.length ? <p className="text-sm text-destructive">{fields.email.join(" ")}</p> : null}
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="invitation-role">Role</Label>
            <Select value={role} onValueChange={(value) => setRole(value as WorkspaceRole)}>
              <SelectTrigger id="invitation-role" aria-label="Role"><SelectValue /></SelectTrigger>
              <SelectContent>{ROLE_OPTIONS.map((item) => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
          <DialogFooter><Button type="submit" disabled={!email.trim() || mutation.isPending}>{mutation.isPending ? "Sending…" : "Send invitation"}</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
