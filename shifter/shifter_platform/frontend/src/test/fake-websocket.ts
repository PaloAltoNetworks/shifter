/**
 * Minimal `WebSocket` test double (#1370).
 *
 * The mission-control realtime hook/components open a socket inside a
 * `useEffect` and drive state off `onopen`/`onmessage`/`onclose`. jsdom's test
 * environment has a real global `WebSocket` (Node 22+), so without this double
 * a mounted component would attempt a real (failing) network connection.
 * `installFakeWebSocket()` swaps `globalThis.WebSocket` for this double so
 * tests can drive the connection lifecycle deterministically from the
 * "server" side via `emitOpen` / `emitMessage` / `emitClose`.
 */
type OpenListener = ((event: Event) => void) | null;
type MessageListener = ((event: MessageEvent) => void) | null;
type CloseListener = ((event: CloseEvent) => void) | null;

export class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  /** Every socket constructed while installed, in creation order. */
  static readonly instances: FakeWebSocket[] = [];

  readonly url: string;
  readyState: number = FakeWebSocket.CONNECTING;
  readonly sent: string[] = [];

  onopen: OpenListener = null;
  onmessage: MessageListener = null;
  onclose: CloseListener = null;
  onerror: OpenListener = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  /** Mirrors the real `close()`: triggers `onclose` (tests never rely on this for server-initiated closes; use `emitClose`). */
  close(code = 1000, reason = ""): void {
    if (this.readyState === FakeWebSocket.CLOSED) return;
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.({ code, reason } as CloseEvent);
  }

  /** Test-only: simulate the server accepting the connection. */
  emitOpen(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.(new Event("open"));
  }

  /** Test-only: simulate a server text frame. Objects are JSON-encoded. */
  emitMessage(data: unknown): void {
    const payload = typeof data === "string" ? data : JSON.stringify(data);
    this.onmessage?.({ data: payload } as MessageEvent);
  }

  /** Test-only: simulate the server (or network) closing the connection. */
  emitClose(code = 1000, reason = ""): void {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.({ code, reason } as CloseEvent);
  }
}

/** Install the double; returns a restore function for `afterEach`. */
export function installFakeWebSocket(): () => void {
  const original = globalThis.WebSocket;
  FakeWebSocket.instances.length = 0;
  // @ts-expect-error -- test double is intentionally narrower than lib.dom's WebSocket.
  globalThis.WebSocket = FakeWebSocket;
  return () => {
    globalThis.WebSocket = original;
  };
}

/** The most recently constructed fake socket; throws if none exists yet. */
export function latestSocket(): FakeWebSocket {
  const socket = FakeWebSocket.instances.at(-1);
  if (!socket) {
    throw new Error("No FakeWebSocket instance was created");
  }
  return socket;
}
