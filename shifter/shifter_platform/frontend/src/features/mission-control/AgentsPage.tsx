import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { Loader2 } from "lucide-react";

import { ApiError } from "@/api/errors";
import { useAgents } from "@/api/mission-control";
import type { AgentListItem } from "@/api/types";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import { formatTimestamp } from "./format";
import { type AgentType, useAgentUpload } from "./useAgentUpload";

const AGENT_TYPE_OPTIONS: ReadonlyArray<{ value: AgentType; label: string }> = [
  { value: "xdr", label: "XDR/XSIAM Agent" },
  { value: "xdr_collector", label: "XDR Collector" },
  { value: "cloud_identity_engine", label: "Cloud Identity Engine" },
];

/**
 * Upload-agent form (#1370). Mirrors the legacy `DirectUploader` flow
 * (`static/js/upload.js`, `templates/mission_control/agents.html`):
 * `useInitiateUpload()` -> presigned S3 PUT (progress) -> `useCompleteUpload()`,
 * all owned by `useAgentUpload`. No step auto-retries; a failure surfaces
 * inline and requires a fresh submit.
 */
function UploadAgentForm() {
  const upload = useAgentUpload();
  const [name, setName] = useState("");
  const [agentType, setAgentType] = useState<AgentType>("xdr");
  const [file, setFile] = useState<File | null>(null);
  // `Input` (an uncontrolled `<input type="file">`) has no controlled `value`
  // to reset, and it is not `forwardRef`-wrapped, so remounting it via a
  // changing `key` is the way to clear the picked filename after a completed
  // or cancelled upload.
  const [fileInputKey, setFileInputKey] = useState(0);
  const nameId = useId();
  const typeId = useId();
  const fileId = useId();

  const uploading = upload.phase === "uploading";

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    upload.start({ name, file, agentType });
  }

  function onCancel() {
    upload.cancel();
  }

  // Reset the form once an upload completes successfully (phase transitions
  // uploading -> idle with no error) so the next upload starts from a clean
  // slate. A cancelled upload also lands on "idle", which is fine — clearing
  // the form is the expected outcome of cancelling too.
  const previousPhaseRef = useRef(upload.phase);
  useEffect(() => {
    if (previousPhaseRef.current === "uploading" && upload.phase === "idle") {
      setName("");
      setFile(null);
      setFileInputKey((key) => key + 1);
    }
    previousPhaseRef.current = upload.phase;
  }, [upload.phase]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Upload agent</CardTitle>
      </CardHeader>
      <form onSubmit={onSubmit} noValidate>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor={nameId}>Agent name</Label>
            <Input
              id={nameId}
              placeholder="e.g., Acme Corp XSIAM"
              value={name}
              maxLength={100}
              disabled={uploading}
              onChange={(event) => setName(event.target.value)}
            />
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor={typeId}>Agent type</Label>
            <Select value={agentType} onValueChange={(value) => setAgentType(value as AgentType)}>
              <SelectTrigger id={typeId} className="w-full" disabled={uploading}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {AGENT_TYPE_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor={fileId}>Installer file</Label>
            <Input
              key={fileInputKey}
              id={fileId}
              type="file"
              disabled={uploading}
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
            <p className="text-sm text-muted-foreground">Max 2048 MB per file.</p>
          </div>

          {uploading ? (
            <div className="flex flex-col gap-2" aria-live="polite">
              <Progress value={upload.progress} />
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">{upload.statusText}</span>
                <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
                  Cancel
                </Button>
              </div>
            </div>
          ) : null}

          {upload.error ? (
            <Alert variant="destructive">
              <AlertTitle>Upload failed</AlertTitle>
              <AlertDescription>{upload.error}</AlertDescription>
            </Alert>
          ) : null}
        </CardContent>
        <CardFooter className="justify-end">
          <Button type="submit" disabled={uploading || !file || !name.trim()}>
            {uploading ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : null}
            {uploading ? "Uploading…" : "Upload agent"}
          </Button>
        </CardFooter>
      </form>
    </Card>
  );
}

function EmptyAgentsState() {
  return (
    <Card className="grid place-items-center px-6 py-16 text-center">
      <p className="text-sm font-medium">No agents uploaded yet</p>
      <p className="mt-1 text-sm text-muted-foreground">
        Upload an XDR, XDR Collector, or Cloud Identity Engine agent to get started.
      </p>
    </Card>
  );
}

function AgentRow({ agent }: Readonly<{ agent: AgentListItem }>) {
  return (
    <TableRow>
      <TableCell className="font-medium">{agent.name}</TableCell>
      <TableCell>{agent.agent_type_display}</TableCell>
      <TableCell>{agent.os_name}</TableCell>
      <TableCell className="text-sm text-muted-foreground">
        {agent.original_filename}
        <span className="block text-xs">{agent.file_size_mb} MB</span>
      </TableCell>
      <TableCell className="text-sm text-muted-foreground">{formatTimestamp(agent.created_at)}</TableCell>
    </TableRow>
  );
}

function AgentsListBody({ query }: Readonly<{ query: ReturnType<typeof useAgents> }>) {
  if (query.isLoading) {
    return (
      <div className="space-y-3">
        {[0, 1, 2].map((row) => (
          <Skeleton key={row} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  if (query.isError) {
    const message = query.error instanceof ApiError ? query.error.message : "Please retry.";
    return (
      <Alert variant="destructive">
        <AlertTitle>Could not load your agents</AlertTitle>
        <AlertDescription>{message}</AlertDescription>
      </Alert>
    );
  }

  const agents = query.data?.agents ?? [];
  if (agents.length === 0) {
    return <EmptyAgentsState />;
  }

  return (
    <Card className="overflow-hidden py-0" aria-busy={query.isFetching}>
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Name</TableHead>
            <TableHead>Type</TableHead>
            <TableHead>OS</TableHead>
            <TableHead>File</TableHead>
            <TableHead>Uploaded</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {agents.map((agent) => (
            <AgentRow key={agent.id} agent={agent} />
          ))}
        </TableBody>
      </Table>
    </Card>
  );
}

/**
 * Agents list + upload (#1370). There is intentionally no delete action here:
 * `mission_control/api/urls.py` has no `/api/v1` agent-delete route (the
 * legacy Django delete at `mission_control:delete_agent` is not part of the
 * canonical API surface this SPA is scoped to), so agent deletion stays a
 * pending gap tracked by #1328/#1329 rather than calling the legacy endpoint
 * or inventing a new one.
 */
export function AgentsPage() {
  const query = useAgents();

  return (
    <>
      <PageHeader title="Agents" description="Manage your XDR, XDR Collector, and Cloud Identity Engine agents." />

      <div className="mb-6">
        <UploadAgentForm />
      </div>

      <Alert className="mb-6">
        <AlertTitle>Agent deletion is not yet available here</AlertTitle>
        <AlertDescription>
          Removing an agent still requires the legacy Mission Control pages. Deleting agents through this API is
          tracked as a pending gap (#1328, #1329).
        </AlertDescription>
      </Alert>

      <AgentsListBody query={query} />
    </>
  );
}
