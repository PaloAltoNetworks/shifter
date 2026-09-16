/**
 * Organization console landing (#1938, PLAT-231): the caller's organizations and
 * workspaces, grouped by organization, each linking into its workspace scope. A
 * read-only overview — the per-capability surfaces land with PLAT-232–240.
 */
import { Link } from "react-router";

import type { PrincipalWorkspaceContext } from "@/api/types";
import { Card } from "@/components/ui/card";

import { organizationSettingsPath, organizationWorkspacesPath, workspaceScopePath } from "../routes";
import { useWorkspaceContext } from "./WorkspaceContext";

function groupByOrganization(
  workspaces: readonly PrincipalWorkspaceContext[],
): Array<{ uuid: string; name: string; workspaces: PrincipalWorkspaceContext[] }> {
  const byUuid = new Map<string, { uuid: string; name: string; workspaces: PrincipalWorkspaceContext[] }>();
  for (const workspace of workspaces) {
    const key = workspace.organization.uuid;
    const group = byUuid.get(key) ?? { uuid: key, name: workspace.organization.name, workspaces: [] };
    group.workspaces.push(workspace);
    byUuid.set(key, group);
  }
  return [...byUuid.values()];
}

export function OrganizationOverviewPage() {
  const { workspaces } = useWorkspaceContext();
  const organizations = groupByOrganization(workspaces);

  return (
    <div className="space-y-6">
      <nav aria-label="Organization sections" className="flex flex-wrap gap-3 text-sm">
        <Link to={organizationSettingsPath()} className="text-muted-foreground hover:text-foreground">
          Organization settings
        </Link>
        <Link to={organizationWorkspacesPath()} className="text-muted-foreground hover:text-foreground">
          Workspaces
        </Link>
      </nav>

      {organizations.map((organization) => (
        <Card key={organization.uuid} className="p-6">
          <h2 className="text-sm font-medium">{organization.name}</h2>
          <ul className="mt-3 space-y-2">
            {organization.workspaces.map((workspace) => (
              <li key={workspace.workspace_uuid} className="flex items-center justify-between gap-4">
                <Link
                  to={workspaceScopePath(workspace.workspace_uuid)}
                  className="text-sm text-foreground/90 hover:underline"
                >
                  {workspace.workspace_name}
                  {workspace.is_personal ? " (personal)" : ""}
                </Link>
                <span className="text-xs text-muted-foreground">{workspace.role}</span>
              </li>
            ))}
          </ul>
        </Card>
      ))}
    </div>
  );
}
