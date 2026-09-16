/**
 * Workspace switcher for the organization admin console (#1938, PLAT-231).
 *
 * Selecting a workspace navigates to its public-UUID route; the selection lives
 * in the URL, never in local storage or a server-persisted "current workspace".
 */
import { useNavigate } from "react-router";

import type { PrincipalWorkspaceContext } from "@/api/types";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

import { workspaceScopePath } from "../routes";

export function WorkspaceSwitcher({
  workspaces,
  selected,
}: Readonly<{
  workspaces: readonly PrincipalWorkspaceContext[];
  selected: PrincipalWorkspaceContext | null;
}>) {
  const navigate = useNavigate();

  if (workspaces.length === 0) {
    return null;
  }

  return (
    <Select value={selected?.workspace_uuid ?? ""} onValueChange={(uuid) => navigate(workspaceScopePath(uuid))}>
      <SelectTrigger className="w-64" aria-label="Select workspace">
        <SelectValue placeholder="Select a workspace" />
      </SelectTrigger>
      <SelectContent>
        {workspaces.map((workspace) => (
          <SelectItem key={workspace.workspace_uuid} value={workspace.workspace_uuid}>
            {workspace.organization.name} / {workspace.workspace_name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
