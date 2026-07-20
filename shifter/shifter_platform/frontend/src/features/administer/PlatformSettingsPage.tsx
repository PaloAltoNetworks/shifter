import { useBootstrapContext } from "@/app/bootstrap-context";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card } from "@/components/ui/card";

import { titleCase } from "./format";

/**
 * Platform Settings is a read-only informational surface (#1373). Platform
 * configuration (environment, identity provider, cloud, Kubernetes, Terraform,
 * secrets, rollout flags) is owned by deployment; there is no validated platform
 * settings mutation service, so this workspace shows the non-secret rollout state
 * the session already carries and never edits it. Account settings live in
 * Mission Control, not here.
 */
export function PlatformSettingsPage() {
  const bootstrap = useBootstrapContext();
  const flags = Object.entries(bootstrap.feature_flags) as Array<[string, boolean]>;

  return (
    <>
      <PageHeader title="Platform settings" description="Read-only platform configuration" />

      <Alert className="mb-4">
        <AlertTitle>Managed by deployment</AlertTitle>
        <AlertDescription>
          Platform configuration is owned by the deployment pipeline and is not editable here. This page shows the current
          non-secret rollout state for reference. Personal account settings live under your profile in Mission Control.
        </AlertDescription>
      </Alert>

      <Card className="p-6">
        <h2 className="text-sm font-medium">Feature rollout flags</h2>
        <dl className="mt-4 grid grid-cols-1 gap-x-8 gap-y-3 sm:grid-cols-2">
          {flags.map(([name, enabled]) => (
            <div key={name} className="flex items-center justify-between gap-4 border-b border-white/5 pb-2">
              <dt className="text-sm text-muted-foreground">{titleCase(name.replaceAll("_", " "))}</dt>
              <dd>
                <span
                  className={`inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.05] px-2.5 py-0.5 text-xs font-medium ${
                    enabled ? "text-foreground/85" : "text-muted-foreground"
                  }`}
                >
                  <span
                    className="size-1.5 rounded-full"
                    style={{ backgroundColor: enabled ? "#30d158" : "#8e8e93" }}
                    aria-hidden="true"
                  />
                  {enabled ? "Enabled" : "Disabled"}
                </span>
              </dd>
            </div>
          ))}
        </dl>
      </Card>
    </>
  );
}
