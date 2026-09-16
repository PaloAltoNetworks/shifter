/**
 * Workspace membership & roles administration surface (#1941, PLAT-234).
 * Rendered at `workspaces/:workspaceUuid/membership` inside the workspace-scoped
 * console layout.
 *
 * Authority lives on the server: the `/api/v1/workspaces/{uuid}/memberships/*`
 * endpoints authorize the caller's workspace role and are the `shared.audit`
 * boundary. This surface consumes the selected workspace's server-derived
 * `PrincipalWorkspaceContext.capabilities` for presentation only and posts the
 * actions; it never compares the closed `owner`/`admin`/`member` role codes to
 * reconstruct policy. Owner/admin (with `read_members`) see the roster and the
 * actions their advertised capabilities permit; a member sees an honest
 * self-service state and can leave. The last-owner rule is shown from roster
 * state as an affordance, but the server stays authoritative — a concurrent
 * change can still return `409 last_owner_required` between render and submit.
 */
import { useState } from "react";
import { useParams } from "react-router";

import {
  useAddWorkspaceMember,
  useChangeWorkspaceMemberRole,
  useLeaveWorkspace,
  useRemoveWorkspaceMember,
  useSelfMembership,
  useWorkspaceMemberships,
} from "@/api/memberships";
import { ApiError, describeMutationError } from "@/api/errors";
import type { PrincipalWorkspaceContext, WorkspaceMembership, WorkspaceRole } from "@/api/types";
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

/** The closed workspace role vocabulary, rendered as display data / request values only. */
const ROLE_OPTIONS: readonly { value: WorkspaceRole; label: string }[] = [
  { value: "owner", label: "Owner" },
  { value: "admin", label: "Admin" },
  { value: "member", label: "Member" },
];

function roleLabel(role: string): string {
  return ROLE_OPTIONS.find((option) => option.value === role)?.label ?? role;
}

export function WorkspaceMembershipPage() {
  const { workspaceUuid } = useParams();
  const uuid = workspaceUuid ?? "";
  const { selected } = useWorkspaceContext();
  const capabilities = selected?.capabilities ?? [];

  // The nav predicate admits either roster access or self-service leave; render
  // the matching mode. Both signals are server-advertised capabilities, never a
  // role-string shortcut.
  if (selected && capabilities.includes("read_members")) {
    return <MembershipRoster uuid={uuid} workspaceName={selected.workspace_name} capabilities={capabilities} />;
  }
  if (selected && capabilities.includes("leave_workspace")) {
    return <SelfServiceMembership uuid={uuid} selected={selected} />;
  }
  return (
    <Alert variant="destructive" className="max-w-xl">
      <AlertTitle>Membership is not available</AlertTitle>
      <AlertDescription>Your role in this workspace does not permit membership administration.</AlertDescription>
    </Alert>
  );
}

function MembershipRoster({
  uuid,
  workspaceName,
  capabilities,
}: Readonly<{ uuid: string; workspaceName: string; capabilities: readonly string[] }>) {
  const roster = useWorkspaceMemberships(uuid);
  const self = useSelfMembership(uuid);
  const description = `Manage who can access ${workspaceName} and their roles`;

  // Identity-dependent actions (Leave vs Remove on the caller's own row, and the
  // self-role-change principal-context invalidation in useChangeWorkspaceMemberRole)
  // need the caller's own membership. Do not render the roster until BOTH the
  // roster and self resolve, so a slow or failed self request can never mistake
  // the caller's own row for another member's and take the wrong command path.
  if (roster.isLoading || self.isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader title="Membership" description={description} />
        <Skeleton className="h-40 w-full max-w-3xl" />
      </div>
    );
  }

  if (roster.isError || !roster.data) {
    const forbidden = roster.error instanceof ApiError && roster.error.status === 403;
    return (
      <div className="space-y-6">
        <PageHeader title="Membership" description={description} />
        <Alert variant="destructive" className="max-w-xl">
          <AlertTitle>
            {forbidden ? "You do not have permission to view the membership roster" : "Could not load the membership roster"}
          </AlertTitle>
          <AlertDescription>Please retry. If the problem persists, contact an administrator.</AlertDescription>
        </Alert>
      </div>
    );
  }

  if (self.isError || !self.data) {
    return (
      <div className="space-y-6">
        <PageHeader title="Membership" description={description} />
        <Alert variant="destructive" className="max-w-xl">
          <AlertTitle>Could not confirm your membership</AlertTitle>
          <AlertDescription>
            Membership actions are unavailable until your own membership loads. Please retry. If the problem persists, contact
            an administrator.
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  const members = roster.data;
  const selfUserId = self.data.user_id;
  const ownerCount = members.filter((member) => member.role === "owner").length;
  const canAdd = capabilities.includes("add_member");
  const canChangeRole = capabilities.includes("change_member_role");
  const canRemove = capabilities.includes("remove_member");
  const canLeave = capabilities.includes("leave_workspace");

  return (
    <div className="space-y-6">
      <PageHeader title="Membership" description={description} actions={canAdd ? <AddMemberDialog uuid={uuid} /> : undefined} />
      {ownerCount === 1 ? (
        <Alert className="max-w-3xl">
          <AlertTitle>This workspace has a single owner</AlertTitle>
          <AlertDescription>
            The last owner cannot be removed, demoted, or leave. Add or promote another owner (or transfer ownership from the
            workspace overview) first.
          </AlertDescription>
        </Alert>
      ) : null}
      <Card className="overflow-hidden py-0" aria-busy={roster.isFetching}>
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Member</TableHead>
              <TableHead className="w-[170px]">Role</TableHead>
              <TableHead className="w-[200px]">Joined</TableHead>
              <TableHead className="w-[140px] text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {members.map((member) => {
              const isSelf = member.user_id === selfUserId;
              const isLastOwner = member.role === "owner" && ownerCount === 1;
              return (
                <TableRow key={member.user_id}>
                  <TableCell className="font-medium">{member.display_name}</TableCell>
                  <TableCell>
                    <RoleCell uuid={uuid} member={member} editable={canChangeRole && !isLastOwner} selfUserId={selfUserId} />
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">{formatTimestamp(member.created_at)}</TableCell>
                  <TableCell className="text-right">
                    <MemberRowActions
                      uuid={uuid}
                      member={member}
                      isSelf={isSelf}
                      isLastOwner={isLastOwner}
                      canRemove={canRemove}
                      canLeave={canLeave}
                    />
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}

/**
 * Per-row action for a roster member: the caller's own row offers Leave (self
 * removal must use the leave endpoint), every other row offers Remove. Each is
 * gated on the matching advertised capability.
 */
function MemberRowActions({
  uuid,
  member,
  isSelf,
  isLastOwner,
  canRemove,
  canLeave,
}: Readonly<{
  uuid: string;
  member: WorkspaceMembership;
  isSelf: boolean;
  isLastOwner: boolean;
  canRemove: boolean;
  canLeave: boolean;
}>) {
  if (isSelf) {
    return canLeave ? <LeaveAction uuid={uuid} disabled={isLastOwner} /> : null;
  }
  return canRemove ? <RemoveAction uuid={uuid} member={member} disabled={isLastOwner} /> : null;
}

/** Inline role control: an editable Select when permitted, otherwise a static badge. */
function RoleCell({
  uuid,
  member,
  editable,
  selfUserId,
}: Readonly<{ uuid: string; member: WorkspaceMembership; editable: boolean; selfUserId: number }>) {
  const mutation = useChangeWorkspaceMemberRole(uuid, selfUserId);

  if (!editable) {
    return <Badge variant="outline">{roleLabel(member.role)}</Badge>;
  }

  const error = describeMutationError(mutation.error, "The role could not be changed.");

  return (
    <div className="flex flex-col gap-1">
      <Select
        value={member.role}
        onValueChange={(role) => mutation.mutate({ userId: member.user_id, role: role as WorkspaceRole })}
      >
        <SelectTrigger size="sm" className="w-[130px]" aria-label={`Role for ${member.display_name}`} disabled={mutation.isPending}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {ROLE_OPTIONS.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {error ? <p className="text-sm text-destructive">{error}</p> : null}
    </div>
  );
}

/** Remove another member, confirmed first. Disabled for the sole owner. */
function RemoveAction({
  uuid,
  member,
  disabled,
}: Readonly<{ uuid: string; member: WorkspaceMembership; disabled: boolean }>) {
  const [open, setOpen] = useState(false);
  const mutation = useRemoveWorkspaceMember(uuid);

  function onConfirm() {
    mutation.mutate(member.user_id, { onSuccess: () => setOpen(false) });
  }

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        className="text-destructive"
        disabled={disabled}
        title={disabled ? "The last owner cannot be removed. Add or promote another owner first." : undefined}
        onClick={() => setOpen(true)}
      >
        Remove
      </Button>
      <ConfirmDialog
        open={open}
        title={`Remove ${member.display_name}?`}
        confirmLabel="Remove"
        destructive
        pending={mutation.isPending}
        error={mutation.error}
        onConfirm={onConfirm}
        onOpenChange={setOpen}
      >
        {member.display_name} will lose access to this workspace. This does not delete their account.
      </ConfirmDialog>
    </>
  );
}

/** Leave the workspace (self-removal). Disabled when the caller is the sole owner. */
function LeaveAction({ uuid, disabled }: Readonly<{ uuid: string; disabled: boolean }>) {
  const [open, setOpen] = useState(false);
  const mutation = useLeaveWorkspace(uuid);

  function onConfirm() {
    mutation.mutate(undefined, { onSuccess: () => setOpen(false) });
  }

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        disabled={disabled}
        title={disabled ? "The last owner cannot leave. Transfer ownership first." : undefined}
        onClick={() => setOpen(true)}
      >
        Leave
      </Button>
      <ConfirmDialog
        open={open}
        title="Leave this workspace?"
        confirmLabel="Leave"
        destructive
        pending={mutation.isPending}
        error={mutation.error}
        onConfirm={onConfirm}
        onOpenChange={setOpen}
      >
        You will lose access to this workspace. An owner or admin can add you back later.
      </ConfirmDialog>
    </>
  );
}

/** Add an existing active account to the workspace by email and role. */
function AddMemberDialog({ uuid }: Readonly<{ uuid: string }>) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<WorkspaceRole>("member");
  const mutation = useAddWorkspaceMember(uuid);

  const fieldErrors = mutation.error instanceof ApiError ? mutation.error.fieldErrors() : {};
  const topLevelError =
    Object.keys(fieldErrors).length === 0 ? describeMutationError(mutation.error, "The member could not be added.") : null;

  function onOpenChange(next: boolean) {
    setOpen(next);
    if (!next) {
      setEmail("");
      setRole("member");
      mutation.reset();
    }
  }

  function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    mutation.mutate({ email: email.trim(), role }, { onSuccess: () => onOpenChange(false) });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button size="sm">Add member</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add member</DialogTitle>
          <DialogDescription>Add an existing account to this workspace by email and assign a role.</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={onSubmit} aria-label="Add member">
          <div className="flex flex-col gap-2">
            <Label htmlFor="add-member-email">Email</Label>
            <Input
              id="add-member-email"
              type="email"
              value={email}
              aria-invalid={fieldErrors.email ? true : undefined}
              onChange={(event) => setEmail(event.target.value)}
            />
            {fieldErrors.email?.length ? <p className="text-sm text-destructive">{fieldErrors.email.join(" ")}</p> : null}
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="add-member-role">Role</Label>
            <Select value={role} onValueChange={(value) => setRole(value as WorkspaceRole)}>
              <SelectTrigger id="add-member-role" className="w-[180px]" aria-label="Role">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ROLE_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {fieldErrors.role?.length ? <p className="text-sm text-destructive">{fieldErrors.role.join(" ")}</p> : null}
          </div>

          {topLevelError ? (
            <Alert variant="destructive">
              <AlertDescription>{topLevelError}</AlertDescription>
            </Alert>
          ) : null}

          <DialogFooter>
            <Button type="submit" disabled={mutation.isPending || email.trim().length === 0}>
              {mutation.isPending ? "Adding…" : "Add member"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Self-service state for a member who cannot read the roster but can leave. */
function SelfServiceMembership({
  uuid,
  selected,
}: Readonly<{ uuid: string; selected: PrincipalWorkspaceContext }>) {
  return (
    <div className="space-y-6">
      <PageHeader title="Membership" description={`Your membership in ${selected.workspace_name}`} />
      <Card className="max-w-2xl space-y-4 p-6">
        <h2 className="text-sm font-medium">Your membership</h2>
        <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
          <div className="flex flex-col gap-1">
            <dt className="text-muted-foreground">Workspace</dt>
            <dd className="font-medium">{selected.workspace_name}</dd>
          </div>
          <div className="flex flex-col gap-1">
            <dt className="text-muted-foreground">Your role</dt>
            <dd>
              <Badge variant="outline">{roleLabel(selected.role)}</Badge>
            </dd>
          </div>
        </dl>
        <p className="text-sm text-muted-foreground">
          Only workspace owners and admins can view the full membership roster. You can leave this workspace below.
        </p>
        <div>
          <LeaveAction uuid={uuid} disabled={false} />
        </div>
      </Card>
    </div>
  );
}
