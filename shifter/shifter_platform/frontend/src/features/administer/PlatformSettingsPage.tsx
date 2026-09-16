import { useState, type FormEvent } from "react";

import {
  useMissionControlLeasePolicySettings,
  useReplaceGroupLeasePolicy,
  useReplaceTenantLeasePolicy,
  useResetGroupLeasePolicy,
  useResetTenantLeasePolicy,
} from "@/api/administer";
import { describeMutationError } from "@/api/errors";
import type { MissionControlLeasePolicy, MissionControlLeasePolicyGroup } from "@/api/types";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";

interface PolicyEditorProps {
  readonly title: string;
  readonly actionLabel: string;
  readonly scopeId: string;
  readonly policy: MissionControlLeasePolicy;
  readonly revision: number;
  readonly hasOverride: boolean;
  readonly pending: boolean;
  readonly error: unknown;
  readonly onSave: (policy: MissionControlLeasePolicy) => void;
  readonly onReset: () => void;
  readonly testId: string;
}

function PolicyEditor({
  title,
  actionLabel,
  scopeId,
  policy,
  revision,
  hasOverride,
  pending,
  error,
  onSave,
  onReset,
  testId,
}: PolicyEditorProps) {
  const [initialDays, setInitialDays] = useState(String(policy.initial_days));
  const [extensionDays, setExtensionDays] = useState(String(policy.extension_days));
  const [maximumDays, setMaximumDays] = useState(String(policy.maximum_days));
  const [extensionsEnabled, setExtensionsEnabled] = useState(policy.extensions_enabled);
  const [validationError, setValidationError] = useState<string | null>(null);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const candidate = {
      initial_days: Number(initialDays),
      extension_days: Number(extensionDays),
      maximum_days: Number(maximumDays),
      extensions_enabled: extensionsEnabled,
    };
    if (
      !Number.isInteger(candidate.initial_days) ||
      !Number.isInteger(candidate.extension_days) ||
      !Number.isInteger(candidate.maximum_days) ||
      candidate.initial_days < 1 ||
      candidate.extension_days < 1 ||
      candidate.maximum_days < 1
    ) {
      setValidationError("Lease durations must be positive whole numbers.");
      return;
    }
    if (candidate.initial_days > candidate.maximum_days) {
      setValidationError("Initial days cannot exceed maximum days.");
      return;
    }
    setValidationError(null);
    onSave(candidate);
  };

  const mutationError = describeMutationError(error, `Could not update ${title.toLowerCase()}.`);

  return (
    <Card data-testid={testId}>
      <CardHeader>
        <h4 className="font-semibold leading-none">{title}</h4>
        <CardDescription>
          {hasOverride ? `Runtime override, revision ${revision}` : "Inheriting the effective tenant policy"}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-5" onSubmit={submit}>
          {(validationError || mutationError) && (
            <Alert variant="destructive">
              <AlertTitle>Policy not saved</AlertTitle>
              <AlertDescription>{validationError ?? mutationError}</AlertDescription>
            </Alert>
          )}

          <div className="grid gap-4 sm:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor={`${scopeId}-initial-days`}>Initial days</Label>
              <Input
                id={`${scopeId}-initial-days`}
                type="number"
                min={1}
                step={1}
                value={initialDays}
                disabled={pending}
                onChange={(event) => setInitialDays(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor={`${scopeId}-extension-days`}>Extension days</Label>
              <Input
                id={`${scopeId}-extension-days`}
                type="number"
                min={1}
                step={1}
                value={extensionDays}
                disabled={pending}
                onChange={(event) => setExtensionDays(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor={`${scopeId}-maximum-days`}>Maximum days</Label>
              <Input
                id={`${scopeId}-maximum-days`}
                type="number"
                min={1}
                step={1}
                value={maximumDays}
                disabled={pending}
                onChange={(event) => setMaximumDays(event.target.value)}
              />
            </div>
          </div>

          <div className="flex items-center gap-3">
            <input
              id={`${scopeId}-extensions-enabled`}
              className="size-4 rounded border-input accent-primary"
              type="checkbox"
              checked={extensionsEnabled}
              disabled={pending}
              onChange={(event) => setExtensionsEnabled(event.target.checked)}
            />
            <Label htmlFor={`${scopeId}-extensions-enabled`}>Allow owner extensions</Label>
          </div>

          <div className="flex flex-wrap gap-3">
            <Button type="submit" disabled={pending}>
              Save {actionLabel}
            </Button>
            {hasOverride && (
              <Button type="button" variant="outline" disabled={pending} onClick={onReset}>
                Reset {actionLabel}
              </Button>
            )}
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function TenantPolicyEditor({
  effective,
  override,
  revision,
}: {
  readonly effective: MissionControlLeasePolicy;
  readonly override: { policy: MissionControlLeasePolicy; revision: number } | null;
  readonly revision: number;
}) {
  const replace = useReplaceTenantLeasePolicy();
  const reset = useResetTenantLeasePolicy();

  return (
    <PolicyEditor
      key={`tenant-${revision}`}
      title="Tenant policy"
      actionLabel="tenant policy"
      scopeId="tenant"
      policy={override?.policy ?? effective}
      revision={revision}
      hasOverride={override !== null}
      pending={replace.isPending || reset.isPending}
      error={replace.error ?? reset.error}
      onSave={(policy) => replace.mutate({ expected_revision: revision, ...policy })}
      onReset={() => reset.mutate({ expected_revision: revision })}
      testId="tenant-lease-policy"
    />
  );
}

function GroupPolicyEditor({
  group,
  inherited,
}: {
  readonly group: MissionControlLeasePolicyGroup;
  readonly inherited: MissionControlLeasePolicy;
}) {
  const replace = useReplaceGroupLeasePolicy(group.id);
  const reset = useResetGroupLeasePolicy(group.id);
  const revision = group.revision;

  return (
    <PolicyEditor
      key={`group-${group.id}-${revision}`}
      title={group.name}
      actionLabel={`${group.name} policy`}
      scopeId={`group-${group.id}`}
      policy={group.override?.policy ?? inherited}
      revision={revision}
      hasOverride={group.override !== null}
      pending={replace.isPending || reset.isPending}
      error={replace.error ?? reset.error}
      onSave={(policy) => replace.mutate({ expected_revision: revision, ...policy })}
      onReset={() => reset.mutate({ expected_revision: revision })}
      testId={`group-lease-policy-${group.id}`}
    />
  );
}

function PolicySummary({ title, policy }: { readonly title: string; readonly policy: MissionControlLeasePolicy }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <div>
            <dt className="text-muted-foreground">Initial</dt>
            <dd className="font-medium">{policy.initial_days} days</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Extension</dt>
            <dd className="font-medium">{policy.extension_days} days</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Maximum</dt>
            <dd className="font-medium">{policy.maximum_days} days</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Owner extensions</dt>
            <dd className="font-medium">{policy.extensions_enabled ? "Enabled" : "Disabled"}</dd>
          </div>
        </dl>
      </CardContent>
    </Card>
  );
}

export function PlatformSettingsPage() {
  const settings = useMissionControlLeasePolicySettings();

  return (
    <>
      <PageHeader title="Platform settings" description="Runtime tenant and group policy" />

      <div className="space-y-6">
        <div>
          <h2 className="text-xl font-semibold">Mission Control lease policy</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Lease durations apply to new generations only. Existing range deadlines remain unchanged; whether an owner may
            extend a range is evaluated from the current policy.
          </p>
        </div>

        {settings.isLoading && <Skeleton className="h-48 w-full" aria-label="Loading lease policy" />}

        {settings.isError && (
          <Alert variant="destructive">
            <AlertTitle>Could not load lease policy</AlertTitle>
            <AlertDescription>Refresh the page to try again.</AlertDescription>
          </Alert>
        )}

        {settings.data && (
          <>
            <PolicySummary title="Deployment fallback" policy={settings.data.baseline} />

            <section className="space-y-3" aria-labelledby="tenant-policy-heading">
              <div>
                <h3 id="tenant-policy-heading" className="text-lg font-semibold">
                  Tenant policy
                </h3>
                <p className="text-sm text-muted-foreground">
                  Effective source: {settings.data.effective_source === "runtime" ? "runtime override" : "deployment fallback"}.
                </p>
              </div>
              <TenantPolicyEditor
                effective={settings.data.effective_tenant}
                override={settings.data.tenant_override}
                revision={settings.data.tenant_revision}
              />
            </section>

            <section className="space-y-3" aria-labelledby="group-policy-heading">
              <div>
                <h3 id="group-policy-heading" className="text-lg font-semibold">
                  Group policies
                </h3>
                <p className="text-sm text-muted-foreground">
                  Members of multiple groups receive the most restrictive applicable values. Group durations cannot exceed
                  the effective tenant maximum.
                </p>
              </div>
              {settings.data.groups.length === 0 ? (
                <p className="text-sm text-muted-foreground">No policy-eligible groups are configured.</p>
              ) : (
                <div className="grid gap-4 xl:grid-cols-2">
                  {settings.data.groups.map((group) => (
                    <GroupPolicyEditor key={group.id} group={group} inherited={settings.data.effective_tenant} />
                  ))}
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </>
  );
}
