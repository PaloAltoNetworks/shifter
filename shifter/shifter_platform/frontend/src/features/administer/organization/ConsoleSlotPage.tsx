/**
 * Placeholder for a console surface slot whose behavior lands in a later slice
 * (#1938, PLAT-231; surfaces owned by PLAT-232–240). The route exists so deep
 * links and in-console navigation resolve today; the page is honest that the
 * workflow is not built yet rather than implying a completed capability.
 */
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

export function ConsoleSlotPage({ title }: Readonly<{ title: string }>) {
  return (
    <Alert>
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>This administration surface arrives in a later slice. The console shell and navigation are in place.</AlertDescription>
    </Alert>
  );
}
