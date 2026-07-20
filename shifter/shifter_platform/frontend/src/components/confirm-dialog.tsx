import type { ReactNode } from "react";

import { ApiError } from "@/api/errors";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Shared confirmation dialog wrapping the shadcn AlertDialog (#1373). Promoted
 * from the previously per-feature copies so every SPA workspace shares one
 * implementation instead of drifting apart.
 */
export function ConfirmDialog({
  open,
  title,
  confirmLabel,
  destructive,
  pending,
  confirmDisabled,
  error,
  onConfirm,
  onOpenChange,
  children,
}: Readonly<{
  open: boolean;
  title: string;
  confirmLabel: string;
  destructive?: boolean;
  pending?: boolean;
  /** Extra condition (e.g. a type-to-confirm match) beyond `pending` that gates the confirm action. */
  confirmDisabled?: boolean;
  error?: unknown;
  onConfirm: () => void;
  onOpenChange: (open: boolean) => void;
  children: ReactNode;
}>) {
  let message: string | null = null;
  if (error instanceof ApiError) {
    message = error.message;
  } else if (error) {
    message = "The action could not be completed.";
  }

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{children}</AlertDialogDescription>
        </AlertDialogHeader>
        {message ? (
          <Alert variant="destructive">
            <AlertDescription>{message}</AlertDescription>
          </Alert>
        ) : null}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            className={destructive ? cn(buttonVariants({ variant: "destructive" })) : undefined}
            disabled={pending || confirmDisabled}
            onClick={(event) => {
              event.preventDefault();
              onConfirm();
            }}
          >
            {confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
