import { useState } from "react";
import { useParams } from "react-router";

import {
  type AuthorizationScope,
  useAuthorizationCatalog,
  useAuthorizationGroups,
  useAuthorizationOperation,
  useAuthorizationPolicies,
  useCreateAuthorizationGroup,
  useCreateAuthorizationPolicy,
  useDirectAssignment,
  useGroupMembership,
  usePolicyAction,
  usePolicyAssignment,
  usePredefinedAssignment,
  usePredefinedAuthorizationCatalog,
  useReconcileAuthorizationOperation,
} from "@/api/authorization";
import type { AuthorizationEffect, AuthorizationMutation } from "@/api/types";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";

export function MutationOutcome({
  workspaceUuid,
  result,
  error,
  uncertain,
  onRetry,
}: Readonly<{ workspaceUuid: AuthorizationScope; result?: AuthorizationMutation; error?: unknown; uncertain?: boolean; onRetry?: () => void }>) {
  const pending = result?.state === "requested" || result?.state === "unresolved";
  const operation = useAuthorizationOperation(workspaceUuid, result?.operation_id ?? "", pending);
  const reconcile = useReconcileAuthorizationOperation(workspaceUuid, result?.operation_id ?? "");
  if (error) return <>
    <MutationError />
    {uncertain ? <div className="space-y-2">
      <p>The response was not confirmed. Retry the original command before changing these inputs.</p>
      <Button type="button" onClick={onRetry}>Retry original command</Button>
    </div> : null}
  </>;
  if (!result) return null;
  const state = operation.data?.state ?? result.state;
  const descriptions: Record<string, string> = {
    requested: "The request is recorded and awaiting provider confirmation.",
    confirmed: "The requested authorization change is confirmed.",
    denied: "The request was denied and no relationship change was attempted.",
    unresolved: "The provider outcome is unknown. Conflicting edits are blocked until reconciliation.",
  };
  return (
    <Alert variant={state === "denied" || state === "unresolved" ? "destructive" : "default"}>
      <AlertTitle>Authorization change: {state}</AlertTitle>
      <AlertDescription>{descriptions[state]}</AlertDescription>
      {operation.isError ? <p role="alert">The operation status could not be refreshed.</p> : null}
      {reconcile.isError ? <p role="alert">Reconciliation failed. The operation is still pending.</p> : null}
      {state === "requested" || state === "unresolved" ? (
        <Button className="mt-3" type="button" disabled={reconcile.isPending} onClick={() => reconcile.mutate()}>
          {reconcile.isPending ? "Reconciling…" : "Reconcile status"}
        </Button>
      ) : null}
    </Alert>
  );
}

function MutationError() {
  return (
    <Alert variant="destructive">
      <AlertTitle>Authorization change could not be completed</AlertTitle>
      <AlertDescription>Check your inputs and permissions, then try again. No successful change has been confirmed.</AlertDescription>
    </Alert>
  );
}

function CreateMetadataCard({
  title,
  description,
  onCreate,
  pending,
  error,
}: Readonly<{
  title: string;
  description: string;
  onCreate: (name: string, description: string) => Promise<unknown>;
  pending: boolean;
  error?: unknown;
}>) {
  const [name, setName] = useState("");
  const [details, setDetails] = useState("");
  return (
    <Card className="space-y-4 p-5">
      <div>
        <h2 className="font-medium">{title}</h2>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      <form
        className="space-y-3"
        onSubmit={async (event) => {
          event.preventDefault();
          if (!name.trim()) return;
          try {
            await onCreate(name.trim(), details.trim());
            setName("");
            setDetails("");
          } catch {
            // The mutation's error below preserves the draft for correction.
          }
        }}
      >
        <div className="space-y-1">
          <Label htmlFor={`${title}-name`}>Name</Label>
          <Input id={`${title}-name`} value={name} maxLength={120} onChange={(event) => setName(event.target.value)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor={`${title}-description`}>Description</Label>
          <Input
            id={`${title}-description`}
            value={details}
            maxLength={500}
            onChange={(event) => setDetails(event.target.value)}
          />
        </div>
        <Button type="submit" disabled={pending || !name.trim()}>
          {pending ? "Creating…" : `Create ${title.toLowerCase()}`}
        </Button>
      </form>
      {error ? <MutationError /> : null}
    </Card>
  );
}

function EffectSelect({ value, onChange }: Readonly<{ value: AuthorizationEffect; onChange: (value: AuthorizationEffect) => void }>) {
  return (
    <select
      aria-label="Relationship effect"
      className="h-9 rounded-md border bg-background px-3 text-sm"
      value={value}
      onChange={(event) => onChange(event.target.value as AuthorizationEffect)}
    >
      <option value="grant">Grant</option>
      <option value="revoke">Revoke</option>
    </select>
  );
}

export function WorkspaceAuthorizationPage() {
  const { workspaceUuid = "" } = useParams();
  return <ScopeAuthorizationContent key={workspaceUuid} workspaceUuid={workspaceUuid} />;
}

export function ScopeAuthorizationContent({ workspaceUuid }: Readonly<{ workspaceUuid: AuthorizationScope }>) {
  const scopeType = typeof workspaceUuid === "string" ? "workspace" : workspaceUuid.kind;
  const groups = useAuthorizationGroups(workspaceUuid);
  const policies = useAuthorizationPolicies(workspaceUuid);
  const catalog = useAuthorizationCatalog();
  const predefined = usePredefinedAuthorizationCatalog();
  const createGroup = useCreateAuthorizationGroup(workspaceUuid);
  const createPolicy = useCreateAuthorizationPolicy(workspaceUuid);

  if (groups.isPending || policies.isPending || catalog.isPending || predefined.isPending) {
    return <Skeleton className="h-56 w-full max-w-5xl" />;
  }
  if (groups.isError || policies.isError || catalog.isError || predefined.isError) {
    return (
      <Alert variant="destructive" className="max-w-xl">
        <AlertTitle>Authorization policies are not available</AlertTitle>
        <AlertDescription>Your current credential or policy does not permit this workspace operation.</AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Policies and groups"
        description={`Manage ${scopeType} groups, policies, assignments, and revocations.`}
      />
      <div className="grid gap-4 lg:grid-cols-2">
        <CreateMetadataCard
          title="Group"
          description="Groups collect people and services that receive shared policy assignments."
          pending={createGroup.isPending}
          error={createGroup.error}
          onCreate={(name, description) => createGroup.mutateAsync({ name, description })}
        />
        <CreateMetadataCard
          title="Policy"
          description="Policies define reusable sets of permissions."
          pending={createPolicy.isPending}
          error={createPolicy.error}
          onCreate={(name, description) => createPolicy.mutateAsync({ name, description })}
        />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <MetadataList title="Groups" items={groups.data ?? []} />
        <MetadataList title="Policies" items={policies.data ?? []} />
      </div>
      <GroupMembershipForm workspaceUuid={workspaceUuid} groups={(groups.data ?? []).filter((item) => item.is_active)} />
      <PolicyAssignmentForm workspaceUuid={workspaceUuid} groups={(groups.data ?? []).filter((item) => item.is_active)} policies={(policies.data ?? []).filter((item) => item.is_active && !item.predefined_code)} />
      <PredefinedAssignmentForm
        workspaceUuid={workspaceUuid}
        groups={(groups.data ?? []).filter((item) => item.is_active)}
        policies={(predefined.data ?? []).filter((item) => item.target_type === scopeType)}
      />
      <ActionAssignmentForm
        workspaceUuid={workspaceUuid}
        policies={(policies.data ?? []).filter((item) => item.is_active && !item.predefined_code)}
        actions={(catalog.data ?? []).filter((item) => item.target_type === scopeType && item.delegable)}
      />
    </div>
  );
}

function PredefinedAssignmentForm({
  workspaceUuid,
  groups,
  policies,
}: Readonly<{
  workspaceUuid: AuthorizationScope;
  groups: readonly { uuid: string; name: string }[];
  policies: readonly { code: string; name: string }[];
}>) {
  const [policyCode, setPolicyCode] = useState("");
  const [subjectKind, setSubjectKind] = useState<"principal" | "group">("principal");
  const [subjectUuid, setSubjectUuid] = useState("");
  const [effect, setEffect] = useState<AuthorizationEffect>("grant");
  const mutation = usePredefinedAssignment(workspaceUuid);
  return (
    <Card className="space-y-4 p-5">
      <div>
        <h2 className="font-medium">Predefined administrator assignment</h2>
        <p className="text-sm text-muted-foreground">
          Assign a built-in administrator policy to a person, service, or group.
        </p>
      </div>
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          mutation.mutate({
            policy_code: policyCode,
            subject_kind: subjectKind,
            subject_uuid: subjectUuid,
            effect,
          });
        }}
      >
        <fieldset className="contents" disabled={mutation.isPending || mutation.uncertain}>
        <LabeledSelect
          label="Predefined policy"
          value={policyCode}
          onChange={setPolicyCode}
          options={policies.map((item) => ({ uuid: item.code, name: item.name }))}
        />
        <select
          aria-label="Predefined assignment subject kind"
          className="h-9 rounded-md border bg-background px-3 text-sm"
          value={subjectKind}
          onChange={(event) => setSubjectKind(event.target.value as "principal" | "group")}
        >
          <option value="principal">Principal</option>
          <option value="group">Group</option>
        </select>
        {subjectKind === "group" ? (
          <LabeledSelect label="Predefined assignment group" value={subjectUuid} onChange={setSubjectUuid} options={groups} />
        ) : (
          <LabeledUuid label="Predefined principal UUID" value={subjectUuid} onChange={setSubjectUuid} />
        )}
        <EffectSelect value={effect} onChange={setEffect} />
        <Button type="submit" disabled={!policyCode || !subjectUuid || mutation.isPending}>
          Apply
        </Button>
        </fieldset>
      </form>
      <MutationOutcome workspaceUuid={workspaceUuid} result={mutation.data} error={mutation.error} uncertain={mutation.uncertain} onRetry={mutation.retryCommand} />
    </Card>
  );
}

function MetadataList({ title, items }: Readonly<{ title: string; items: readonly { uuid: string; name: string; is_active: boolean }[] }>) {
  return (
    <Card className="p-5">
      <h2 className="font-medium">{title}</h2>
      {items.length === 0 ? <p className="mt-2 text-sm text-muted-foreground">No {title.toLowerCase()} yet.</p> : null}
      <ul className="mt-3 space-y-2">
        {items.map((item) => (
          <li key={item.uuid} className="flex items-center justify-between gap-3 text-sm">
            <span>{item.name}</span>
            <Badge variant={item.is_active ? "secondary" : "outline"}>{item.is_active ? "Active" : "Inactive"}</Badge>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function GroupMembershipForm({ workspaceUuid, groups }: Readonly<{ workspaceUuid: AuthorizationScope; groups: readonly { uuid: string; name: string }[] }>) {
  const [groupUuid, setGroupUuid] = useState("");
  const [principalUuid, setPrincipalUuid] = useState("");
  const [effect, setEffect] = useState<AuthorizationEffect>("grant");
  const mutation = useGroupMembership(workspaceUuid, groupUuid);
  return (
    <Card className="space-y-4 p-5">
      <h2 className="font-medium">Group membership</h2>
      <form className="flex flex-wrap items-end gap-3" onSubmit={(event) => {
        event.preventDefault();
        mutation.mutate({ principal_uuid: principalUuid, effect });
      }}>
        <fieldset className="contents" disabled={mutation.isPending || mutation.uncertain}>
        <LabeledSelect label="Group" value={groupUuid} onChange={setGroupUuid} options={groups} />
        <LabeledUuid label="Principal UUID" value={principalUuid} onChange={setPrincipalUuid} />
        <EffectSelect value={effect} onChange={setEffect} />
        <Button type="submit" disabled={!groupUuid || !principalUuid || mutation.isPending}>Apply</Button>
        </fieldset>
      </form>
      <MutationOutcome workspaceUuid={workspaceUuid} result={mutation.data} error={mutation.error} uncertain={mutation.uncertain} onRetry={mutation.retryCommand} />
    </Card>
  );
}

function PolicyAssignmentForm({ workspaceUuid, groups, policies }: Readonly<{ workspaceUuid: AuthorizationScope; groups: readonly { uuid: string; name: string }[]; policies: readonly { uuid: string; name: string }[] }>) {
  const [policyUuid, setPolicyUuid] = useState("");
  const [subjectKind, setSubjectKind] = useState<"principal" | "group">("principal");
  const [subjectUuid, setSubjectUuid] = useState("");
  const [effect, setEffect] = useState<AuthorizationEffect>("grant");
  const mutation = usePolicyAssignment(workspaceUuid, policyUuid);
  return (
    <Card className="space-y-4 p-5">
      <h2 className="font-medium">Policy assignment</h2>
      <form className="flex flex-wrap items-end gap-3" onSubmit={(event) => {
        event.preventDefault();
        mutation.mutate({ subject_kind: subjectKind, subject_uuid: subjectUuid, effect });
      }}>
        <fieldset className="contents" disabled={mutation.isPending || mutation.uncertain}>
        <LabeledSelect label="Policy" value={policyUuid} onChange={setPolicyUuid} options={policies} />
        <select aria-label="Assignment subject kind" className="h-9 rounded-md border bg-background px-3 text-sm" value={subjectKind} onChange={(event) => setSubjectKind(event.target.value as "principal" | "group")}>
          <option value="principal">Principal</option><option value="group">Group</option>
        </select>
        {subjectKind === "group" ? <LabeledSelect label="Group" value={subjectUuid} onChange={setSubjectUuid} options={groups} /> : <LabeledUuid label="Principal UUID" value={subjectUuid} onChange={setSubjectUuid} />}
        <EffectSelect value={effect} onChange={setEffect} />
        <Button type="submit" disabled={!policyUuid || !subjectUuid || mutation.isPending}>Apply</Button>
        </fieldset>
      </form>
      <MutationOutcome workspaceUuid={workspaceUuid} result={mutation.data} error={mutation.error} uncertain={mutation.uncertain} onRetry={mutation.retryCommand} />
    </Card>
  );
}

function ActionAssignmentForm({ workspaceUuid, policies, actions }: Readonly<{ workspaceUuid: AuthorizationScope; policies: readonly { uuid: string; name: string }[]; actions: readonly { code: string }[] }>) {
  const [policyUuid, setPolicyUuid] = useState("");
  const [subjectUuid, setSubjectUuid] = useState("");
  const [action, setAction] = useState("");
  const [effect, setEffect] = useState<AuthorizationEffect>("grant");
  const policyMutation = usePolicyAction(workspaceUuid, policyUuid);
  const directMutation = useDirectAssignment(workspaceUuid);
  const mutation = policyUuid ? policyMutation : directMutation;
  return (
    <Card className="space-y-4 p-5">
      <h2 className="font-medium">Action assignment</h2>
      <p className="text-sm text-muted-foreground">Choose a policy, or leave it blank to assign the action directly to a principal.</p>
      <form className="flex flex-wrap items-end gap-3" onSubmit={(event) => {
        event.preventDefault();
        const common = { action, effect };
        if (policyUuid) policyMutation.mutate(common);
        else directMutation.mutate({ ...common, subject_kind: "principal", subject_uuid: subjectUuid });
      }}>
        <fieldset className="contents" disabled={mutation.isPending || mutation.uncertain}>
        <LabeledSelect label="Policy (optional)" value={policyUuid} onChange={setPolicyUuid} options={policies} optional />
        {policyUuid ? null : <LabeledUuid label="Principal UUID" value={subjectUuid} onChange={setSubjectUuid} />}
        <LabeledSelect label="Action" value={action} onChange={setAction} options={actions.map((item) => ({ uuid: item.code, name: item.code }))} />
        <EffectSelect value={effect} onChange={setEffect} />
        <Button type="submit" disabled={!action || (!policyUuid && !subjectUuid) || mutation.isPending}>Apply</Button>
        </fieldset>
      </form>
      <MutationOutcome workspaceUuid={workspaceUuid} result={mutation.data} error={mutation.error} uncertain={mutation.uncertain} onRetry={mutation.retryCommand} />
    </Card>
  );
}

function LabeledSelect({ label, value, onChange, options, optional = false }: Readonly<{ label: string; value: string; onChange: (value: string) => void; options: readonly { uuid: string; name: string }[]; optional?: boolean }>) {
  return <label className="space-y-1 text-sm"><span className="block font-medium">{label}</span><select className="h-9 min-w-48 rounded-md border bg-background px-3" value={value} onChange={(event) => onChange(event.target.value)}><option value="">{optional ? "Direct assignment" : `Select ${label.toLowerCase()}`}</option>{options.map((item) => <option key={item.uuid} value={item.uuid}>{item.name}</option>)}</select></label>;
}

function LabeledUuid({ label, value, onChange }: Readonly<{ label: string; value: string; onChange: (value: string) => void }>) {
  return <label className="space-y-1"><span className="block text-sm font-medium">{label}</span><Input className="font-mono" value={value} placeholder="00000000-0000-0000-0000-000000000000" onChange={(event) => onChange(event.target.value)} /></label>;
}
