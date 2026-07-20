import { useState } from "react";
import { useParams } from "react-router-dom";

import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

import { Terminal, useTerminalConnectionState, type TerminalConnectionState } from "./Terminal";

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

function closeMessage(code: number): string {
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

function ConnectionBadge({ state }: Readonly<{ state: TerminalConnectionState }>) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
      <span className={cn("size-1.5 rounded-full", connectionDotClass(state))} aria-hidden="true" />
      {connectionBadgeCopy(state)}
    </span>
  );
}

export function TerminalPage() {
  const { instanceUuid } = useParams<{ instanceUuid: string }>();
  const [reconnectKey, setReconnectKey] = useState(0);
  const { state, closeInfo, onConnectionStateChange } = useTerminalConnectionState();

  if (!instanceUuid) {
    return (
      <>
        <PageHeader title="Terminal" description="Open a terminal session on a range instance." />
        <Alert variant="destructive">
          <AlertTitle>No instance specified</AlertTitle>
          <AlertDescription>This terminal link is missing an instance to connect to.</AlertDescription>
        </Alert>
      </>
    );
  }

  const isCleanClose = closeInfo?.code === 1000;

  return (
    <>
      <PageHeader
        title="Terminal"
        description="SSH session on this range instance."
        actions={<ConnectionBadge state={state} />}
      />

      {state === "closed" && closeInfo ? (
        <Alert variant={isCleanClose ? "default" : "destructive"} className="mb-4">
          <AlertTitle>{isCleanClose ? "Session ended" : "Connection lost"}</AlertTitle>
          <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
            <span>{closeMessage(closeInfo.code)}</span>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => {
                onConnectionStateChange("connecting", null);
                setReconnectKey((key) => key + 1);
              }}
            >
              Reconnect
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}

      <Card className="overflow-hidden p-2">
        <Terminal key={reconnectKey} instanceUuid={instanceUuid} onConnectionStateChange={onConnectionStateChange} />
      </Card>
    </>
  );
}
