import { createContext, useContext, type ReactNode } from "react";

import { Loader2 } from "lucide-react";

import { useBootstrap } from "@/api/bootstrap";
import { ApiError } from "@/api/errors";
import type { Bootstrap } from "@/api/types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

const BootstrapContext = createContext<Bootstrap | null>(null);

/**
 * Loads the session bootstrap once and provides it to the workspace. On 401
 * (expired session) it redirects to the shared Django login; other failures
 * render a non-leaking error state.
 */
export function BootstrapProvider({ children }: Readonly<{ children: ReactNode }>) {
  const { data, isLoading, error } = useBootstrap();

  if (isLoading) {
    return (
      <div className="grid min-h-dvh place-items-center bg-background text-muted-foreground">
        <Loader2 className="size-6 animate-spin" aria-label="Loading workspace" />
      </div>
    );
  }

  if (error || !data) {
    if (error instanceof ApiError && error.status === 401) {
      const next = encodeURIComponent(globalThis.location.pathname + globalThis.location.search);
      globalThis.location.assign(`/login/?next=${next}`);
      return null;
    }
    return (
      <div className="grid min-h-dvh place-items-center bg-background p-6">
        <Alert variant="destructive" className="max-w-md">
          <AlertTitle>Unable to load the workspace</AlertTitle>
          <AlertDescription>Please retry. If the problem persists, contact an administrator.</AlertDescription>
        </Alert>
      </div>
    );
  }

  return <BootstrapContext.Provider value={data}>{children}</BootstrapContext.Provider>;
}

export function useBootstrapContext(): Bootstrap {
  const value = useContext(BootstrapContext);
  if (value === null) {
    throw new Error("useBootstrapContext must be used within a BootstrapProvider");
  }
  return value;
}
