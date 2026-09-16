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

import { cn } from "@/lib/utils";

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

type ConnectionStateHandler = (state: TerminalConnectionState, closeInfo: TerminalCloseInfo | null) => void;

/** Create the xterm instance, load the fit addon, and mount it into `container`. */
function createTerminal(container: HTMLElement): { term: XTerm; fitAddon: FitAddon } {
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
  return { term, fitAddon };
}

/**
 * Wire copy-on-select and Ctrl+Shift+C/V for the terminal.
 *
 * tmux owns wheel events so its history remains scrollable. xterm's standard
 * Shift+drag bypass creates a browser selection; copy it when the drag ends.
 *
 * Paste is deliberately NOT bound to `contextmenu`. Ranges are
 * adversary-simulation environments, so a hostile or compromised instance can
 * prompt the operator to right-click; reading `navigator.clipboard` there and
 * feeding it straight to the session would silently exfiltrate whatever is on
 * the workstation clipboard (passwords, cloud credentials, incident notes)
 * into the remote shell — with the default browser menu suppressed, nothing
 * signals that a clipboard read happened. Paste stays an explicit gesture:
 * Ctrl+Shift+V below, or the browser's own context-menu paste.
 *
 * Returns a teardown that removes the DOM listeners it added.
 */
function attachClipboardAndKeys(term: XTerm): () => void {
  const terminalElement = term.element;
  const copySelection = () => {
    const selection = term.getSelection();
    if (selection && navigator.clipboard) {
      void navigator.clipboard.writeText(selection).catch(() => undefined);
    }
  };
  const pasteClipboard = () => {
    if (navigator.clipboard) {
      void navigator.clipboard
        .readText()
        .then((text) => {
          if (text) term.paste(text);
        })
        .catch(() => undefined);
    }
  };
  const handleMouseUp = () => copySelection();

  terminalElement?.addEventListener("mouseup", handleMouseUp);
  term.attachCustomKeyEventHandler((event) => {
    if (event.type !== "keydown" || !event.ctrlKey || !event.shiftKey) return true;
    if (event.key.toLowerCase() === "c") {
      copySelection();
      return false;
    }
    if (event.key.toLowerCase() === "v") {
      pasteClipboard();
      return false;
    }
    return true;
  });

  return () => {
    terminalElement?.removeEventListener("mouseup", handleMouseUp);
  };
}

/** Forward wheel gestures to tmux (throttled) when `enabled`; returns a teardown. */
function attachTmuxWheel(term: XTerm, socket: WebSocket, enabled: boolean): () => void {
  const terminalElement = term.element;
  let lastWheelInputAt = 0;
  const handleTmuxWheel = (event: WheelEvent) => {
    if (!enabled || event.deltaY === 0) return;
    event.preventDefault();
    event.stopPropagation();

    // Trackpads emit many events per gesture. Throttle them into deliberate
    // tmux scroll steps rather than flooding the SSH websocket.
    const now = performance.now();
    if (now - lastWheelInputAt < 35) return;
    lastWheelInputAt = now;
    if (socket.readyState === WebSocket.OPEN) {
      const key = event.deltaY < 0 ? "\u001b[23~" : "\u001b[24~"; // F11 / F12
      socket.send(JSON.stringify({ type: "input", data: key }));
    }
  };
  if (enabled) {
    terminalElement?.addEventListener("wheel", handleTmuxWheel, { capture: true, passive: false });
  }
  return () => {
    terminalElement?.removeEventListener("wheel", handleTmuxWheel, { capture: true });
  };
}

/**
 * Bridge the websocket and the terminal: input/resize out, output in, plus
 * connection-state callbacks. `onStateChange` is read through a ref so a new
 * inline callback identity never tears down the live socket. Returns a teardown
 * that disposes the terminal listeners, detaches the socket handlers, and closes it.
 */
function bindSocket(
  term: XTerm,
  fitAddon: FitAddon,
  socket: WebSocket,
  onStateChange: { readonly current: ConnectionStateHandler | undefined },
): () => void {
  function sendResize() {
    if (socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
    }
  }

  socket.onopen = () => {
    fitAddon.fit();
    sendResize();
    term.focus();
    onStateChange.current?.("open", null);
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
    onStateChange.current?.("closed", { code: event.code, reason: event.reason });
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

  return () => {
    dataDisposable.dispose();
    resizeDisposable.dispose();
    socket.onopen = null;
    socket.onmessage = null;
    socket.onerror = null;
    socket.onclose = null;
    socket.close(1000, "component unmounted");
  };
}

export interface TerminalProps {
  instanceUuid: string;
  tmuxWheelScrolling?: boolean;
  onConnectionStateChange?: ConnectionStateHandler;
  /**
   * Container sizing for the terminal surface. Defaults to the standalone
   * page's fixed height; the workspace passes `h-full` so a pane (tab body or
   * split column) drives the height instead. `FitAddon` and xterm DOM
   * ownership stay inside this component either way.
   */
  className?: string;
  /**
   * Accessible name for the terminal region. The workspace passes a
   * device-specific name so two panes are not duplicate `region` landmarks.
   */
  label?: string;
}

/** Owns one xterm instance + one terminal websocket for its lifetime; remount (via `key`) to reconnect. */
export function Terminal({
  instanceUuid,
  tmuxWheelScrolling = false,
  onConnectionStateChange,
  className = "h-[32rem]",
  label = "Terminal session",
}: Readonly<TerminalProps>) {
  const containerRef = useRef<HTMLElement>(null);
  const onStateChangeRef = useRef(onConnectionStateChange);
  onStateChangeRef.current = onConnectionStateChange;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    const { term, fitAddon } = createTerminal(container);
    const detachClipboard = attachClipboardAndKeys(term);
    const socket = new WebSocket(terminalSocketUrl(instanceUuid));
    const detachWheel = attachTmuxWheel(term, socket, tmuxWheelScrolling);
    const detachSocket = bindSocket(term, fitAddon, socket, onStateChangeRef);

    // A workspace pane changes size without the window changing size: showing a
    // tab, dragging the split separator, or mounting into a container that was
    // zero-width a frame earlier. A hidden or zero-width xterm container is a
    // known mis-fit source, so observe the container itself rather than relying
    // on `window.resize` alone (which stays for browsers mid-teardown).
    const observer = new ResizeObserver(() => fitAddon.fit());
    observer.observe(container);

    function handleWindowResize() {
      fitAddon.fit();
    }
    window.addEventListener("resize", handleWindowResize);

    return () => {
      window.removeEventListener("resize", handleWindowResize);
      observer.disconnect();
      detachWheel();
      detachClipboard();
      detachSocket();
      term.dispose();
    };
    // `onConnectionStateChange` is intentionally read via `onStateChangeRef`
    // (set on every render, above) rather than closed over directly, so an
    // inline callback identity doesn't tear down and reopen the socket every
    // render; only a real `instanceUuid` change (or unmount) should do that.
  }, [instanceUuid, tmuxWheelScrolling]);

  return (
    <section
      ref={containerRef}
      aria-label={label}
      className={cn("overflow-hidden rounded-md border border-white/10 bg-[#0d0d0d] p-2", className)}
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
