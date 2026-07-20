import { Loader2 } from "lucide-react";

import { useCtfRangeStatus, useVpnProfileDownload } from "@/api/ctf";
import { describeMutationError } from "@/api/errors";
import type { CtfRangeStatus } from "@/api/types";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useGuacamoleSession } from "@/features/mission-control/guacamole";

import { titleCase } from "./format";

const READY = "ready";

// One target box in the participant's ready range. Each row owns its own
// Guacamole session hook so pending/error state stays per box (issue #1740),
// mirroring mission-control's InstanceTable.
type CtfTargetInstance = CtfRangeStatus["target_instances"][number];

function TargetBoxRow({ box }: Readonly<{ box: CtfTargetInstance }>) {
  const session = useGuacamoleSession();
  const busy = session.pendingProtocol === "rdp";
  return (
    <TableRow>
      <TableCell className="font-medium">{box.name || "—"}</TableCell>
      <TableCell className="font-mono text-sm text-muted-foreground">{box.private_ip || "—"}</TableCell>
      <TableCell>{titleCase(box.os_type)}</TableCell>
      <TableCell>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={busy || !box.uuid}
          aria-busy={busy}
          aria-label={`Open ${box.name || "range box"} session`}
          onClick={() => session.open({ protocol: "rdp", instanceUuid: box.uuid })}
        >
          {busy ? <Loader2 className="mr-1 size-3.5 animate-spin" aria-hidden="true" /> : null}
          Open
        </Button>
        {session.error ? (
          <p role="alert" className="mt-1 text-xs text-destructive">
            {session.error}
          </p>
        ) : null}
      </TableCell>
    </TableRow>
  );
}

function RangeAccess({ status }: Readonly<{ status: CtfRangeStatus }>) {
  if (status.status !== READY) {
    return (
      <p className="mt-4 text-sm text-muted-foreground">Range access becomes available once your range is ready.</p>
    );
  }

  const boxes = status.target_instances;
  if (boxes.length === 0) {
    return <p className="mt-4 text-sm text-muted-foreground">No target boxes are available in your range yet.</p>;
  }

  return (
    <div className="mt-4">
      <h2 className="mb-2 text-sm font-medium">Target Boxes</h2>
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Name</TableHead>
            <TableHead>IP Address</TableHead>
            <TableHead>OS</TableHead>
            <TableHead>Access</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {boxes.map((box, index) => (
            <TargetBoxRow key={box.uuid || `${box.name}-${index}`} box={box} />
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function VpnProfileDownload({ status }: Readonly<{ status: CtfRangeStatus }>) {
  const download = useVpnProfileDownload();
  const error = describeMutationError(download.error, "Could not download the VPN profile.");

  if (status.status !== READY || !status.vpn_profile_available) return null;

  return (
    <div className="mt-3">
      <Button variant="secondary" onClick={() => download.mutate()} disabled={download.isPending}>
        {download.isPending ? "Downloading…" : "Download VPN profile"}
      </Button>
      <p className="mt-2 text-sm text-muted-foreground">
        This file is a private credential. Import it into a standard OpenVPN client and store it securely.
      </p>
      {error ? (
        <Alert variant="destructive" className="mt-3">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
    </div>
  );
}

export function RangePage() {
  const query = useCtfRangeStatus();

  if (query.isLoading) {
    return (
      <>
        <PageHeader title="Range" />
        <Skeleton className="h-40 w-full" />
      </>
    );
  }

  if (query.isError || !query.data) {
    return (
      <>
        <PageHeader title="Range" />
        <Alert variant="destructive">
          <AlertTitle>Could not load range status</AlertTitle>
          <AlertDescription>Please retry.</AlertDescription>
        </Alert>
      </>
    );
  }

  const status = query.data;

  return (
    <>
      <PageHeader title="Range" description="Your dedicated range for this event" />
      <Card>
        <CardContent>
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">Status</span>
            <Badge variant="secondary">{titleCase(status.status)}</Badge>
          </div>
          {status.range_instance_id === null ? null : (
            <p className="mt-2 text-sm text-muted-foreground">Range instance #{status.range_instance_id}</p>
          )}
          <RangeAccess status={status} />
          <VpnProfileDownload status={status} />
        </CardContent>
      </Card>
    </>
  );
}
