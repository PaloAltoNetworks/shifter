/**
 * xterm.js terminal bound to the SSH terminal websocket (#1370).
 *
 * Opens `ws(s)://<host>/ws/terminal/<instance_uuid>/`
 * (`mission_control/routing.py` -> `SSHConsumer`). Framing matches
 * `SSHConsumer.receive` / `_read_ssh_output` (`mission_control/consumers.py`)
 * and the legacy `static/js/terminal.js` exactly:
 *
 *   client -> server: { "type": "input", "data": "<keystrokes>" }
 *                      { "type": "resize", "cols": <n>, "rows": <n> }
 *   server -> client: { "type": "output", "data": "<shell output>" }
 *
 * The socket is same-origin, authenticated by the session cookie
 * (`config/asgi.py`'s `AllowedHostsOriginValidator` + `AuthMiddlewareStack`) —
 * no bearer token, no second auth scheme.
 */
import { useEffect, useRef, useState } from "react";

import { FitAddon } from "@xterm/addon-fit";
import { Terminal as XTerm } from "@xterm/xterm";

import "@xterm/xterm/css/xterm.css";

// Mirrors static/js/terminal.js's terminalOptions.theme for visual continuity
// with the legacy terminal (xterm's own color model, not a design token).
const TERMINAL_THEME = {
  background: "#0d0d0d",
  foreground: "#eaebeb",
  cursor: "#94a3b8",
  cursorAccent: "#0d0d0d",
  selectionBackground: "rgba(148, 163, 184, 0.3)",
  black: "#000000",
  red: "#ff5555",
  green: "#50fa7b",
  yellow: "#f1fa8c",
  blue: "#5391e6",
  magenta: "#ff79c6",
  cyan: "#8be9fd",
  white: "#eaebeb",
  brightBlack: "#666666",
  brightRed: "#ff6e6e",
  brightGreen: "#69ff94",
  brightYellow: "#ffffa5",
  brightBlue: "#6eb6ff",
  brightMagenta: "#ff92df",
  brightCyan: "#a4ffff",
  brightWhite: "#ffffff",
} as const;

export type TerminalConnectionState = "connecting" | "open" | "closed";

export interface TerminalCloseInfo {
  code: number;
  reason: string;
}

function terminalSocketUrl(instanceUuid: string): string {
  const protocol = globalThis.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${globalThis.location.host}/ws/terminal/${instanceUuid}/`;
}

export interface TerminalProps {
  instanceUuid: string;
  onConnectionStateChange?: (state: TerminalConnectionState, closeInfo: TerminalCloseInfo | null) => void;
}

/** Owns one xterm instance + one terminal websocket for its lifetime; remount (via `key`) to reconnect. */
export function Terminal({ instanceUuid, onConnectionStateChange }: Readonly<TerminalProps>) {
  const containerRef = useRef<HTMLElement>(null);
  const onStateChangeRef = useRef(onConnectionStateChange);
  onStateChangeRef.current = onConnectionStateChange;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    const term = new XTerm({
      theme: TERMINAL_THEME,
      fontFamily: "'Monaco', 'Menlo', 'Ubuntu Mono', 'Consolas', monospace",
      fontSize: 13,
      lineHeight: 1.2,
      cursorBlink: true,
      scrollback: 5000,
      allowProposedApi: true,
    });
    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(container);
    fitAddon.fit();

    const socket = new WebSocket(terminalSocketUrl(instanceUuid));

    function sendResize() {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
      }
    }

    socket.onopen = () => {
      fitAddon.fit();
      sendResize();
      term.focus();
      onStateChangeRef.current?.("open", null);
    };

    socket.onmessage = (event) => {
      let message: { type?: string; data?: unknown } | null = null;
      try {
        message = JSON.parse(event.data as string) as { type?: string; data?: unknown };
      } catch {
        return; // Malformed frame; drop it rather than crash the session.
      }
      if (message?.type === "output" && typeof message.data === "string") {
        term.write(message.data);
      }
    };

    socket.onclose = (event) => {
      onStateChangeRef.current?.("closed", { code: event.code, reason: event.reason });
    };

    socket.onerror = () => {
      // Swallow; `onclose` follows immediately and carries the close code.
    };

    const dataDisposable = term.onData((data) => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "input", data }));
      }
    });
    const resizeDisposable = term.onResize(({ cols, rows }) => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "resize", cols, rows }));
      }
    });

    function handleWindowResize() {
      fitAddon.fit();
    }
    window.addEventListener("resize", handleWindowResize);

    return () => {
      window.removeEventListener("resize", handleWindowResize);
      dataDisposable.dispose();
      resizeDisposable.dispose();
      socket.onopen = null;
      socket.onmessage = null;
      socket.onerror = null;
      socket.onclose = null;
      socket.close(1000, "component unmounted");
      term.dispose();
    };
    // `onConnectionStateChange` is intentionally read via `onStateChangeRef`
    // (set on every render, above) rather than closed over directly, so an
    // inline callback identity doesn't tear down and reopen the socket every
    // render; only a real `instanceUuid` change (or unmount) should do that.
  }, [instanceUuid]);

  return (
    <section
      ref={containerRef}
      aria-label="Terminal session"
      className="h-[32rem] overflow-hidden rounded-md border border-white/10 bg-[#0d0d0d] p-2"
    />
  );
}

/** Convenience hook mirroring the imperative callback above as local state, for pages that just want the current state. */
export function useTerminalConnectionState(): {
  state: TerminalConnectionState;
  closeInfo: TerminalCloseInfo | null;
  onConnectionStateChange: (state: TerminalConnectionState, closeInfo: TerminalCloseInfo | null) => void;
} {
  const [state, setState] = useState<TerminalConnectionState>("connecting");
  const [closeInfo, setCloseInfo] = useState<TerminalCloseInfo | null>(null);
  return {
    state,
    closeInfo,
    onConnectionStateChange: (nextState, nextCloseInfo) => {
      setState(nextState);
      setCloseInfo(nextCloseInfo);
    },
  };
}
