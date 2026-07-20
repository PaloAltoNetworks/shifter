/**
 * UX mode context for the platform shell (#1369, ADR-013).
 *
 * Mode (participant / operator) is a user-facing frame, not an authorization
 * fact: switching mode changes the navigation structure and default landing but
 * never grants permission (ADR-013-R3/R4). Eligibility comes from the bootstrap
 * payload; the current selection is in-memory only (no localStorage — the shell
 * stores no drafts or state that outlives the session), defaulting to the
 * server-provided default mode. Users eligible for only one mode cannot switch.
 */
import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

import type { Bootstrap, UxMode } from "@/api/types";

interface ModeContextValue {
  readonly mode: UxMode;
  readonly canSwitch: boolean;
  readonly setMode: (mode: UxMode) => void;
}

const ModeContext = createContext<ModeContextValue | null>(null);

function eligibleModes(bootstrap: Bootstrap): UxMode[] {
  const modes: UxMode[] = [];
  if (bootstrap.modes.operator) modes.push("operator");
  if (bootstrap.modes.participant) modes.push("participant");
  return modes;
}

export function ModeProvider({
  bootstrap,
  children,
}: Readonly<{ bootstrap: Bootstrap; children: ReactNode }>) {
  const eligible = useMemo(() => eligibleModes(bootstrap), [bootstrap]);
  const [activeMode, setActiveMode] = useState<UxMode>(() => {
    const preferred = bootstrap.modes.default;
    return eligible.includes(preferred) ? preferred : (eligible[0] ?? "operator");
  });

  const value = useMemo<ModeContextValue>(
    () => ({
      mode: activeMode,
      canSwitch: eligible.length > 1,
      setMode: (next: UxMode) => {
        // Guard: only switch into a mode the principal is eligible for.
        if (eligible.includes(next)) setActiveMode(next);
      },
    }),
    [activeMode, eligible],
  );

  return <ModeContext.Provider value={value}>{children}</ModeContext.Provider>;
}

export function useMode(): ModeContextValue {
  const value = useContext(ModeContext);
  if (value === null) {
    throw new Error("useMode must be used within a ModeProvider");
  }
  return value;
}
