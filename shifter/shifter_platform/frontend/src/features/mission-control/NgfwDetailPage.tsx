import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Loader2 } from "lucide-react";

import { ApiError } from "@/api/errors";
import { useNgfwList } from "@/api/mission-control";
import type { NGFWListItem } from "@/api/types";
import { rangeStatusMapping } from "@/app/state-map";
import { PageHeader } from "@/components/page-header";
import { StatusChip } from "@/components/status-chip";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

import { formatTimestamp } from "./format";
import { useNgfwSshSession } from "./guacamole";
import { NgfwDestroyDialog } from "./NgfwDestroyDialog";
import { missionControlNgfwListPath } from "./routes";

function Breadcrumb({ current }: Readonly<{ current: string }>) {
  return (
    <nav className="mb-3 text-sm text-muted-foreground" aria-label="Breadcrumb">
      <Link className="hover:text-foreground" to={missionControlNgfwListPath()}>
        NGFWs
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

/** CLI (SSH) access card, shown only once the NGFW is ready — mirrors the legacy detail page. */
function CliAccessCard({ appId }: Readonly<{ appId: string }>) {
  const session = useNgfwSshSession();
  const busy = session.state === "preparing";

  return (
    <Card className="mb-6">
      <CardHeader>
        <CardTitle>CLI access</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <p className="text-sm text-muted-foreground">Open the PAN-OS command line interface via SSH.</p>
        <div>
          <Button type="button" disabled={busy} aria-busy={busy} onClick={() => session.open(appId)}>
            {busy ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : null}
            {busy ? "Opening…" : "Open CLI"}
          </Button>
        </div>
        {session.error ? (
          <p role="alert" className="text-sm text-destructive">
            {session.error}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function NgfwOverview({ ngfw }: Readonly<{ ngfw: NGFWListItem }>) {
  const navigate = useNavigate();
  const [destroyOpen, setDestroyOpen] = useState(false);
  const mapping = rangeStatusMapping(ngfw.status);

  return (
    <>
      <Breadcrumb current={ngfw.name} />
      <PageHeader
        title={ngfw.name}
        description="NGFW detail"
        actions={<StatusChip intent={mapping.intent} label={mapping.label} />}
      />

      <Card className="mb-6 overflow-hidden py-0">
        <dl>
          <MetadataRow label="Serial number" value={ngfw.serial_number ?? "Pending provisioning"} />
          <MetadataRow label="Created" value={formatTimestamp(ngfw.created_at)} />
        </dl>
      </Card>

      {ngfw.status === "ready" ? <CliAccessCard appId={ngfw.id} /> : null}

      <Card className="border-destructive/40">
        <CardHeader>
          <CardTitle>Danger zone</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="mb-3 text-sm text-muted-foreground">
            Deprovisioning destroys this NGFW and deactivates its license. Credits are returned to your pool. This
            cannot be undone.
          </p>
          <Button type="button" variant="destructive" size="sm" onClick={() => setDestroyOpen(true)}>
            Deprovision NGFW
          </Button>
        </CardContent>
      </Card>

      <NgfwDestroyDialog
        ngfw={ngfw}
        open={destroyOpen}
        onOpenChange={setDestroyOpen}
        onDestroyed={() => navigate(missionControlNgfwListPath())}
      />
    </>
  );
}

function NotFoundNgfw() {
  return (
    <>
      <Breadcrumb current="Not found" />
      <Alert variant="destructive">
        <AlertTitle>NGFW not found</AlertTitle>
        <AlertDescription>
          This NGFW does not exist or is no longer available.{" "}
          <Link className="underline" to={missionControlNgfwListPath()}>
            Back to NGFWs
          </Link>
          .
        </AlertDescription>
      </Alert>
    </>
  );
}

/**
 * One NGFW identified by the `:appId` route param (#1370). There is no
 * dedicated per-NGFW detail GET endpoint, so — mirroring `RangeDetailPage`'s
 * approach for ranges — this resolves the NGFW from `useNgfwList()`, whose
 * `NGFWListItem` projection is also all the legacy detail page's "Overview"
 * section renders beyond linked-ranges data this API surface does not expose.
 */
export function NgfwDetailPage() {
  const { appId } = useParams<{ appId: string }>();
  const query = useNgfwList();

  if (query.isLoading) {
    return (
      <>
        <PageHeader title="NGFW" description="NGFW detail" />
        <div className="space-y-3">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-40 w-full" />
        </div>
      </>
    );
  }

  if (query.isError) {
    const message = query.error instanceof ApiError ? query.error.message : "Please retry.";
    return (
      <>
        <PageHeader title="NGFW" description="NGFW detail" />
        <Alert variant="destructive">
          <AlertTitle>Could not load this NGFW</AlertTitle>
          <AlertDescription>{message}</AlertDescription>
        </Alert>
      </>
    );
  }

  const ngfw = query.data?.ngfws.find((entry) => entry.id === appId);
  if (!ngfw) {
    return <NotFoundNgfw />;
  }

  return <NgfwOverview ngfw={ngfw} />;
}
