/**
 * Organization/workspace admin console shell (#1938, PLAT-231).
 *
 * Owns the layout, the current-principal context query, the workspace switcher,
 * and the selected-workspace React context for descendants. Route/nav/flag/
 * switcher visibility is advisory throughout; the `/api/v1/workspaces/`
 * endpoints remain the authority. This slice ships the shell and route slots
 * only — the child surfaces land with PLAT-232–240.
 */
import { Outlet, useParams } from "react-router";

import { usePrincipalContext } from "@/api/principalContext";
import { ApiError } from "@/api/errors";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";

import { WorkspaceContextProvider } from "./WorkspaceContext";
import { WorkspaceSwitcher } from "./WorkspaceSwitcher";
import { resolveSelectedWorkspace } from "./surfaces";

export function OrganizationConsoleLayout() {
  const { workspaceUuid } = useParams();
  const query = usePrincipalContext();

  if (query.isLoading) {
    return (
      <>
        <PageHeader title="Organization" description="Organization and workspace administration" />
        <Skeleton className="h-10 w-64" />
      </>
    );
  }

  if (query.error) {
    const denied = query.error instanceof ApiError && query.error.status === 403;
    return (
      <>
        <PageHeader title="Organization" description="Organization and workspace administration" />
        <Alert variant="destructive" className="max-w-xl">
          <AlertTitle>{denied ? "You do not have access to the organization console" : "Could not load organization context"}</AlertTitle>
          <AlertDescription>
            {denied
              ? "This console requires a staff session. Contact an administrator if you believe this is an error."
              : "Please retry. If the problem persists, contact an administrator."}
          </AlertDescription>
        </Alert>
      </>
    );
  }

  const workspaces = query.data ?? [];
  const selected = resolveSelectedWorkspace(workspaces, workspaceUuid);

  return (
    <WorkspaceContextProvider workspaces={workspaces} selected={selected}>
      <PageHeader
        title="Organization"
        description="Organization and workspace administration"
        actions={<WorkspaceSwitcher workspaces={workspaces} selected={selected} />}
      />
      {workspaces.length === 0 ? (
        <Alert className="max-w-xl">
          <AlertTitle>No workspaces yet</AlertTitle>
          <AlertDescription>
            You do not belong to any workspaces. Once you are added to a workspace it will appear here.
          </AlertDescription>
        </Alert>
      ) : (
        <Outlet />
      )}
    </WorkspaceContextProvider>
  );
}
