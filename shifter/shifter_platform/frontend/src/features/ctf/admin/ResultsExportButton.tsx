import { exportCtfResults } from "@/api/ctfAdmin";
import { Button } from "@/components/ui/button";

/** Download the event results/statistics export as JSON (CTF-1103). */
export function ResultsExportButton({ eventId }: Readonly<{ eventId: string }>) {
  async function download() {
    const data = await exportCtfResults(eventId);
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const href = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = "event-results.json";
    anchor.click();
    URL.revokeObjectURL(href);
  }

  return (
    <Button type="button" variant="outline" size="sm" onClick={() => void download()}>
      Export results
    </Button>
  );
}
