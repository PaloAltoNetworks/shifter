import { useEffect, useId, useState } from "react";

import { useDestroyNgfw } from "@/api/mission-control";
import type { NGFWListItem } from "@/api/types";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { ConfirmDialog } from "@/components/confirm-dialog";

/**
 * Shared NGFW deprovision confirmation (#1370), used by both the NGFW list
 * and detail pages. Mirrors the legacy
 * `templates/mission_control/ngfw/deprovision.html` type-to-confirm flow: the
 * confirm action stays disabled until the typed value matches the NGFW's name
 * exactly, and that typed value is sent as `confirm_name`
 * (`NGFWDestroySerializer`). No auto-retry on failure (ADR-029): the dialog
 * stays open with the error inline and requires an explicit re-click.
 */
export function NgfwDestroyDialog({
  ngfw,
  open,
  onOpenChange,
  onDestroyed,
}: Readonly<{
  ngfw: NGFWListItem;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDestroyed?: () => void;
}>) {
  const destroy = useDestroyNgfw();
  const [confirmName, setConfirmName] = useState("");
  const inputId = useId();

  useEffect(() => {
    if (!open) {
      setConfirmName("");
      destroy.reset();
    }
    // Reset local + mutation state whenever the dialog closes; `destroy` is a
    // fresh object each render and including it would reset on every
    // keystroke, so only `open` drives this effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const matches = confirmName.trim().length > 0 && confirmName.trim() === ngfw.name;

  function handleConfirm() {
    if (!matches) return;
    destroy.mutate(
      { appId: ngfw.id, confirmName: confirmName.trim() },
      {
        onSuccess: () => {
          onOpenChange(false);
          onDestroyed?.();
        },
      },
    );
  }

  return (
    <ConfirmDialog
      open={open}
      title={`Deprovision ${ngfw.name}`}
      confirmLabel="Deprovision NGFW"
      destructive
      pending={destroy.isPending}
      confirmDisabled={!matches}
      error={destroy.error}
      onConfirm={handleConfirm}
      onOpenChange={onOpenChange}
    >
      <span className="block">
        This will permanently deprovision the NGFW, terminate its instance, and deactivate its license. This cannot
        be undone.
      </span>
      <span className="mt-3 block">
        <Label htmlFor={inputId}>
          Type <strong className="text-foreground">{ngfw.name}</strong> to confirm.
        </Label>
        <Input
          id={inputId}
          className="mt-1.5"
          autoComplete="off"
          disabled={destroy.isPending}
          value={confirmName}
          onChange={(event) => setConfirmName(event.target.value)}
        />
      </span>
    </ConfirmDialog>
  );
}
