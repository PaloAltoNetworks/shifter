import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card } from "@/components/ui/card";

/**
 * Cost reporting is a truthful degraded state (#1373). Cost viewing depends on a
 * separately owned canonical data source and `/api/v1/` read contract that do
 * not exist yet; surfacing a placeholder here does not claim a working workflow.
 * This page renders no cost figures and calls no provider — it states the surface
 * is unavailable and why.
 */
export function CostPage() {
  return (
    <>
      <PageHeader title="Cost" description="Cost reporting" />

      <Card className="p-8">
        <div className="mx-auto max-w-lg text-center">
          <h2 className="text-base font-medium">Cost reporting is not available yet</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            A canonical cost data source and read API are being built separately. Once they are in place, actual spend,
            forecast, and budget will appear here as clearly labelled, distinct figures.
          </p>
          <Alert className="mt-6 text-left">
            <AlertTitle>Where to find cost today</AlertTitle>
            <AlertDescription>
              Until this surface is ready, use your cloud provider&apos;s billing console for authoritative spend.
            </AlertDescription>
          </Alert>
        </div>
      </Card>
    </>
  );
}
