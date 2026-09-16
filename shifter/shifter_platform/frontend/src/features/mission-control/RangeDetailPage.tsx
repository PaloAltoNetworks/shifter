import { Link, useParams } from "react-router";

import { ApiError } from "@/api/errors";
import { useCurrentRange, useRangeHistory } from "@/api/mission-control";
import type { RangeHistory } from "@/api/types";
import { rangeStatusMapping } from "@/app/state-map";
import { PageHeader } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

import { ActiveRangePanel } from "./ActiveRangePanel";
import { formatTimestamp } from "./format";
import { missionControlHistoryPath } from "./routes";

function Breadcrumb({ current }: Readonly<{ current: string }>) {
  return (
    <nav className="mb-3 text-sm text-muted-foreground" aria-label="Breadcrumb">
      <Link className="hover:text-foreground" to={missionControlHistoryPath()}>
        Ranges
      </Link>
      <span className="px-1.5">/</span>
      <span className="text-foreground">{current}</span>
    </nav>
  );
}

function MetadataRow({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-border/60 px-4 py-3 last:border-0">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="font-mono text-sm">{value}</dd>
    </div>
  );
}

/**
 * A past range resolved from `useRangeHistory()`. There is no dedicated
 * per-range detail endpoint (by design, #1370 preflight): the only live
 * instance/connection data the backend exposes is for the single active
 * range, so a historical entry can only ever render the metadata the history
 * list already carries.
 */
function HistoricalRangeView({ entry }: Readonly<{ entry: RangeHistory }>) {
  const mapping = rangeStatusMapping(entry.status);
  return (
    <>
      <Breadcrumb current={entry.scenario_id} />
      <PageHeader
        title={entry.scenario_id}
        description="Past range"
        actions={<StatusChip intent={mapping.intent} label={mapping.label} />}
      />

      <Alert className="mb-6">
        <AlertTitle>Live view unavailable</AlertTitle>
        <AlertDescription>
          Live instances and connections are only available for your active range. Past ranges are typically
          destroyed and no longer have running instances to connect to.
        </AlertDescription>
      </Alert>

      <Card className="overflow-hidden py-0">
        <dl>
          {entry.request_id ? <MetadataRow label="Request ID" value={entry.request_id} /> : null}
          {entry.range_id == null ? null : <MetadataRow label="Range ID" value={String(entry.range_id)} />}
          <MetadataRow label="Created" value={formatTimestamp(entry.created_at)} />
          <MetadataRow label="Updated" value={formatTimestamp(entry.updated_at)} />
        </dl>
      </Card>
    </>
  );
}

function NotFoundRange() {
  return (
    <>
      <Breadcrumb current="Not found" />
      <Alert variant="destructive">
        <AlertTitle>Range not found</AlertTitle>
        <AlertDescription>
          This range does not exist or is no longer available.{" "}
          <Link className="underline" to={missionControlHistoryPath()}>
            Back to ranges
          </Link>
          .
        </AlertDescription>
      </Alert>
    </>
  );
}

/**
 * One range identified by the `:requestId` route param (#1370). There is no
 * dedicated per-range detail endpoint by design: when the id matches the
 * single active range (`useCurrentRange`), this renders the full live view
 * (shared with the dashboard via `ActiveRangePanel`); otherwise it resolves
 * the id from `useRangeHistory` and renders the available metadata with a
 * note that live access is active-range-only.
 */
export function RangeDetailPage() {
  const { requestId } = useParams<{ requestId: string }>();
  const currentRange = useCurrentRange();
  const history = useRangeHistory();

  if (currentRange.isLoading || history.isLoading) {
    return (
      <>
        <PageHeader title="Range" description="Range detail" />
        <div className="space-y-3">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-40 w-full" />
        </div>
      </>
    );
  }

  if (currentRange.isError || history.isError) {
    const error = currentRange.error ?? history.error;
    const message = error instanceof ApiError ? error.message : "Please retry.";
    return (
      <>
        <PageHeader title="Range" description="Range detail" />
        <Alert variant="destructive">
          <AlertTitle>Could not load this range</AlertTitle>
          <AlertDescription>{message}</AlertDescription>
        </Alert>
      </>
    );
  }

  const activeRange = currentRange.data?.has_range ? (currentRange.data.range ?? null) : null;
  if (activeRange && activeRange.request_id === requestId) {
    return (
      <>
        <Breadcrumb current={activeRange.scenario_id} />
        <ActiveRangePanel
          range={activeRange}
          lifecycle={currentRange.data?.lifecycle ?? null}
          vpnProfileAvailable={currentRange.data?.vpn_profile_available ?? false}
          isFetching={currentRange.isFetching}
          title={activeRange.scenario_id}
          description="Live range detail"
        />
      </>
    );
  }

  const historyEntry = history.data?.ranges.find((entry) => entry.request_id === requestId);
  if (historyEntry) {
    return <HistoricalRangeView entry={historyEntry} />;
  }

  return <NotFoundRange />;
}
