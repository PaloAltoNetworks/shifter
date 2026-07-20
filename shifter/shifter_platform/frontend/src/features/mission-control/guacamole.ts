/**
 * Guacamole RDP/SSH session bootstrap (#1370).
 *
 * Server-brokered flow only, matching the legacy
 * `static/js/terminal-guacamole.js` poll/open sequence exactly:
 *
 *   1. POST to queue the bootstrap and get back a `request_id`. Two callers
 *      share this module: range instances go through `useRequestGuacamoleUrl`
 *      (`/mission-control/guacamole/{rdp,ssh}-url/`, keyed by instance uuid)
 *      and NGFWs go through `useNgfwSshUrl`
 *      (`/mission-control/ngfw/<app_id>/ssh-url/`, keyed by app id). Both
 *      endpoints return the identical `GuacamoleBootstrapQueued` envelope
 *      (`mission_control/api/guacamole.py` `GuacamoleNGFWSSHURLView` reuses
 *      `_range_bootstrap_response`), so the poll/open half below is
 *      target-agnostic.
 *   2. Poll `GET /mission-control/guacamole/bootstrap/<request_id>/`
 *      (`mission_control/api/urls.py` `guacamole-bootstrap-status`) once a
 *      second, up to 60 attempts (~1 minute), until the response carries a
 *      terminal `url` (succeeded) or `error` (failed/expired).
 *   3. Open the one-time signed URL with
 *      `window.open(url, "_blank", "noopener,noreferrer")`.
 *
 * The status endpoint also sends a `Retry-After: 1` response header
 * (`mission_control/api/guacamole.py` `_status_response`); it is hard-coded to
 * 1s server-side today, so the fixed 1s poll interval below already honors it.
 * `apiFetch` only returns the parsed body (no header access), so if the
 * backend ever varies that header this poll would need `apiFetch` to expose
 * response headers.
 *
 * The signed URL is never stored, logged, or returned from this module beyond
 * the single `window.open` call — no bounce through component state.
 * Mutations never auto-retry (ADR-029 / `api/queryClient.ts`): a failed
 * attempt surfaces its error and requires an explicit user retry (a fresh
 * `open()` call), matching the "no auto-retry" guardrail.
 */
import { useCallback, useRef, useState } from "react";

import { ApiError } from "@/api/errors";
import { apiFetch } from "@/api/client";
import { useNgfwSshUrl, useRequestGuacamoleUrl, type GuacamoleProtocol } from "@/api/mission-control";
import type { GuacamoleBootstrapQueued, GuacamoleBootstrapStatus } from "@/api/types";

const POLL_INTERVAL_MS = 1000;
const POLL_ATTEMPTS = 60;

const PROTOCOL_LABEL: Record<GuacamoleProtocol, string> = { rdp: "RDP", ssh: "SSH" };

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function bootstrapStatusPath(requestId: string): string {
  return `/mission-control/guacamole/bootstrap/${requestId}/`;
}

/** Poll the bootstrap status endpoint until it resolves a signed URL or fails. */
async function pollForSignedUrl(requestId: string, label: string): Promise<string> {
  for (let attempt = 0; attempt < POLL_ATTEMPTS; attempt += 1) {
    let status: GuacamoleBootstrapStatus;
    try {
      status = await apiFetch<GuacamoleBootstrapStatus>(bootstrapStatusPath(requestId));
    } catch (error) {
      // A 410 (expired) or other terminal HTTP error from the status endpoint
      // ends the poll rather than retrying against a dead bootstrap request.
      throw new Error(error instanceof ApiError ? error.message : `Failed to generate ${label} URL`);
    }
    if (status.url) {
      return status.url;
    }
    if (status.error) {
      throw new Error(status.error);
    }
    await delay(POLL_INTERVAL_MS);
  }
  throw new Error(`${label} session request timed out`);
}

export type GuacamoleSessionState = "idle" | "preparing" | "error";

/** Derive the session state from whether a bootstrap is pending and the last error, if any. */
function sessionState(isPending: boolean, error: string | null): GuacamoleSessionState {
  if (isPending) return "preparing";
  if (error) return "error";
  return "idle";
}

interface BootstrapRunArgs {
  /** Queue the bootstrap (the target-specific POST); resolves to the queued envelope. */
  queue: () => Promise<GuacamoleBootstrapQueued>;
  /** Human label used in poll-timeout / generic-failure messages ("SSH", "RDP"). */
  label: string;
  /** Called once the run settles (success or failure), before `error`/`busy` update. */
  onSettled?: () => void;
}

/**
 * Target-agnostic "queue one bootstrap, poll it, open the signed URL"
 * runner. One bootstrap in flight per hook instance (a ref, not React state,
 * so a synchronous second `run()` call is rejected even before this hook's
 * own re-render lands) — callers layer their own per-target key (protocol,
 * app id, ...) over `busy`/`error` if they need finer-grained UI state.
 */
function useBootstrapOpener() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inFlightRef = useRef(false);

  const run = useCallback(({ queue, label, onSettled }: BootstrapRunArgs): boolean => {
    if (inFlightRef.current) return false;
    inFlightRef.current = true;
    setBusy(true);
    setError(null);

    void (async () => {
      try {
        const queued = await queue();
        const url = await pollForSignedUrl(queued.request_id, label);
        window.open(url, "_blank", "noopener,noreferrer");
      } catch (err) {
        setError(err instanceof Error ? err.message : `Failed to open ${label} session.`);
      } finally {
        inFlightRef.current = false;
        setBusy(false);
        onSettled?.();
      }
    })();

    return true;
  }, []);

  return { busy, error, run };
}

export interface GuacamoleSession {
  /** Which protocol is currently bootstrapping on this hook instance, if any. */
  pendingProtocol: GuacamoleProtocol | null;
  state: GuacamoleSessionState;
  /** User-facing message from the most recent failed attempt, if any. */
  error: string | null;
  /** Queue a bootstrap, poll it, and open the resulting session in a new tab. */
  open: (args: { protocol: GuacamoleProtocol; instanceUuid: string }) => void;
}

/**
 * Own one bootstrap-in-flight per hook instance. Callers that render one
 * instance table row per hook call get independent busy/error state per row
 * (and per protocol column within a row, via `pendingProtocol`).
 */
export function useGuacamoleSession(): GuacamoleSession {
  const requestGuacamoleUrl = useRequestGuacamoleUrl();
  const [pendingProtocol, setPendingProtocol] = useState<GuacamoleProtocol | null>(null);
  const opener = useBootstrapOpener();

  const open = useCallback(
    ({ protocol, instanceUuid }: { protocol: GuacamoleProtocol; instanceUuid: string }) => {
      const started = opener.run({
        queue: () => requestGuacamoleUrl.mutateAsync({ protocol, instanceUuid }),
        label: PROTOCOL_LABEL[protocol],
        onSettled: () => setPendingProtocol(null),
      });
      if (started) setPendingProtocol(protocol);
    },
    [opener, requestGuacamoleUrl],
  );

  return {
    pendingProtocol,
    state: sessionState(pendingProtocol !== null, opener.error),
    error: opener.error,
    open,
  };
}

export interface NgfwSshSession {
  state: GuacamoleSessionState;
  /** User-facing message from the most recent failed attempt, if any. */
  error: string | null;
  /** Queue an SSH bootstrap for the given NGFW app id, poll it, and open it in a new tab. */
  open: (appId: string) => void;
}

/**
 * NGFW-CLI counterpart to `useGuacamoleSession`, keyed by app id instead of
 * instance uuid (`GuacamoleNGFWSSHURLView`, `/mission-control/ngfw/<app_id>/
 * ssh-url/`). Shares the same queue/poll/open runner so both surfaces honor
 * identical timeout, error, and no-auto-retry behavior.
 */
export function useNgfwSshSession(): NgfwSshSession {
  const requestNgfwSshUrl = useNgfwSshUrl();
  const opener = useBootstrapOpener();

  const open = useCallback(
    (appId: string) => {
      opener.run({
        queue: () => requestNgfwSshUrl.mutateAsync(appId),
        label: "SSH",
      });
    },
    [opener, requestNgfwSshUrl],
  );

  return {
    state: sessionState(opener.busy, opener.error),
    error: opener.error,
    open,
  };
}
