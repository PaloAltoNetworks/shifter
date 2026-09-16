/**
 * Selected-workspace context for the organization admin console (#1938,
 * PLAT-231), modeled on `app/mode.tsx`.
 *
 * The authoritative server snapshot is owned by TanStack Query
 * (`usePrincipalContext`). The *selection* is React Router URL state expressed as
 * the workspace's public UUID; this context only exposes the validated selection
 * (resolved against the latest snapshot) to descendants. Neither this context nor
 * any client store is authority: child API calls send the public UUID and are
 * reauthorized server-side, and cached capabilities only shape presentation.
 */
import { createContext, useContext, useMemo, type ReactNode } from "react";

import type { PrincipalWorkspaceContext } from "@/api/types";

interface WorkspaceContextValue {
  /** All workspaces the caller belongs to, in deterministic switcher order. */
  readonly workspaces: readonly PrincipalWorkspaceContext[];
  /** The workspace the current route resolves to, or null (missing/stale/empty). */
  readonly selected: PrincipalWorkspaceContext | null;
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceContextProvider({
  workspaces,
  selected,
  children,
}: Readonly<{
  workspaces: readonly PrincipalWorkspaceContext[];
  selected: PrincipalWorkspaceContext | null;
  children: ReactNode;
}>) {
  // Memoize so the context value is stable across renders when its inputs are
  // unchanged (a fresh object every render would re-render all consumers).
  const value = useMemo(() => ({ workspaces, selected }), [workspaces, selected]);
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspaceContext(): WorkspaceContextValue {
  const value = useContext(WorkspaceContext);
  if (value === null) {
    throw new Error("useWorkspaceContext must be used within a WorkspaceContextProvider");
  }
  return value;
}
