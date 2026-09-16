/**
 * Shared terminal connection-state presentation (#1370, #1661).
 *
 * Extracted from `TerminalPage` so the standalone page and every workspace pane
 * render one close-code vocabulary and one connection affordance. There is no
 * second close-code enum in the SPA: unknown codes fall through to a generic
 * message here.
 */
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { TerminalCloseInfo, TerminalConnectionState } from "./Terminal";

// cyberscript.enums.WebSocketCloseCode (mission_control/consumers.py,
// status_consumers.py) — the application close codes SSHConsumer actually
// sends, mapped to accessible copy. Codes not listed here (e.g. an abnormal
// network drop, which never carries one of these) fall through to a generic
// message.
const CLOSE_CODE_COPY: Record<number, string> = {
  1000: "Session ended.",
  4001: "Your session has expired. Sign in again to reconnect.",
  4003: "You do not have permission to access this instance.",
  4004: "This instance could not be found. It may have been destroyed.",
  4005: "Invalid terminal request.",
  4500: "A server error interrupted the session.",
  4502: "Could not establish an SSH connection to this instance.",
  4503: "Terminal capacity is temporarily unavailable. Try reconnecting in a moment.",
};

export function closeMessage(code: number): string {
  return CLOSE_CODE_COPY[code] ?? "Connection closed unexpectedly.";
}

function connectionBadgeCopy(state: TerminalConnectionState): string {
  if (state === "open") return "Connected";
  if (state === "connecting") return "Connecting…";
  return "Disconnected";
}

function connectionDotClass(state: TerminalConnectionState): string {
  if (state === "open") return "bg-emerald-500";
  if (state === "connecting") return "bg-amber-500 animate-pulse";
  return "bg-destructive";
}

/** Connection state as a dot plus text — never color alone. */
export function ConnectionBadge({ state }: Readonly<{ state: TerminalConnectionState }>) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
      <span className={cn("size-1.5 rounded-full", connectionDotClass(state))} aria-hidden="true" />
      {connectionBadgeCopy(state)}
    </span>
  );
}

/**
 * The closed-session notice and its explicit reconnect action.
 *
 * Reconnect is always user-initiated: close code 4503 (terminal capacity) is
 * retryable, and an automatic multi-pane reconnect would turn one saturated
 * worker into a reconnect storm.
 */
export function TerminalCloseAlert({
  closeInfo,
  onReconnect,
  className,
}: Readonly<{ closeInfo: TerminalCloseInfo; onReconnect: () => void; className?: string }>) {
  const isCleanClose = closeInfo.code === 1000;
  return (
    <Alert variant={isCleanClose ? "default" : "destructive"} className={className}>
      <AlertTitle>{isCleanClose ? "Session ended" : "Connection lost"}</AlertTitle>
      <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
        <span>{closeMessage(closeInfo.code)}</span>
        <Button type="button" size="sm" variant="outline" onClick={onReconnect}>
          Reconnect
        </Button>
      </AlertDescription>
    </Alert>
  );
}
