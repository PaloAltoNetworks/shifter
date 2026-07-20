import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render } from "@testing-library/react";

import { installFakeWebSocket, latestSocket } from "@/test/fake-websocket";

vi.mock("@xterm/addon-fit", () => {
  class FakeFitAddon {
    fit = vi.fn();
  }
  return { FitAddon: FakeFitAddon };
});

vi.mock("@xterm/xterm", () => {
  class FakeXTerm {
    static instances: FakeXTerm[] = [];
    cols = 80;
    rows = 24;
    open = vi.fn();
    loadAddon = vi.fn();
    write = vi.fn();
    focus = vi.fn();
    dispose = vi.fn();
    onDataCallback: ((data: string) => void) | null = null;
    onResizeCallback: ((size: { cols: number; rows: number }) => void) | null = null;

    constructor() {
      FakeXTerm.instances.push(this);
    }

    onData(callback: (data: string) => void) {
      this.onDataCallback = callback;
      return { dispose: vi.fn() };
    }

    onResize(callback: (size: { cols: number; rows: number }) => void) {
      this.onResizeCallback = callback;
      return { dispose: vi.fn() };
    }
  }
  return { Terminal: FakeXTerm };
});

import { Terminal as XTermCtor } from "@xterm/xterm";

import { Terminal } from "./Terminal";

interface FakeXTermInstance {
  open: ReturnType<typeof vi.fn>;
  write: ReturnType<typeof vi.fn>;
  focus: ReturnType<typeof vi.fn>;
  dispose: ReturnType<typeof vi.fn>;
  onDataCallback: ((data: string) => void) | null;
  onResizeCallback: ((size: { cols: number; rows: number }) => void) | null;
}

function latestTerm(): FakeXTermInstance {
  const instances = (XTermCtor as unknown as { instances: FakeXTermInstance[] }).instances;
  const term = instances.at(-1);
  if (!term) throw new Error("No fake xterm instance was created");
  return term;
}

const INSTANCE_UUID = "22222222-2222-2222-2222-222222222222";

let restoreWebSocket: () => void;

beforeEach(() => {
  restoreWebSocket = installFakeWebSocket();
  (XTermCtor as unknown as { instances: unknown[] }).instances = [];
});

afterEach(() => {
  restoreWebSocket();
});

describe("Terminal", () => {
  it("opens ws(s)://<host>/ws/terminal/<instance_uuid>/ and mounts xterm into the container", () => {
    render(<Terminal instanceUuid={INSTANCE_UUID} />);
    const socket = latestSocket();
    expect(socket.url).toBe(`ws://${window.location.host}/ws/terminal/${INSTANCE_UUID}/`);
    expect(latestTerm().open).toHaveBeenCalled();
  });

  it("sends a resize frame and focuses the terminal once the socket opens", () => {
    render(<Terminal instanceUuid={INSTANCE_UUID} />);
    const socket = latestSocket();
    act(() => socket.emitOpen());

    expect(socket.sent).toContainEqual(JSON.stringify({ type: "resize", cols: 80, rows: 24 }));
    expect(latestTerm().focus).toHaveBeenCalled();
  });

  it("reports the open state via onConnectionStateChange", () => {
    const onConnectionStateChange = vi.fn();
    render(<Terminal instanceUuid={INSTANCE_UUID} onConnectionStateChange={onConnectionStateChange} />);
    act(() => latestSocket().emitOpen());
    expect(onConnectionStateChange).toHaveBeenCalledWith("open", null);
  });

  it("frames keystrokes as SSHConsumer input messages and sends only while open", () => {
    render(<Terminal instanceUuid={INSTANCE_UUID} />);
    const socket = latestSocket();
    const term = latestTerm();

    term.onDataCallback?.("ls -la\n");
    expect(socket.sent).toHaveLength(0); // Not open yet; nothing queued or sent.

    act(() => socket.emitOpen());
    socket.sent.length = 0; // Clear the resize frame sent on open.
    term.onDataCallback?.("ls -la\n");
    expect(socket.sent).toContainEqual(JSON.stringify({ type: "input", data: "ls -la\n" }));
  });

  it("frames a live resize as SSHConsumer resize messages", () => {
    render(<Terminal instanceUuid={INSTANCE_UUID} />);
    const socket = latestSocket();
    act(() => socket.emitOpen());
    socket.sent.length = 0;

    latestTerm().onResizeCallback?.({ cols: 120, rows: 40 });
    expect(socket.sent).toContainEqual(JSON.stringify({ type: "resize", cols: 120, rows: 40 }));
  });

  it("writes SSHConsumer output frames to the terminal", () => {
    render(<Terminal instanceUuid={INSTANCE_UUID} />);
    const socket = latestSocket();
    act(() => socket.emitMessage({ type: "output", data: "$ " }));
    expect(latestTerm().write).toHaveBeenCalledWith("$ ");
  });

  it("ignores malformed or non-output frames without throwing", () => {
    render(<Terminal instanceUuid={INSTANCE_UUID} />);
    const socket = latestSocket();
    expect(() => act(() => socket.emitMessage("not json"))).not.toThrow();
    expect(() => act(() => socket.emitMessage({ type: "status", status: "ready" }))).not.toThrow();
    expect(latestTerm().write).not.toHaveBeenCalled();
  });

  it("reports the closed state with the close code/reason and does not crash", () => {
    const onConnectionStateChange = vi.fn();
    render(<Terminal instanceUuid={INSTANCE_UUID} onConnectionStateChange={onConnectionStateChange} />);
    const socket = latestSocket();
    act(() => socket.emitClose(4502, "SSH connection failed"));
    expect(onConnectionStateChange).toHaveBeenCalledWith("closed", { code: 4502, reason: "SSH connection failed" });
  });

  it("disposes the terminal and cleanly closes the socket on unmount", () => {
    const { unmount } = render(<Terminal instanceUuid={INSTANCE_UUID} />);
    const socket = latestSocket();
    const term = latestTerm();

    unmount();

    expect(term.dispose).toHaveBeenCalled();
    expect(socket.readyState).toBe(3 /* CLOSED */);
  });

  it("remounting with a new key tears down the old socket and opens a fresh one", () => {
    const { rerender } = render(<Terminal key={0} instanceUuid={INSTANCE_UUID} />);
    const first = latestSocket();

    rerender(<Terminal key={1} instanceUuid={INSTANCE_UUID} />);

    expect(first.readyState).toBe(3 /* CLOSED */);
    expect(latestSocket()).not.toBe(first);
  });
});
