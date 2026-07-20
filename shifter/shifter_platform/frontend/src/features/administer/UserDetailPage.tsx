import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import type { ReactNode } from "react";

import { useAdminUser, useGrantOrganizer, useSetUserActive, useSoftDeleteUser } from "@/api/administer";
import { ApiError } from "@/api/errors";
import type { AdminUserDetail } from "@/api/types";
import { useBootstrapContext } from "@/app/bootstrap-context";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

import { AccountOriginBadge, AccountStatusBadge, RoleBadge } from "./badges";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { accountOriginLabel, formatTimestamp, titleCase } from "./format";
import { usersListPath } from "./routes";

type DialogKind = "set-active" | "delete" | "grant-organizer";

function loadErrorTitle(error: unknown): string {
  if (error instanceof ApiError && error.status === 403) return "You do not have permission to view this user";
  if (error instanceof ApiError && error.status === 404) return "User not found";
  return "Could not load user";
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

  const setActive = useSetUserActive(user.id);
  const softDelete = useSoftDeleteUser(user.id);
  const grantOrganizer = useGrantOrganizer(user.id);

  function close() {
    setActive.reset();
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
            isSelf={bootstrap.principal.id === user.id}
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
        setActive={setActive}
        softDelete={softDelete}
        grantOrganizer={grantOrganizer}
        onClose={close}
        onDone={() => setDialog(null)}
      />
    </>
  );
}

function UserActions({
  user,
  canChange,
  canDelete,
  isSelf,
  onOpen,
}: Readonly<{
  user: AdminUserDetail;
  canChange: boolean;
  canDelete: boolean;
  isSelf: boolean;
  onOpen: (dialog: DialogKind) => void;
}>) {
  const showLifecycle = canChange && !user.is_deleted;
  return (
    <div className="flex flex-wrap items-center gap-2">
      {showLifecycle ? (
        <Button
          variant="outline"
          size="sm"
          disabled={isSelf && user.is_active}
          title={isSelf && user.is_active ? "You cannot deactivate your own account." : undefined}
          onClick={() => onOpen("set-active")}
        >
          {user.is_active ? "Deactivate" : "Activate"}
        </Button>
      ) : null}
      {showLifecycle && !user.is_ctf_organizer ? (
        <Button variant="outline" size="sm" onClick={() => onOpen("grant-organizer")}>
          Grant CTF Organizer
        </Button>
      ) : null}
      {canDelete && !user.is_deleted ? (
        <Button
          variant="destructive"
          size="sm"
          disabled={isSelf}
          title={isSelf ? "You cannot delete your own account." : undefined}
          onClick={() => onOpen("delete")}
        >
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
          <AccountStatusBadge isActive={user.is_active} isDeleted={user.is_deleted} />
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
  setActive,
  softDelete,
  grantOrganizer,
  onClose,
  onDone,
}: Readonly<{
  user: AdminUserDetail;
  dialog: DialogKind | null;
  setActive: ReturnType<typeof useSetUserActive>;
  softDelete: ReturnType<typeof useSoftDeleteUser>;
  grantOrganizer: ReturnType<typeof useGrantOrganizer>;
  onClose: () => void;
  onDone: () => void;
}>) {
  const specs = [
    {
      kind: "set-active",
      title: user.is_active ? "Deactivate account?" : "Activate account?",
      confirmLabel: user.is_active ? "Deactivate" : "Activate",
      destructive: user.is_active,
      pending: setActive.isPending,
      error: setActive.error,
      confirm: () => setActive.mutate(!user.is_active, { onSuccess: onDone }),
      body: user.is_active
        ? "The user will be signed out and blocked from signing in until reactivated. This does not delete or anonymize the account."
        : "The user will be able to sign in again.",
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
      body: "The account is soft-deleted and can no longer sign in. This does not permanently erase, anonymize, or unbind the provider identity.",
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

function Field({ label, children }: Readonly<{ label: string; children: ReactNode }>) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="mt-1 text-sm">{children}</dd>
    </div>
  );
}
