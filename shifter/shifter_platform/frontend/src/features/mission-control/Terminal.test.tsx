import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { installFakeWebSocket, latestSocket } from "@/test/fake-websocket";

vi.mock("@xterm/addon-fit", () => {
  class FakeFitAddon {
    static instances: FakeFitAddon[] = [];
    fit = vi.fn();

    constructor() {
      FakeFitAddon.instances.push(this);
    }
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
    element = document.createElement("div");
    getSelection = vi.fn(() => "");
    paste = vi.fn();
    attachCustomKeyEventHandler = vi.fn();
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

import { FitAddon as FitAddonCtor } from "@xterm/addon-fit";
import { Terminal as XTermCtor } from "@xterm/xterm";

import { ResizeObserverStub } from "@/test/setup";

import { Terminal } from "./Terminal";

function latestFitAddon(): { fit: ReturnType<typeof vi.fn> } {
  const instances = (FitAddonCtor as unknown as { instances: { fit: ReturnType<typeof vi.fn> }[] }).instances;
  const addon = instances.at(-1);
  if (!addon) throw new Error("No fake fit addon was created");
  return addon;
}

function latestResizeObserver(): ResizeObserverStub {
  const observer = ResizeObserverStub.instances.at(-1);
  if (!observer) throw new Error("No ResizeObserver was constructed");
  return observer;
}

interface FakeXTermInstance {
  element: HTMLElement;
  open: ReturnType<typeof vi.fn>;
  write: ReturnType<typeof vi.fn>;
  focus: ReturnType<typeof vi.fn>;
  dispose: ReturnType<typeof vi.fn>;
  getSelection: ReturnType<typeof vi.fn>;
  paste: ReturnType<typeof vi.fn>;
  attachCustomKeyEventHandler: ReturnType<typeof vi.fn>;
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
let clipboardReadText: ReturnType<typeof vi.fn>;
let clipboardWriteText: ReturnType<typeof vi.fn>;

beforeEach(() => {
  restoreWebSocket = installFakeWebSocket();
  (XTermCtor as unknown as { instances: unknown[] }).instances = [];
  (FitAddonCtor as unknown as { instances: unknown[] }).instances = [];
  ResizeObserverStub.instances.length = 0;
  clipboardReadText = vi.fn(() => Promise.resolve("clipboard input"));
  clipboardWriteText = vi.fn(() => Promise.resolve());
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { readText: clipboardReadText, writeText: clipboardWriteText },
  });
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

  it("fills a caller-supplied container height so a workspace pane can size it", () => {
    const { container } = render(<Terminal instanceUuid={INSTANCE_UUID} className="h-full" />);
    const surface = container.querySelector("section");
    expect(surface).toHaveClass("h-full");
    expect(surface).not.toHaveClass("h-[32rem]");
  });

  it("names its region from the caller so two panes are not duplicate landmarks", () => {
    render(<Terminal instanceUuid={INSTANCE_UUID} label="Left pane: web-01" />);
    expect(screen.getByRole("region", { name: "Left pane: web-01" })).toBeInTheDocument();
  });

  it("falls back to a generic region name for the standalone page", () => {
    render(<Terminal instanceUuid={INSTANCE_UUID} />);
    expect(screen.getByRole("region", { name: "Terminal session" })).toBeInTheDocument();
  });

  it("keeps the standalone fixed height when no className is supplied", () => {
    const { container } = render(<Terminal instanceUuid={INSTANCE_UUID} />);
    expect(container.querySelector("section")).toHaveClass("h-[32rem]");
  });

  it("refits xterm when its container resizes, not only on window resize", () => {
    render(<Terminal instanceUuid={INSTANCE_UUID} />);
    const fitAddon = latestFitAddon();
    const observer = latestResizeObserver();

    const fitsAfterMount = fitAddon.fit.mock.calls.length;
    act(() => observer.trigger());

    expect(fitAddon.fit.mock.calls.length).toBeGreaterThan(fitsAfterMount);
  });

  it("disconnects the container observer on unmount", () => {
    const { unmount } = render(<Terminal instanceUuid={INSTANCE_UUID} />);
    const observer = latestResizeObserver();
    expect(observer.observed.size).toBe(1);

    unmount();
    expect(observer.observed.size).toBe(0);
  });

  it("does not read or send the clipboard on right-click", async () => {
    // Ranges are adversary-simulation environments: a hostile or compromised
    // instance can prompt a user to right-click. Auto-pasting on contextmenu
    // would silently ship whatever is on the workstation clipboard
    // (passwords, cloud creds) into the remote shell with no browser-visible
    // indication. Paste must stay an explicit, user-understood gesture.
    render(<Terminal instanceUuid={INSTANCE_UUID} />);
    const term = latestTerm();
    const socket = latestSocket();
    act(() => socket.emitOpen());
    socket.sent.length = 0;

    fireEvent.contextMenu(term.element);
    await Promise.resolve();

    expect(clipboardReadText).not.toHaveBeenCalled();
    expect(term.paste).not.toHaveBeenCalled();
    expect(socket.sent).toHaveLength(0);
  });

  it("still pastes on the explicit Ctrl+Shift+V gesture", async () => {
    render(<Terminal instanceUuid={INSTANCE_UUID} />);
    const term = latestTerm();
    const handler = term.attachCustomKeyEventHandler.mock.calls[0][0] as (event: KeyboardEvent) => boolean;

    const handled = handler({ type: "keydown", ctrlKey: true, shiftKey: true, key: "V" } as KeyboardEvent);
    await Promise.resolve();
    await Promise.resolve();

    expect(handled).toBe(false);
    expect(clipboardReadText).toHaveBeenCalled();
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

  it("copies a completed mouse selection to the browser clipboard", async () => {
    render(<Terminal instanceUuid={INSTANCE_UUID} />);
    const term = latestTerm();
    term.getSelection.mockReturnValue("selected output");

    fireEvent.mouseUp(term.element);

    await waitFor(() => expect(clipboardWriteText).toHaveBeenCalledWith("selected output"));
  });

  it("supports Ctrl+Shift+C and Ctrl+Shift+V clipboard shortcuts", async () => {
    render(<Terminal instanceUuid={INSTANCE_UUID} />);
    const term = latestTerm();
    term.getSelection.mockReturnValue("keyboard selection");
    const keyHandler = term.attachCustomKeyEventHandler.mock.calls[0]?.[0] as (event: KeyboardEvent) => boolean;

    expect(keyHandler(new KeyboardEvent("keydown", { key: "c", ctrlKey: true, shiftKey: true }))).toBe(false);
    expect(keyHandler(new KeyboardEvent("keydown", { key: "v", ctrlKey: true, shiftKey: true }))).toBe(false);

    await waitFor(() => expect(clipboardWriteText).toHaveBeenCalledWith("keyboard selection"));
    await waitFor(() => expect(term.paste).toHaveBeenCalledWith("clipboard input"));
  });

  it("bridges CTF wheel gestures to tmux copy-mode keys without affecting ordinary terminals", () => {
    const { unmount } = render(<Terminal instanceUuid={INSTANCE_UUID} tmuxWheelScrolling />);
    const socket = latestSocket();
    const term = latestTerm();
    act(() => socket.emitOpen());
    socket.sent.length = 0;

    fireEvent.wheel(term.element, { deltaY: -100 });

    expect(socket.sent).toContainEqual(JSON.stringify({ type: "input", data: "\u001b[23~" }));
    unmount();

    render(<Terminal instanceUuid={INSTANCE_UUID} />);
    const ordinarySocket = latestSocket();
    const ordinaryTerm = latestTerm();
    act(() => ordinarySocket.emitOpen());
    ordinarySocket.sent.length = 0;
    fireEvent.wheel(ordinaryTerm.element, { deltaY: -100 });
    expect(ordinarySocket.sent).toHaveLength(0);
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
