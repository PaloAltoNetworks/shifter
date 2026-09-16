import { Link } from "react-router";

import { Loader2 } from "lucide-react";

import type { InstancePresentation } from "@/api/types";
import { Button, buttonVariants } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

import { isConsoleCapable } from "./consoleTargets";
import { useGuacamoleSession, type GuacamoleSession } from "./guacamole";
import { missionControlTerminalPath } from "./routes";

function titleCase(value: string): string {
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}

function GuacamoleButton({
  label,
  protocol,
  instanceUuid,
  session,
}: Readonly<{
  label: string;
  protocol: "rdp" | "ssh";
  instanceUuid: string;
  session: GuacamoleSession;
}>) {
  const busy = session.pendingProtocol === protocol;
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      disabled={busy}
      aria-busy={busy}
      aria-label={`Open ${label} session`}
      onClick={() => session.open({ protocol, instanceUuid })}
    >
      {busy ? <Loader2 className="size-3.5 animate-spin" aria-hidden="true" /> : null}
      {label}
    </Button>
  );
}

function InstanceActions({ instance }: Readonly<{ instance: InstancePresentation }>) {
  const session = useGuacamoleSession();

  if (!isConsoleCapable(instance)) {
    return <span className="text-sm text-muted-foreground">Managed via NGFW</span>;
  }

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <Link
          to={missionControlTerminalPath(instance.uuid)}
          className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
          aria-label="Open terminal"
        >
          Terminal
        </Link>
        <GuacamoleButton label="SSH" protocol="ssh" instanceUuid={instance.uuid} session={session} />
        <GuacamoleButton label="RDP" protocol="rdp" instanceUuid={instance.uuid} session={session} />
      </div>
      {session.error ? (
        <p role="alert" className="text-xs text-destructive">
          {session.error}
        </p>
      ) : null}
    </div>
  );
}

/**
 * Shared per-instance table: identity columns plus live-access actions. Reused
 * by the range dashboard and (a later chunk) the range detail page.
 */
export function InstanceTable({ instances }: Readonly<{ instances: InstancePresentation[] }>) {
  if (instances.length === 0) {
    return <p className="p-4 text-sm text-muted-foreground">No instances provisioned yet.</p>;
  }
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead>Name</TableHead>
          <TableHead>Role</TableHead>
          <TableHead>OS</TableHead>
          <TableHead>Private IP</TableHead>
          <TableHead>Access</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {instances.map((instance, index) => (
          <TableRow key={instance.uuid ?? `${instance.name}-${index}`}>
            <TableCell className="font-medium">{instance.name || "—"}</TableCell>
            <TableCell>{titleCase(instance.role)}</TableCell>
            <TableCell>{titleCase(instance.os_type)}</TableCell>
            <TableCell className="font-mono text-sm text-muted-foreground">{instance.private_ip ?? "—"}</TableCell>
            <TableCell>
              <InstanceActions instance={instance} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
