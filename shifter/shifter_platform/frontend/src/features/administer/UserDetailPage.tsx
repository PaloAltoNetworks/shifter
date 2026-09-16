import { useState } from "react";
import { Link, useParams } from "react-router";

import type { ReactNode } from "react";

import {
  useAccountLifecycle,
  useAdminUser,
  useGrantOrganizer,
  useResetUserPassword,
  useSoftDeleteUser,
  useTransferOwnership,
} from "@/api/administer";
import { ApiError } from "@/api/errors";
import type { AccountLifecycleAction, AdminUserDetail, TransferOwnershipResult } from "@/api/types";
import { useBootstrapContext } from "@/app/bootstrap-context";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";

import { AccountLifecycleBadge, AccountOriginBadge, RoleBadge } from "./badges";
import { accountOriginLabel, formatTimestamp, titleCase } from "./format";
import { usersListPath } from "./routes";

type DialogKind = "activate" | "deactivate" | "suspend" | "reset-password" | "transfer" | "delete" | "grant-organizer";

function loadErrorTitle(error: unknown): string {
  if (error instanceof ApiError && error.status === 403) return "You do not have permission to view this user";
  if (error instanceof ApiError && error.status === 404) return "User not found";
  return "Could not load user";
}

function transferErrorMessage(error: unknown): string | null {
  if (error instanceof ApiError) return error.message;
  if (error) return "The transfer could not be completed.";
  return null;
}

export function UserDetailPage() {
  const params = useParams();
  const id = Number(params.id);
  const query = useAdminUser(id, Number.isFinite(id));

  if (query.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-9 w-64" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (query.isError || !query.data) {
    return (
      <div className="space-y-4">
        <PageHeader title="User" />
        <Alert variant="destructive">
          <AlertTitle>{loadErrorTitle(query.error)}</AlertTitle>
          <AlertDescription>
            <Link className="underline" to={usersListPath()}>
              Back to users
            </Link>
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  return <UserDetail user={query.data} />;
}

function UserDetail({ user }: Readonly<{ user: AdminUserDetail }>) {
  const bootstrap = useBootstrapContext();
  const [dialog, setDialog] = useState<DialogKind | null>(null);

  const lifecycle = useAccountLifecycle(user.id);
  const resetPassword = useResetUserPassword(user.id);
  const transfer = useTransferOwnership(user.id);
  const softDelete = useSoftDeleteUser(user.id);
  const grantOrganizer = useGrantOrganizer(user.id);

  function close() {
    lifecycle.reset();
    resetPassword.reset();
    transfer.reset();
    softDelete.reset();
    grantOrganizer.reset();
    setDialog(null);
  }

  return (
    <>
      <PageHeader
        title={user.display_name}
        description={user.email || user.username}
        actions={
          <UserActions
            user={user}
            canChange={bootstrap.permissions.can_change_users}
            canDelete={bootstrap.permissions.can_delete_users}
            onOpen={setDialog}
          />
        }
      />

      {user.is_deleted ? (
        <Alert className="mb-4">
          <AlertTitle>This account is deleted</AlertTitle>
          <AlertDescription>The account has been soft-deleted and can no longer sign in.</AlertDescription>
        </Alert>
      ) : null}

      <UserFields user={user} />

      <UserConfirmDialogs
        user={user}
        dialog={dialog}
        lifecycle={lifecycle}
        resetPassword={resetPassword}
        softDelete={softDelete}
        grantOrganizer={grantOrganizer}
        onClose={close}
        onDone={() => setDialog(null)}
      />
      <TransferOwnershipDialog
        open={dialog === "transfer"}
        transfer={transfer}
        onOpenChange={(open) => {
          if (!open) close();
        }}
      />
    </>
  );
}

function UserActions({
  user,
  canChange,
  canDelete,
  onOpen,
}: Readonly<{
  user: AdminUserDetail;
  canChange: boolean;
  canDelete: boolean;
  onOpen: (dialog: DialogKind) => void;
}>) {
  // Server-derived, authority-aware hints; the endpoints reauthorize. Change
  // actions are additionally gated on the caller's change permission.
  const actions = user.available_actions ?? [];
  const has = (action: string) => canChange && actions.includes(action);
  const activateLabel = user.lifecycle_state === "suspended" ? "Reinstate" : "Activate";
  return (
    <div className="flex flex-wrap items-center gap-2">
      {has("activate") ? (
        <Button variant="outline" size="sm" onClick={() => onOpen("activate")}>
          {activateLabel}
        </Button>
      ) : null}
      {has("deactivate") ? (
        <Button variant="outline" size="sm" onClick={() => onOpen("deactivate")}>
          Deactivate
        </Button>
      ) : null}
      {has("suspend") ? (
        <Button variant="outline" size="sm" onClick={() => onOpen("suspend")}>
          Suspend
        </Button>
      ) : null}
      {has("reset_password") ? (
        <Button variant="outline" size="sm" onClick={() => onOpen("reset-password")}>
          Reset password
        </Button>
      ) : null}
      {has("transfer_ownership") ? (
        <Button variant="outline" size="sm" onClick={() => onOpen("transfer")}>
          Transfer ownership
        </Button>
      ) : null}
      {canChange && !user.is_deleted && !user.is_ctf_organizer ? (
        <Button variant="outline" size="sm" onClick={() => onOpen("grant-organizer")}>
          Grant CTF Organizer
        </Button>
      ) : null}
      {canDelete && !user.is_deleted ? (
        <Button variant="destructive" size="sm" onClick={() => onOpen("delete")}>
          Delete
        </Button>
      ) : null}
    </div>
  );
}

function UserFields({ user }: Readonly<{ user: AdminUserDetail }>) {
  const hasRole = user.is_superuser || user.is_staff || user.is_ctf_organizer;
  return (
    <Card className="p-6">
      <dl className="grid grid-cols-1 gap-x-8 gap-y-4 sm:grid-cols-2">
        <Field label="Username">{user.username}</Field>
        <Field label="Email">{user.email || "—"}</Field>
        <Field label="Status">
          <AccountLifecycleBadge state={user.lifecycle_state} />
        </Field>
        <Field label="Account origin">
          <AccountOriginBadge origin={user.account_origin} />
        </Field>
        <Field label="Account type">{titleCase(user.user_type.replaceAll("_", " "))}</Field>
        <Field label="Roles">
          <div className="flex flex-wrap gap-1.5">
            {user.is_superuser ? <RoleBadge label="Superuser" /> : null}
            {user.is_staff ? <RoleBadge label="Staff" /> : null}
            {user.is_ctf_organizer ? <RoleBadge label="Organizer" /> : null}
            {hasRole ? null : <span className="text-sm text-muted-foreground">None</span>}
          </div>
        </Field>
        <Field label="Groups">
          {user.groups.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {user.groups.map((group) => (
                <RoleBadge key={group} label={group} />
              ))}
            </div>
          ) : (
            <span className="text-sm text-muted-foreground">None</span>
          )}
        </Field>
        {user.is_ctf_organizer ? (
          <Field label="Organizer grant source">
            {user.organizer_grant_source ? accountOriginLabel(user.organizer_grant_source) : "—"}
          </Field>
        ) : null}
        <Field label="Joined">{formatTimestamp(user.date_joined)}</Field>
        <Field label="Last login">{formatTimestamp(user.last_login)}</Field>
      </dl>
    </Card>
  );
}

function UserConfirmDialogs({
  user,
  dialog,
  lifecycle,
  resetPassword,
  softDelete,
  grantOrganizer,
  onClose,
  onDone,
}: Readonly<{
  user: AdminUserDetail;
  dialog: DialogKind | null;
  lifecycle: ReturnType<typeof useAccountLifecycle>;
  resetPassword: ReturnType<typeof useResetUserPassword>;
  softDelete: ReturnType<typeof useSoftDeleteUser>;
  grantOrganizer: ReturnType<typeof useGrantOrganizer>;
  onClose: () => void;
  onDone: () => void;
}>) {
  function runLifecycle(action: AccountLifecycleAction) {
    lifecycle.mutate(action, { onSuccess: onDone });
  }

  const activateLabel = user.lifecycle_state === "suspended" ? "Reinstate" : "Activate";
  const specs = [
    {
      kind: "activate",
      title: user.lifecycle_state === "suspended" ? "Reinstate account?" : "Activate account?",
      confirmLabel: activateLabel,
      destructive: false,
      pending: lifecycle.isPending,
      error: lifecycle.error,
      confirm: () => runLifecycle("activate"),
      body: "The user will be able to sign in again. This does not restore revoked API tokens.",
    },
    {
      kind: "deactivate",
      title: "Deactivate account?",
      confirmLabel: "Deactivate",
      destructive: true,
      pending: lifecycle.isPending,
      error: lifecycle.error,
      confirm: () => runLifecycle("deactivate"),
      body: "The user is signed out and blocked from signing in until reactivated. Assignments and owned resources are retained; live API tokens are revoked. This does not delete or anonymize the account.",
    },
    {
      kind: "suspend",
      title: "Suspend account?",
      confirmLabel: "Suspend",
      destructive: true,
      pending: lifecycle.isPending,
      error: lifecycle.error,
      confirm: () => runLifecycle("suspend"),
      body: "The user is signed out and blocked from signing in (a temporary security hold). Assignments and owned resources are retained; live API tokens are revoked. Reinstate to lift the suspension.",
    },
    {
      kind: "reset-password",
      title: "Send password reset?",
      confirmLabel: "Send reset email",
      destructive: false,
      pending: resetPassword.isPending,
      error: resetPassword.error,
      confirm: () => resetPassword.mutate(undefined, { onSuccess: onDone }),
      body: "Emails the user a link to set a new password using Django's standard reset flow. Available only for local accounts; provider accounts reset at their identity provider.",
    },
    {
      kind: "grant-organizer",
      title: "Grant CTF Organizer?",
      confirmLabel: "Grant",
      destructive: false,
      pending: grantOrganizer.isPending,
      error: grantOrganizer.error,
      confirm: () => grantOrganizer.mutate(undefined, { onSuccess: onDone }),
      body: "This adds the user to CTF Organizer as a local grant. It is additive and audited; provider-managed membership is unaffected. Removing organizer access is not available here.",
    },
    {
      kind: "delete",
      title: "Delete account?",
      confirmLabel: "Delete",
      destructive: true,
      pending: softDelete.isPending,
      error: softDelete.error,
      confirm: () => softDelete.mutate(undefined, { onSuccess: onDone }),
      body: "The account is soft-deleted and can no longer sign in; its live API tokens are revoked. This does not permanently erase, anonymize, or unbind the provider identity.",
    },
  ] as const;

  return (
    <>
      {specs.map((spec) => (
        <ConfirmDialog
          key={spec.kind}
          open={dialog === spec.kind}
          title={spec.title}
          confirmLabel={spec.confirmLabel}
          destructive={spec.destructive}
          pending={spec.pending}
          error={spec.error}
          onOpenChange={(open) => {
            if (!open) onClose();
          }}
          onConfirm={spec.confirm}
        >
          {spec.body}
        </ConfirmDialog>
      ))}
    </>
  );
}

function TransferOwnershipDialog({
  open,
  transfer,
  onOpenChange,
}: Readonly<{
  open: boolean;
  transfer: ReturnType<typeof useTransferOwnership>;
  onOpenChange: (open: boolean) => void;
}>) {
  const [replacementId, setReplacementId] = useState("");
  const [ranges, setRanges] = useState(true);
  const [workspaces, setWorkspaces] = useState(true);

  const parsedId = Number(replacementId);
  const validId = Number.isInteger(parsedId) && parsedId > 0;
  const kinds = [ranges ? "ranges" : null, workspaces ? "workspaces" : null].filter(Boolean) as (
    | "ranges"
    | "workspaces"
  )[];
  const result = transfer.data as TransferOwnershipResult | undefined;
  const errorMessage = transferErrorMessage(transfer.error);

  function submit() {
    if (!validId || kinds.length === 0) return;
    transfer.mutate({ replacement_user_id: parsedId, resource_kinds: kinds });
  }

  function handleOpenChange(next: boolean) {
    if (!next) {
      setReplacementId("");
      setRanges(true);
      setWorkspaces(true);
    }
    onOpenChange(next);
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Transfer ownership</DialogTitle>
          <DialogDescription>
            Reassign this user&apos;s owned resources to a replacement account during offboarding. Ranges with a live
            VPN credential and workspaces the replacement is not a member of are reported as blocked, never forced.
          </DialogDescription>
        </DialogHeader>

        {result ? (
          <div className="space-y-2 text-sm" data-testid="transfer-result">
            <p>Transfer complete:</p>
            <ul className="list-disc pl-5 text-muted-foreground">
              <li>Ranges reassigned: {result.ranges_reassigned}, blocked: {result.ranges_blocked}</li>
              <li>
                Workspaces transferred: {result.workspaces_transferred}, already owned: {result.workspaces_already_owned},
                blocked (not a member): {result.workspaces_blocked_no_membership}
              </li>
            </ul>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="replacement-user-id">Replacement user ID</Label>
              <Input
                id="replacement-user-id"
                inputMode="numeric"
                value={replacementId}
                onChange={(event) => setReplacementId(event.target.value)}
                placeholder="e.g. 42"
              />
            </div>
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">Resources to transfer</legend>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={ranges} onChange={(event) => setRanges(event.target.checked)} />
                <span>Ranges</span>
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={workspaces}
                  onChange={(event) => setWorkspaces(event.target.checked)}
                />
                <span>Workspaces</span>
              </label>
            </fieldset>
            {errorMessage ? (
              <Alert variant="destructive">
                <AlertDescription>{errorMessage}</AlertDescription>
              </Alert>
            ) : null}
          </div>
        )}

        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline" disabled={transfer.isPending}>
              {result ? "Close" : "Cancel"}
            </Button>
          </DialogClose>
          {result ? null : (
            <Button onClick={submit} disabled={transfer.isPending || !validId || kinds.length === 0}>
              Transfer
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Field({ label, children }: Readonly<{ label: string; children: ReactNode }>) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="mt-1 text-sm">{children}</dd>
    </div>
  );
}
