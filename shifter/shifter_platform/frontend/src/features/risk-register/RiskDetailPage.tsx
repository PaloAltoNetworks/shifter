import { useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Loader2 } from "lucide-react";

import { useBootstrapContext } from "@/app/bootstrap-context";
import { useDeleteRisk, useRestoreRisk, useRisk, useUpdateRisk } from "@/api/risks";
import type { Risk } from "@/api/types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

import { SeverityBadge, StatusBadge } from "./badges";
import { CommentsPanel } from "./CommentsPanel";
import { ConfirmDialog } from "./ConfirmDialog";
import { HistoryPanel } from "./HistoryPanel";
import { formatTimestamp } from "./format";

type ActionDialog = "delete" | "restore" | "close" | "reopen" | null;

function Field({ label, children }: Readonly<{ label: string; children: ReactNode }>) {
  return (
    <div className="grid grid-cols-[150px_1fr] gap-4 border-b border-border/60 py-3 last:border-0">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}

function Multiline({ value }: Readonly<{ value: string }>) {
  return <p className="whitespace-pre-wrap">{value || "—"}</p>;
}

function DetailActions({
  risk,
  riskId,
  onAction,
}: Readonly<{ risk: Risk; riskId: number; onAction: (dialog: ActionDialog) => void }>) {
  if (risk.is_deleted) {
    return (
      <Button variant="outline" size="sm" onClick={() => onAction("restore")}>
        Restore
      </Button>
    );
  }
  return (
    <>
      <Link className={cn(buttonVariants({ variant: "outline", size: "sm" }))} to={`/risks/${riskId}/edit`}>
        Edit
      </Link>
      {risk.status === "closed" ? (
        <Button variant="outline" size="sm" onClick={() => onAction("reopen")}>
          Reopen
        </Button>
      ) : (
        <Button variant="outline" size="sm" onClick={() => onAction("close")}>
          Close
        </Button>
      )}
      <Button variant="destructive" size="sm" onClick={() => onAction("delete")}>
        Delete
      </Button>
    </>
  );
}

type RiskMutations = Readonly<{
  remove: ReturnType<typeof useDeleteRisk>;
  restore: ReturnType<typeof useRestoreRisk>;
  update: ReturnType<typeof useUpdateRisk>;
}>;

function DetailDialogs({
  dialog,
  riskId,
  mutations,
  resolution,
  onResolutionChange,
  onClose,
  onDeleted,
}: Readonly<{
  dialog: ActionDialog;
  riskId: number;
  mutations: RiskMutations;
  resolution: string;
  onResolutionChange: (value: string) => void;
  onClose: () => void;
  onDeleted: () => void;
}>) {
  const { remove, restore, update } = mutations;
  return (
    <>
      <ConfirmDialog
        open={dialog === "delete"}
        title="Delete risk?"
        confirmLabel="Delete"
        destructive
        pending={remove.isPending}
        error={remove.error}
        onOpenChange={(open) => !open && onClose()}
        onConfirm={() => remove.mutate(riskId, { onSuccess: onDeleted })}
      >
        This risk will be moved to the deleted state. It can be restored later.
      </ConfirmDialog>

      <ConfirmDialog
        open={dialog === "restore"}
        title="Restore risk?"
        confirmLabel="Restore"
        pending={restore.isPending}
        error={restore.error}
        onOpenChange={(open) => !open && onClose()}
        onConfirm={() => restore.mutate(riskId, { onSuccess: onClose })}
      >
        This risk will be returned to the active register.
      </ConfirmDialog>

      <ConfirmDialog
        open={dialog === "reopen"}
        title="Reopen risk?"
        confirmLabel="Reopen"
        pending={update.isPending}
        error={update.error}
        onOpenChange={(open) => !open && onClose()}
        onConfirm={() => update.mutate({ status: "open" }, { onSuccess: onClose })}
      >
        This risk will be moved back to open.
      </ConfirmDialog>

      <Dialog open={dialog === "close"} onOpenChange={(open) => !open && onClose()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Close risk?</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Label htmlFor="resolution">Resolution reason</Label>
            <Textarea
              id="resolution"
              rows={3}
              value={resolution}
              onChange={(event) => onResolutionChange(event.target.value)}
            />
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={onClose} disabled={update.isPending}>
              Cancel
            </Button>
            <Button
              onClick={() => update.mutate({ status: "closed", resolution_reason: resolution }, { onSuccess: onClose })}
              disabled={update.isPending}
            >
              Close risk
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function OverviewTab({ risk }: Readonly<{ risk: Risk }>) {
  return (
    <dl>
      <Field label="Severity">
        <SeverityBadge severity={risk.severity ?? "low"} />
      </Field>
      <Field label="Status">
        <StatusBadge status={risk.status ?? "open"} />
      </Field>
      <Field label="Likelihood">{risk.likelihood_score ?? "—"}</Field>
      <Field label="Impact">{risk.impact_score ?? "—"}</Field>
      <Field label="Risk score">
        <span className="font-mono tabular-nums">{risk.risk_score ?? "—"}</span>
      </Field>
      <Field label="STRIDE">{(risk.stride_categories as string[] | undefined)?.join(", ") || "—"}</Field>
      <Field label="Description">
        <Multiline value={risk.description ?? ""} />
      </Field>
      <Field label="Created">{formatTimestamp(risk.created_at)}</Field>
      <Field label="Updated">{formatTimestamp(risk.updated_at)}</Field>
    </dl>
  );
}

function MitigationTab({ risk }: Readonly<{ risk: Risk }>) {
  return (
    <dl>
      <Field label="Mitigation status">
        <Multiline value={risk.mitigation_status ?? ""} />
      </Field>
      <Field label="Attack vector">
        <Multiline value={risk.attack_vector ?? ""} />
      </Field>
      <Field label="Affected assets">
        <Multiline value={risk.affected_assets ?? ""} />
      </Field>
      <Field label="Resolution reason">
        <Multiline value={risk.resolution_reason ?? ""} />
      </Field>
    </dl>
  );
}

export function RiskDetailPage() {
  const params = useParams();
  const navigate = useNavigate();
  const riskId = Number(params.id);
  const bootstrap = useBootstrapContext();
  const canWrite = bootstrap.principal.is_staff;
  const canViewAudit = bootstrap.principal.is_staff || bootstrap.principal.is_superuser;

  const query = useRisk(riskId, true);
  const remove = useDeleteRisk();
  const restore = useRestoreRisk();
  const update = useUpdateRisk(riskId);

  const [tab, setTab] = useState("overview");
  const [dialog, setDialog] = useState<ActionDialog>(null);
  const [resolution, setResolution] = useState("");

  function closeDialog() {
    remove.reset();
    restore.reset();
    update.reset();
    setResolution("");
    setDialog(null);
  }

  if (query.isLoading) {
    return (
      <div className="grid place-items-center py-24 text-muted-foreground">
        <Loader2 className="size-6 animate-spin" aria-label="Loading risk" />
      </div>
    );
  }
  if (query.isError || !query.data) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Risk unavailable</AlertTitle>
        <AlertDescription>
          This risk was not found or has been removed.{" "}
          <Link className="underline" to="/">
            Back to risks
          </Link>
          .
        </AlertDescription>
      </Alert>
    );
  }

  const risk: Risk = query.data;

  return (
    <>
      <nav className="mb-3 text-sm text-muted-foreground" aria-label="Breadcrumb">
        <Link className="hover:text-foreground" to="/">
          Risks
        </Link>
        <span className="px-1.5">/</span>
        <span className="text-foreground">{risk.title ?? "Risk"}</span>
      </nav>

      <div className="mb-6 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">{risk.title ?? "Risk"}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <SeverityBadge severity={risk.severity ?? "low"} />
            <StatusBadge status={risk.status ?? "open"} />
            {risk.is_deleted ? (
              <Badge variant="outline" className="border-zinc-700 text-zinc-400">
                Deleted
              </Badge>
            ) : null}
          </div>
        </div>
        {canWrite ? (
          <div className="flex shrink-0 items-center gap-2">
            <DetailActions risk={risk} riskId={riskId} onAction={setDialog} />
          </div>
        ) : null}
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="mitigation">Mitigation</TabsTrigger>
          <TabsTrigger value="comments">Comments</TabsTrigger>
          <TabsTrigger value="history">History</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="mt-4">
          <Card>
            <CardContent>
              <OverviewTab risk={risk} />
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="mitigation" className="mt-4">
          <Card>
            <CardContent>
              <MitigationTab risk={risk} />
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="comments" className="mt-4">
          <Card>
            <CardContent>
              <CommentsPanel
                riskId={riskId}
                canWrite={canWrite}
                readOnly={Boolean(risk.is_deleted)}
                includeDeleted={Boolean(risk.is_deleted)}
              />
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="history" className="mt-4">
          <Card>
            <CardContent>
              <HistoryPanel riskId={riskId} canViewAudit={canViewAudit} />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <DetailDialogs
        dialog={dialog}
        riskId={riskId}
        mutations={{ remove, restore, update }}
        resolution={resolution}
        onResolutionChange={setResolution}
        onClose={closeDialog}
        onDeleted={() => navigate("/")}
      />
    </>
  );
}
