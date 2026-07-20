import { useState } from "react";

import { exportCtfChallenges, useImportCtfChallenges } from "@/api/ctfAdmin";
import { describeMutationError } from "@/api/errors";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

function downloadJson(name: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = name;
  anchor.click();
  URL.revokeObjectURL(href);
}

/** Challenge pack export/import (CTF-1101/1102/1104). */
export function ChallengeTransferControls({ eventId }: Readonly<{ eventId: string }>) {
  const importPack = useImportCtfChallenges(eventId);
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);
  const result = importPack.data;
  const errorMessage = describeMutationError(importPack.error, "Import failed.");

  async function exportPack(fmt: "shifter" | "ctfd") {
    const data = await exportCtfChallenges(eventId, fmt);
    downloadJson(fmt === "ctfd" ? "challenges-ctfd.json" : "challenges-shifter.json", data);
  }

  function runImport() {
    setParseError(null);
    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(text) as Record<string, unknown>;
    } catch {
      setParseError("Not valid JSON.");
      return;
    }
    importPack.mutate(payload);
  }

  return (
    <div className="flex items-center gap-2">
      <Button type="button" variant="outline" size="sm" onClick={() => void exportPack("shifter")}>
        Export
      </Button>
      <Button type="button" variant="outline" size="sm" onClick={() => void exportPack("ctfd")}>
        Export (CTFd)
      </Button>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (!next) {
            setText("");
            setParseError(null);
            importPack.reset();
          }
        }}
      >
        <DialogTrigger asChild>
          <Button type="button" variant="outline" size="sm">
            Import pack
          </Button>
        </DialogTrigger>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Import challenge pack</DialogTitle>
            <DialogDescription>
              Paste a Shifter or CTFd challenge export. Bad or duplicate entries are skipped and reported; the
              rest import.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-1">
            <Label htmlFor="pack-json">Pack JSON</Label>
            <Textarea id="pack-json" rows={8} value={text} onChange={(e) => setText(e.target.value)} />
          </div>
          {parseError ? <p className="text-xs text-destructive">{parseError}</p> : null}
          {importPack.error ? <p className="text-xs text-destructive">{errorMessage}</p> : null}
          {result ? (
            <div className="text-sm">
              <p>{result.created.length} imported.</p>
              {result.errors.length ? (
                <ul className="mt-1 list-inside list-disc text-xs text-destructive">
                  {result.errors.map((entry) => (
                    <li key={`${String(entry.index)}-${String(entry.error)}`}>
                      {entry.name ? `${entry.name}: ` : `Entry ${Number(entry.index) + 1}: `}
                      {entry.error}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
          <DialogFooter>
            <Button type="button" disabled={!text.trim() || importPack.isPending} onClick={runImport}>
              Import
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
