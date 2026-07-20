import { useState } from "react";

import { useImportCtfParticipants } from "@/api/ctfAdmin";
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

/** Parse "name,email" lines into import rows; row validation happens server-side. */
function parseCsvRows(text: string): Array<{ name: string; email: string }> {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [name = "", email = ""] = line.split(",").map((cell) => cell.trim());
      return { name, email };
    });
}

/** Bulk CSV participant import (CTF-603): per-row errors never sink the batch. */
export function ParticipantImportDialog({ eventId }: Readonly<{ eventId: string }>) {
  const importParticipants = useImportCtfParticipants(eventId);
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");

  const rows = parseCsvRows(text);
  const result = importParticipants.data;
  const errorMessage = describeMutationError(importParticipants.error, "Import failed. Try again.");

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) {
          setText("");
          importParticipants.reset();
        }
      }}
    >
      <DialogTrigger asChild>
        <Button type="button" variant="outline">
          Import CSV
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Import participants</DialogTitle>
          <DialogDescription>
            One participant per line as <code className="font-mono">name,email</code>. Rows that fail (bad
            format, duplicate email) are skipped and reported; the rest are imported.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-1">
          <Label htmlFor="import-csv">CSV rows</Label>
          <Textarea
            id="import-csv"
            rows={8}
            value={text}
            placeholder={"Alice Example,alice@example.com\nBob Example,bob@example.com"}
            onChange={(event) => setText(event.target.value)}
          />
        </div>
        {result ? (
          <div className="text-sm">
            <p>{result.imported} imported.</p>
            {result.errors.length ? (
              <ul className="mt-1 list-inside list-disc text-xs text-destructive">
                {result.errors.map((rowError) => (
                  <li key={`${String(rowError.index)}-${String(rowError.error)}`}>
                    Row {Number(rowError.index) + 1}: {String(rowError.error)}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
        {importParticipants.error ? <p className="text-xs text-destructive">{errorMessage}</p> : null}
        <DialogFooter>
          <Button
            type="button"
            disabled={rows.length === 0 || importParticipants.isPending}
            onClick={() => importParticipants.mutate(rows)}
          >
            Import {rows.length || ""} {rows.length === 1 ? "row" : "rows"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
