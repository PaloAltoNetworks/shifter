/**
 * One terminal-workspace pane: an SSH surface plus the RDP action (#1661).
 *
 * A slot is the single rendering unit shared by tabs mode (one slot) and split
 * mode (two slots). It composes the incumbents rather than re-implementing
 * them: `Terminal` owns the socket and xterm, `useTerminalConnectionState` and
 * `terminalStatus` own connection presentation and close-code copy, and
 * `useGuacamoleSession` owns the server-brokered RDP queue/poll/open. One
 * `useGuacamoleSession` per slot gives each pane independent busy/error state.
 *
 * "SSH" here means the portal's own `/ws/terminal/<uuid>/` xterm channel, not
 * the Guacamole SSH protocol; the two are different transports with different
 * session-state and capacity models and are deliberately not merged.
 *
 * The slot never receives, stores, or renders a signed Guacamole URL — the
 * shared opener consumes it in place.
 */
import { useState } from "react";

import { ExternalLink, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Terminal, useTerminalConnectionState } from "./Terminal";
import type { ConsoleTarget } from "./consoleTargets";
import { useGuacamoleSession } from "./guacamole";
import { ConnectionBadge, TerminalCloseAlert } from "./terminalStatus";

function EmptyPane({ label }: Readonly<{ label: string }>) {
  return (
    <div className="flex h-full flex-col rounded-md border border-dashed bg-muted/20">
      <p className="m-auto p-6 text-center text-sm text-muted-foreground">
        No device selected for the {label.toLowerCase()}.
      </p>
    </div>
  );
}

export interface TerminalSlotProps {
  /** The assigned console target, or null when this pane has nothing to show. */
  target: ConsoleTarget | null;
  /** Accessible name for the pane region ("Left pane", "Right pane", ...). */
  label: string;
  tmuxWheelScrolling?: boolean;
  /** Rendered next to the device identity — the split-mode device select. */
  children?: React.ReactNode;
}

export function TerminalSlot({ target, label, tmuxWheelScrolling = false, children }: Readonly<TerminalSlotProps>) {
  const [reconnectKey, setReconnectKey] = useState(0);
  const { state, closeInfo, onConnectionStateChange } = useTerminalConnectionState();
  const guacamole = useGuacamoleSession();

  if (!target) {
    return <EmptyPane label={label} />;
  }

  const rdpBusy = guacamole.pendingProtocol === "rdp";

  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      {/*
        A plain div, not <header>: outside a sectioning element a <header> is a
        page `banner` landmark, so two panes would publish duplicate banners.
        This is a pane toolbar, and the terminal region below carries the name.
      */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          {children}
          <span className="truncate text-sm font-medium">{target.name}</span>
          {target.private_ip ? (
            <span className="font-mono text-xs text-muted-foreground">{target.private_ip}</span>
          ) : null}
        </div>
        <div className="flex items-center gap-3">
          <ConnectionBadge state={state} />
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={rdpBusy}
            aria-busy={rdpBusy}
            aria-label={`Open RDP session on ${target.name}`}
            onClick={() => guacamole.open({ protocol: "rdp", instanceUuid: target.uuid })}
          >
            {rdpBusy ? (
              <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <ExternalLink className="size-3.5" aria-hidden="true" />
            )}
            RDP
          </Button>
        </div>
      </div>

      {guacamole.error ? (
        <p role="alert" className="text-xs text-destructive">
          {guacamole.error}
        </p>
      ) : null}

      {state === "closed" && closeInfo ? (
        <TerminalCloseAlert
          closeInfo={closeInfo}
          onReconnect={() => {
            onConnectionStateChange("connecting", null);
            setReconnectKey((key) => key + 1);
          }}
        />
      ) : null}

      <Terminal
        // Remounting on the target or reconnect counter is what tears the old
        // socket down; there is never more than one socket per slot.
        key={`${target.uuid}:${reconnectKey}`}
        instanceUuid={target.uuid}
        tmuxWheelScrolling={tmuxWheelScrolling}
        onConnectionStateChange={onConnectionStateChange}
        className="min-h-0 flex-1"
        label={`${label}: ${target.name}`}
      />
    </div>
  );
}
