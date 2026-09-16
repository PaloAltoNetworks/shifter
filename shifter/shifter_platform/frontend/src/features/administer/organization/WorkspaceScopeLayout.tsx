/**
 * Workspace-scoped console layout (#1938, PLAT-231).
 *
 * Renders the capability-aware in-console navigation for the selected workspace
 * and an outlet for its surface slots. A supplied UUID that does not resolve to
 * one of the caller's workspaces renders an honest "not found" state — it never
 * silently falls back to another (or the personal) workspace. The advertised
 * capabilities only enable/disable navigation entries; each surface's endpoint
 * reauthorizes when it lands.
 */
import { Link, Outlet } from "react-router";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card } from "@/components/ui/card";

import { organizationPath, workspaceSurfacePath } from "../routes";
import { useWorkspaceContext } from "./WorkspaceContext";
import { WORKSPACE_SURFACES, surfaceEnabled } from "./surfaces";

export function WorkspaceScopeLayout() {
  const { selected } = useWorkspaceContext();

  if (selected === null) {
    return (
      <Alert variant="destructive" className="max-w-xl">
        <AlertTitle>Workspace not found</AlertTitle>
        <AlertDescription>
          That workspace is not available to you. <Link to={organizationPath()} className="underline">Return to the organization console.</Link>
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="space-y-6">
      <Card className="p-4">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 className="text-sm font-medium">
              {selected.organization.name} / {selected.workspace_name}
            </h2>
            <p className="text-xs text-muted-foreground">Your role: {selected.role}</p>
          </div>
        </div>
        <nav aria-label="Workspace sections" className="mt-4 flex flex-wrap gap-3 text-sm">
          {WORKSPACE_SURFACES.map((surface) => {
            const enabled = surfaceEnabled(surface, selected);
            if (!enabled) {
              return (
                <span key={surface.key} aria-disabled="true" className="cursor-not-allowed text-muted-foreground/50">
                  {surface.label}
                </span>
              );
            }
            return (
              <Link
                key={surface.key}
                to={workspaceSurfacePath(selected.workspace_uuid, surface.key)}
                className="text-muted-foreground hover:text-foreground"
              >
                {surface.label}
              </Link>
            );
          })}
        </nav>
      </Card>
      <Outlet />
    </div>
  );
}
