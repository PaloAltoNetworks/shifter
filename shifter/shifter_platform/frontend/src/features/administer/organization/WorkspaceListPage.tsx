/**
 * Organization-scoped workspace list (#1940, PLAT-233). Lists the non-personal
 * workspaces of a chosen administrable organization, with search, an
 * include-archived toggle, and a create affordance.
 *
 * Authority lives on the server: `/api/v1/workspaces/` authorizes the caller's
 * organization-admin role and is the audit boundary; this surface only presents
 * the projection and posts a create. Organizations and workspaces are addressed
 * by public UUID only, and organization selection is explicit — the chooser
 * lists the principal's administrable organizations (ADR-048) rather than
 * guessing. Personal workspaces are excluded server-side, so nothing here
 * special-cases them.
 */
import { useState } from "react";
import { Link, useSearchParams } from "react-router";

import { useAdministrableOrganizations } from "@/api/organization";
import { useCreateWorkspace, useWorkspaces } from "@/api/workspaces";
import { ApiError, describeMutationError } from "@/api/errors";
import type { OrganizationProfile } from "@/api/types";
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
import { workspaceScopePath } from "../routes";

export function WorkspaceListPage() {
  const orgsQuery = useAdministrableOrganizations();

  if (orgsQuery.isLoading) {
    return (
      <>
        <PageHeader title="Workspaces" description="Manage organization workspaces" />
        <Skeleton className="h-40 w-full max-w-2xl" />
      </>
    );
  }

  if (orgsQuery.isError || !orgsQuery.data) {
    return (
      <>
        <PageHeader title="Workspaces" description="Manage organization workspaces" />
        <Alert variant="destructive" className="max-w-xl">
          <AlertTitle>Could not load your organizations</AlertTitle>
          <AlertDescription>Please retry. If the problem persists, contact an administrator.</AlertDescription>
        </Alert>
      </>
    );
  }

  const organizations = orgsQuery.data.results;

  if (organizations.length === 0) {
    return (
      <>
        <PageHeader title="Workspaces" description="Manage organization workspaces" />
        <Alert className="max-w-xl">
          <AlertTitle>No organizations available</AlertTitle>
          <AlertDescription>You do not administer any organization yet.</AlertDescription>
        </Alert>
      </>
    );
  }

  return <WorkspaceListView organizations={organizations} />;
}

/** The list view once at least one administrable organization is known. */
function WorkspaceListView({ organizations }: Readonly<{ organizations: readonly OrganizationProfile[] }>) {
  const [params, setParams] = useSearchParams();
  const orgParam = params.get("org");
  // Deep links pin an organization; fall back to the first administrable one so
  // the list always resolves to a real, authorized organization scope.
  const selectedOrg = organizations.find((organization) => organization.uuid === orgParam) ?? organizations[0];
  const search = params.get("q")?.trim() || undefined;
  const includeArchived = params.get("archived") === "1";

  const [searchInput, setSearchInput] = useState(search ?? "");

  const query = useWorkspaces({ organizationUuid: selectedOrg.uuid, includeArchived, search });

  function updateParam(key: string, value: string | null) {
    const next = new URLSearchParams(params);
    if (value) {
      next.set(key, value);
    } else {
      next.delete(key);
    }
    setParams(next);
  }

  return (
    <>
      <PageHeader
        title="Workspaces"
        description={`Manage workspaces in ${selectedOrg.name}`}
        actions={<CreateWorkspaceDialog organizationUuid={selectedOrg.uuid} />}
      />

      <form
        className="mb-4 flex flex-wrap items-center gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          updateParam("q", searchInput.trim() || null);
        }}
        role="search"
      >
        {organizations.length > 1 ? (
          <Select value={selectedOrg.uuid} onValueChange={(value) => updateParam("org", value)}>
            <SelectTrigger size="sm" className="w-[220px]" aria-label="Select organization">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {organizations.map((organization) => (
                <SelectItem key={organization.uuid} value={organization.uuid}>
                  {organization.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : null}

        <Input
          type="search"
          value={searchInput}
          onChange={(event) => setSearchInput(event.target.value)}
          placeholder="Search workspaces"
          aria-label="Search workspaces by name"
          className="w-[240px]"
          maxLength={100}
        />
        <Button type="submit" variant="outline" size="sm">
          Search
        </Button>

        <label className="flex select-none items-center gap-2 text-sm text-muted-foreground">
          <input
            type="checkbox"
            className="size-4 rounded border-input bg-transparent accent-primary"
            checked={includeArchived}
            onChange={(event) => updateParam("archived", event.target.checked ? "1" : null)}
          />
          <span>Include archived</span>
        </label>
      </form>

      <Card className="overflow-hidden py-0" aria-busy={query.isFetching}>
        <WorkspaceListBody query={query} filtersActive={Boolean(search)} />
      </Card>
    </>
  );
}

function WorkspaceListBody({
  query,
  filtersActive,
}: Readonly<{ query: ReturnType<typeof useWorkspaces>; filtersActive: boolean }>) {
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
    const forbidden = query.error instanceof ApiError && query.error.status === 403;
    return (
      <div className="p-4">
        <Alert variant="destructive">
          <AlertTitle>{forbidden ? "You do not have permission to view these workspaces" : "Could not load workspaces"}</AlertTitle>
          <AlertDescription>
            {forbidden ? "Ask an administrator to grant you workspace-admin access." : "Please retry."}
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  const workspaces = query.data ?? [];
  if (workspaces.length === 0) {
    return (
      <div className="grid place-items-center px-6 py-16 text-center">
        <p className="text-sm font-medium">{filtersActive ? "No workspaces match your search" : "No workspaces yet"}</p>
        <p className="mt-1 text-sm text-muted-foreground">
          {filtersActive ? "Adjust or clear the search to see more." : "Create a workspace to get started."}
        </p>
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead>Name</TableHead>
          <TableHead className="w-[120px]">Status</TableHead>
          <TableHead className="w-[200px]">Created</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {workspaces.map((workspace) => (
          <TableRow key={workspace.uuid}>
            <TableCell className="font-medium">
              <Link className="hover:underline" to={workspaceScopePath(workspace.uuid)}>
                {workspace.name}
              </Link>
            </TableCell>
            <TableCell>
              {workspace.is_archived ? <Badge variant="secondary">Archived</Badge> : <Badge variant="outline">Active</Badge>}
            </TableCell>
            <TableCell className="text-sm text-muted-foreground">{formatTimestamp(workspace.created_at)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/** Create-workspace dialog: a name input that posts to the lifecycle endpoint. */
function CreateWorkspaceDialog({ organizationUuid }: Readonly<{ organizationUuid: string }>) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const mutation = useCreateWorkspace();

  const fieldErrors = mutation.error instanceof ApiError ? mutation.error.fieldErrors() : {};
  const topLevelError =
    Object.keys(fieldErrors).length === 0 ? describeMutationError(mutation.error, "The workspace could not be created.") : null;

  function onOpenChange(next: boolean) {
    setOpen(next);
    if (!next) {
      setName("");
      mutation.reset();
    }
  }

  function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    mutation.mutate(
      { organization_uuid: organizationUuid, name: name.trim() },
      { onSuccess: () => onOpenChange(false) },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button size="sm">Create workspace</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create workspace</DialogTitle>
          <DialogDescription>Add a new workspace to this organization.</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={onSubmit} aria-label="Create workspace">
          <div className="flex flex-col gap-2">
            <Label htmlFor="create-workspace-name">Workspace name</Label>
            <Input
              id="create-workspace-name"
              value={name}
              aria-invalid={fieldErrors.name ? true : undefined}
              onChange={(event) => setName(event.target.value)}
            />
            {fieldErrors.name?.length ? (
              <p className="text-sm text-destructive">{fieldErrors.name.join(" ")}</p>
            ) : null}
          </div>

          {topLevelError ? (
            <Alert variant="destructive">
              <AlertDescription>{topLevelError}</AlertDescription>
            </Alert>
          ) : null}

          <DialogFooter>
            <Button type="submit" disabled={mutation.isPending || name.trim().length === 0}>
              {mutation.isPending ? "Creating…" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
