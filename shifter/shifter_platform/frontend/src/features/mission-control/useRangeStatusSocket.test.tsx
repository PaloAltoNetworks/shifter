import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";

import { missionControlKeys } from "@/api/mission-control";
import { FakeWebSocket, installFakeWebSocket, latestSocket } from "@/test/fake-websocket";

import { useRangeStatusSocket } from "./useRangeStatusSocket";

const REQUEST_ID = "11111111-1111-1111-1111-111111111111";

let restoreWebSocket: () => void;

beforeEach(() => {
  restoreWebSocket = installFakeWebSocket();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  restoreWebSocket();
});

function renderWithClient(requestId: string | null) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
  const view = renderHook(({ id }: { id: string | null }) => useRangeStatusSocket(id), {
    initialProps: { id: requestId },
    wrapper: ({ children }) => <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>,
  });
  return { ...view, invalidateSpy };
}

describe("useRangeStatusSocket", () => {
  it("is a no-op when requestId is null: no socket opens, reports disconnected", () => {
    const { result } = renderWithClient(null);
    expect(result.current.connected).toBe(false);
    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("opens ws(s)://<host>/ws/range-status/<request_id>/ and reports connected on open", () => {
    const { result } = renderWithClient(REQUEST_ID);
    const socket = latestSocket();
    expect(socket.url).toBe(`ws://${window.location.host}/ws/range-status/${REQUEST_ID}/`);

    act(() => socket.emitOpen());
    expect(result.current.connected).toBe(true);
  });

  it("invalidates the current-range query on a hydrate/delta status message", () => {
    const { invalidateSpy } = renderWithClient(REQUEST_ID);
    const socket = latestSocket();
    act(() => socket.emitOpen());

    act(() => socket.emitMessage({ type: "status", request_id: REQUEST_ID, status: "ready" }));

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: missionControlKeys.currentRange });
  });

  it("invalidates on a delta carrying error_message too (same 'status' framing)", () => {
    const { invalidateSpy } = renderWithClient(REQUEST_ID);
    const socket = latestSocket();
    act(() => socket.emitMessage({ type: "status", request_id: REQUEST_ID, status: "failed", error_message: "boom" }));
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: missionControlKeys.currentRange });
  });

  it("ignores malformed frames without throwing", () => {
    renderWithClient(REQUEST_ID);
    const socket = latestSocket();
    expect(() => act(() => socket.emitMessage("not json"))).not.toThrow();
  });

  it("reconnects after an unexpected close (not in the no-retry set)", () => {
    renderWithClient(REQUEST_ID);
    const first = latestSocket();
    act(() => first.emitOpen());
    act(() => first.emitClose(1006, "abnormal"));

    // Bounded backoff (base 1s, jittered up to the cap) — 5s comfortably covers attempt 0.
    act(() => vi.advanceTimersByTime(5000));

    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it.each([1000, 4001, 4003])("does not reconnect after a no-retry close code %d", (code) => {
    renderWithClient(REQUEST_ID);
    const first = latestSocket();
    act(() => first.emitOpen());
    act(() => first.emitClose(code, "terminal"));

    act(() => vi.advanceTimersByTime(35_000));

    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("reports disconnected after a close, until it reconnects", () => {
    const { result } = renderWithClient(REQUEST_ID);
    const first = latestSocket();
    act(() => first.emitOpen());
    expect(result.current.connected).toBe(true);

    act(() => first.emitClose(1006, "abnormal"));
    expect(result.current.connected).toBe(false);
  });

  it("closes the socket and cancels pending reconnects on unmount", () => {
    const { unmount } = renderWithClient(REQUEST_ID);
    const socket = latestSocket();
    act(() => socket.emitOpen());

    act(() => unmount());

    expect(socket.readyState).toBe(FakeWebSocket.CLOSED);
    act(() => vi.advanceTimersByTime(35_000));
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("closes the old socket and opens a fresh one when requestId changes", () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { rerender } = renderHook(({ id }: { id: string | null }) => useRangeStatusSocket(id), {
      initialProps: { id: REQUEST_ID },
      wrapper: ({ children }) => <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>,
    });
    const first = latestSocket();
    act(() => first.emitOpen());

    const OTHER_ID = "22222222-2222-2222-2222-222222222222";
    act(() => rerender({ id: OTHER_ID }));

    expect(first.readyState).toBe(FakeWebSocket.CLOSED);
    const second = latestSocket();
    expect(second.url).toBe(`ws://${window.location.host}/ws/range-status/${OTHER_ID}/`);
  });
});
