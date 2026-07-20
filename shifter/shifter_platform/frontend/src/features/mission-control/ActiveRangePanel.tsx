import { useEffect, useState } from "react";

import {
  useCancelRange,
  useDownloadRangeVpnProfile,
  useDestroyRange,
  useExtendRange,
  usePauseRange,
  useResumeRange,
} from "@/api/mission-control";
import { describeMutationError } from "@/api/errors";
import type { RangeLease, RangePresentation, RangeStatus } from "@/api/types";
import { rangeStatusMapping } from "@/app/state-map";
import { PageHeader } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { InstanceTable } from "./InstanceTable";
import { useRangeStatusSocket } from "./useRangeStatusSocket";

// Statuses that mean the backend is still working; mirrors the set the
// polling hook (api/mission-control.ts) uses to decide whether to keep
// refetching. Duplicated here (rather than imported) because it drives
// presentation (the progress indicator), not caching policy.
const TRANSIENT_STATUSES: ReadonlySet<RangeStatus> = new Set([
  "pending",
  "provisioning",
  "pausing",
  "resuming",
  "destroying",
]);

type LifecycleDialog = "pause" | "resume" | "cancel" | "destroy" | "extend" | null;

const DIALOG_COPY: Record<
  Exclude<LifecycleDialog, null>,
  { title: string; confirmLabel: string; description: string }
> = {
  pause: {
    title: "Pause range?",
    confirmLabel: "Pause",
    description: "Instances will be stopped but kept. You can resume the range later.",
  },
  resume: {
    title: "Resume range?",
    confirmLabel: "Resume",
    description: "Instances will be started again.",
  },
  cancel: {
    title: "Cancel launch?",
    confirmLabel: "Cancel launch",
    description: "The in-progress range launch will be stopped.",
  },
  destroy: {
    title: "Destroy range?",
    confirmLabel: "Destroy",
    description: "This range and its instances will be permanently destroyed. This cannot be undone.",
  },
  extend: {
    title: "Extend range?",
    confirmLabel: "Extend range",
    description: "The server will add the configured extension, up to this range's maximum lifetime.",
  },
};

const DAY_MS = 24 * 60 * 60 * 1000;
const HOUR_MS = 60 * 60 * 1000;
const MINUTE_MS = 60 * 1000;

function formatTimeRemaining(expiresAt: string, now: number): string {
  const remaining = new Date(expiresAt).valueOf() - now;
  if (remaining <= 0) return "Expires now";
  if (remaining >= DAY_MS) {
    const days = Math.ceil(remaining / DAY_MS);
    return `Expires in ${days} ${days === 1 ? "day" : "days"}`;
  }
  if (remaining >= HOUR_MS) {
    const hours = Math.ceil(remaining / HOUR_MS);
    return `Expires in ${hours} ${hours === 1 ? "hour" : "hours"}`;
  }
  const minutes = Math.max(1, Math.ceil(remaining / MINUTE_MS));
  return `Expires in ${minutes} ${minutes === 1 ? "minute" : "minutes"}`;
}

function formatLeaseTimestamp(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

/**
 * Small, never-color-only live/offline affordance for the range-status socket
 * (advisory only — `useCurrentRange`'s polling `refetchInterval` is the real
 * fallback when the socket is down; see `useRangeStatusSocket`).
 */
function LiveIndicator({ connected }: Readonly<{ connected: boolean }>) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
      <span
        className={cn("size-1.5 rounded-full", connected ? "bg-emerald-500" : "bg-muted-foreground/40")}
        aria-hidden="true"
      />
      {connected ? "Live" : "Offline"}
    </span>
  );
}

function lifecycleActionsFor(range: RangePresentation): Array<{ dialog: LifecycleDialog; label: string }> {
  const actions: Array<{ dialog: LifecycleDialog; label: string }> = [];
  if (range.status === "pending" || range.status === "provisioning") {
    actions.push({ dialog: "cancel", label: "Cancel launch" });
  } else if (range.is_active && range.status !== "destroying") {
    actions.push({ dialog: "destroy", label: "Destroy" });
  }
  if (range.status === "ready") {
    actions.push({ dialog: "pause", label: "Pause" });
  }
  if (range.status === "paused") {
    actions.push({ dialog: "resume", label: "Resume" });
  }
  return actions;
}

function LifecycleActions({
  range,
  onAction,
}: Readonly<{ range: RangePresentation; onAction: (dialog: LifecycleDialog) => void }>) {
  const actions = lifecycleActionsFor(range);
  if (actions.length === 0) return null;
  return (
    <div className="flex shrink-0 items-center gap-2">
      {actions.map((action) => (
        <Button
          key={action.dialog}
          variant={action.dialog === "pause" || action.dialog === "resume" ? "outline" : "destructive"}
          size="sm"
          onClick={() => onAction(action.dialog)}
        >
          {action.label}
        </Button>
      ))}
    </div>
  );
}

function RangeAccessPanel({
  lifecycle,
  vpnProfileAvailable,
  onExtend,
}: Readonly<{
  lifecycle: RangeLease | null;
  vpnProfileAvailable: boolean;
  onExtend: () => void;
}>) {
  const download = useDownloadRangeVpnProfile();
  const downloadError = describeMutationError(download.error, "Could not download the VPN profile.");
  const [now, setNow] = useState(Date.now);

  useEffect(() => {
    const timer = globalThis.setInterval(() => setNow(Date.now()), MINUTE_MS);
    return () => globalThis.clearInterval(timer);
  }, []);

  if (!lifecycle && !vpnProfileAvailable) return null;

  return (
    <Card className="mb-6 p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-sm font-medium">Range lifetime</p>
          {lifecycle ? (
            <>
              <p className="mt-1 text-lg font-semibold">{formatTimeRemaining(lifecycle.expires_at, now)}</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Scheduled cleanup: {formatLeaseTimestamp(lifecycle.expires_at)}. Maximum lifetime: {" "}
                {formatLeaseTimestamp(lifecycle.maximum_expires_at)}.
              </p>
            </>
          ) : (
            <p className="mt-1 text-sm text-muted-foreground">Lifetime information is unavailable.</p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {vpnProfileAvailable ? (
            <Button variant="secondary" onClick={() => download.mutate()} disabled={download.isPending}>
              {download.isPending ? "Downloading…" : "Download VPN profile"}
            </Button>
          ) : null}
          {lifecycle?.can_extend ? (
            <Button variant="outline" onClick={onExtend}>
              Extend by up to {lifecycle.extension_days} days
            </Button>
          ) : null}
        </div>
      </div>
      {vpnProfileAvailable ? (
        <p className="mt-3 text-sm text-muted-foreground">
          The VPN profile is a private credential. Import it into OpenVPN and store it securely.
        </p>
      ) : null}
      {downloadError ? (
        <Alert variant="destructive" className="mt-3">
          <AlertDescription>{downloadError}</AlertDescription>
        </Alert>
      ) : null}
    </Card>
  );
}

/**
 * Renders one active/live range: status chip + realtime socket, the shared
 * instance table, and lifecycle actions behind confirmation. Extracted from
 * `RangeDashboardPage` (#1370) so the dashboard and the range-detail page's
 * active-range branch present the exact same live view instead of two
 * surfaces drifting apart. `title`/`description` are supplied by the caller
 * since the two surfaces use different page copy.
 */
export function ActiveRangePanel({
  range,
  lifecycle,
  vpnProfileAvailable,
  isFetching,
  title,
  description,
}: Readonly<{
  range: RangePresentation;
  lifecycle: RangeLease | null;
  vpnProfileAvailable: boolean;
  isFetching: boolean;
  title: string;
  description: string;
}>) {
  const [dialog, setDialog] = useState<LifecycleDialog>(null);
  const rangeStatusSocket = useRangeStatusSocket(range.request_id);

  const cancelRange = useCancelRange();
  const destroyRange = useDestroyRange();
  const pauseRange = usePauseRange();
  const resumeRange = useResumeRange();
  const extendRange = useExtendRange();

  const mutations = { cancel: cancelRange, destroy: destroyRange, pause: pauseRange, resume: resumeRange } as const;
  let activeMutation: { isPending: boolean; error: unknown } | null = null;
  if (dialog === "extend") {
    activeMutation = extendRange;
  } else if (dialog) {
    activeMutation = mutations[dialog];
  }

  function closeDialog() {
    cancelRange.reset();
    destroyRange.reset();
    pauseRange.reset();
    resumeRange.reset();
    extendRange.reset();
    setDialog(null);
  }

  const mapping = rangeStatusMapping(range.status);
  const transient = TRANSIENT_STATUSES.has(range.status);

  return (
    <>
      <PageHeader
        title={title}
        description={description}
        actions={
          <>
            <LiveIndicator connected={rangeStatusSocket.connected} />
            <StatusChip intent={mapping.intent} label={mapping.label} />
          </>
        }
      />

      {transient ? (
        <div className="mb-4 max-w-xs" aria-hidden="true">
          <Progress value={66} className="h-1.5 animate-pulse" />
        </div>
      ) : null}

      <RangeAccessPanel
        lifecycle={lifecycle}
        vpnProfileAvailable={vpnProfileAvailable}
        onExtend={() => setDialog("extend")}
      />

      <Card className="mb-6 overflow-hidden py-0" aria-busy={isFetching}>
        <InstanceTable instances={range.instances} />
      </Card>

      <div className="flex items-center justify-between gap-4">
        <dl className="text-sm text-muted-foreground">
          <div className="flex gap-2">
            <dt className="font-medium text-foreground">Scenario</dt>
            <dd>{range.scenario_id}</dd>
          </div>
        </dl>
        <LifecycleActions range={range} onAction={setDialog} />
      </div>

      {(Object.keys(DIALOG_COPY) as Array<Exclude<LifecycleDialog, null>>).map((key) => (
        <ConfirmDialog
          key={key}
          open={dialog === key}
          title={DIALOG_COPY[key].title}
          confirmLabel={DIALOG_COPY[key].confirmLabel}
          destructive={key === "cancel" || key === "destroy"}
          pending={dialog === key && activeMutation?.isPending}
          error={dialog === key ? activeMutation?.error : undefined}
          onOpenChange={(open) => {
            if (!open) closeDialog();
          }}
          onConfirm={() => {
            if (key === "extend") {
              extendRange.mutate(undefined, { onSuccess: closeDialog });
            } else {
              mutations[key].mutate({ request_id: range.request_id }, { onSuccess: closeDialog });
            }
          }}
        >
          {DIALOG_COPY[key].description}
        </ConfirmDialog>
      ))}
    </>
  );
}
