/**
 * Live-projection hook for range status (#1370).
 *
 * Opens `ws(s)://<host>/ws/range-status/<request_id>/`
 * (`mission_control/routing.py` -> `RangeStatusConsumer`,
 * `mission_control/status_consumers.py`). The consumer hydrates on connect and
 * streams deltas, both framed identically:
 *
 *   { "type": "status", "request_id": "<uuid>", "status": "<ResourceStatus>", "error_message"?: string }
 *
 * Per the #1370 preflight guardrails, this socket is ADVISORY / live-projection
 * only, never authority: on any `status` message this hook invalidates the
 * `useCurrentRange` query so the canonical `/api/v1/mission-control/range/`
 * read re-fetches — it never stores range data itself, and a dead/unavailable
 * socket just leaves `useCurrentRange`'s bounded `refetchInterval` polling as
 * the fallback (which already runs whenever the range is in a transient
 * status; see `api/mission-control.ts`).
 *
 * Reconnects with bounded exponential backoff + equal jitter, mirroring the
 * legacy `static/js/dashboard.js` `DashboardManager` (`_getRetryDelay` /
 * `_scheduleRetry`): base 1s, capped at 30s, up to 5 attempts. Close codes that
 * mean "don't retry" mirror `cyberscript.enums.WebSocketCloseCode`: NORMAL
 * (1000, clean/intentional close), NOT_AUTHENTICATED (4001), and
 * PERMISSION_DENIED (4003) — the same set `dashboard.js` treats as terminal.
 */
import { useEffect, useState } from "react";

import { useQueryClient } from "@tanstack/react-query";

import { missionControlKeys } from "@/api/mission-control";

const MAX_RECONNECT_ATTEMPTS = 5;
const BASE_DELAY_MS = 1000;
const MAX_DELAY_MS = 30_000;

// cyberscript.enums.WebSocketCloseCode: NORMAL, NOT_AUTHENTICATED, PERMISSION_DENIED.
const NO_RETRY_CLOSE_CODES: ReadonlySet<number> = new Set([1000, 4001, 4003]);

function randomFraction(): number {
  const buf = new Uint32Array(1);
  crypto.getRandomValues(buf);
  return buf[0] / 2 ** 32;
}

/** Exponential backoff capped at MAX_DELAY_MS, with equal jitter (half fixed, half random). */
function retryDelayMs(attempt: number): number {
  const cap = Math.min(BASE_DELAY_MS * 2 ** attempt, MAX_DELAY_MS);
  return Math.round(cap / 2 + randomFraction() * (cap / 2));
}

function rangeStatusSocketUrl(requestId: string): string {
  const protocol = globalThis.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${globalThis.location.host}/ws/range-status/${requestId}/`;
}

export interface RangeStatusSocket {
  /** Advisory connectivity indicator for a small live/offline affordance. */
  readonly connected: boolean;
}

/** No-op when `requestId` is null (no active range to watch). */
export function useRangeStatusSocket(requestId: string | null): RangeStatusSocket {
  const queryClient = useQueryClient();
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (!requestId) {
      setConnected(false);
      return;
    }

    let cancelled = false;
    let socket: WebSocket | null = null;
    let retryTimeout: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;

    function connect() {
      if (cancelled) return;
      const ws = new WebSocket(rangeStatusSocketUrl(requestId as string));
      socket = ws;

      ws.onopen = () => {
        if (cancelled) return;
        attempt = 0;
        setConnected(true);
      };

      ws.onmessage = (event) => {
        if (cancelled) return;
        let message: { type?: string } | null = null;
        try {
          message = JSON.parse(event.data as string) as { type?: string };
        } catch {
          return; // Malformed frame; the polling fallback still covers us.
        }
        if (message?.type === "status") {
          queryClient.invalidateQueries({ queryKey: missionControlKeys.currentRange });
        }
      };

      ws.onclose = (event) => {
        if (cancelled) return;
        setConnected(false);
        if (NO_RETRY_CLOSE_CODES.has(event.code) || attempt >= MAX_RECONNECT_ATTEMPTS) {
          return;
        }
        const delay = retryDelayMs(attempt);
        attempt += 1;
        retryTimeout = setTimeout(connect, delay);
      };

      ws.onerror = () => {
        // Swallow; `onclose` fires immediately after and drives reconnect/backoff.
      };
    }

    connect();

    return () => {
      cancelled = true;
      if (retryTimeout) clearTimeout(retryTimeout);
      const ws = socket;
      if (ws) {
        ws.onopen = null;
        ws.onmessage = null;
        ws.onerror = null;
        ws.onclose = null;
        ws.close(1000, "component unmounted");
      }
    };
  }, [requestId, queryClient]);

  return { connected };
}
