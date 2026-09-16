import { useEffect, useState } from "react";

import { useResetCtfParticipantPassword } from "@/api/ctfAdmin";
import { describeMutationError } from "@/api/errors";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function ParticipantPasswordDialog({
  participantId,
  participantName,
}: Readonly<{
  participantId: string;
  participantName: string;
}>) {
  const [open, setOpen] = useState(false);
  const [settingPassword, setSettingPassword] = useState(false);
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const resetPassword = useResetCtfParticipantPassword(participantId);
  const resetMutation = resetPassword.reset;
  const error = describeMutationError(resetPassword.error, "Could not reset the participant password.");

  function clearSensitiveState() {
    resetMutation();
    setSettingPassword(false);
    setPassword("");
    setConfirmation("");
  }

  useEffect(() => () => resetMutation(), [resetMutation]);

  function close() {
    clearSensitiveState();
    setOpen(false);
  }

  const matches = password.length > 0 && password === confirmation;

  return (
    <>
      <Button type="button" variant="outline" size="sm" onClick={() => setOpen(true)}>
        Manage password
      </Button>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (!next) clearSensitiveState();
          setOpen(next);
        }}
      >
        <DialogContent>
          {resetPassword.data ? (
            <>
              <DialogHeader>
                <DialogTitle>Participant password reset</DialogTitle>
                <DialogDescription>
                  A new password was issued for {resetPassword.data.username}. It will not be available after you
                  dismiss this dialog.
                </DialogDescription>
              </DialogHeader>
              <p className="text-sm font-medium">New password</p>
              <code
                aria-label="Issued password"
                className="select-all break-all rounded-md border bg-muted px-3 py-2 font-mono text-sm"
              >
                {resetPassword.data.password}
              </code>
              <DialogFooter>
                <Button type="button" onClick={close}>
                  Dismiss
                </Button>
              </DialogFooter>
            </>
          ) : (
            <>
              <DialogHeader>
                <DialogTitle>Reset participant password</DialogTitle>
                <DialogDescription>
                  Issue a new password for {participantName}. This does not change the event shared-password policy.
                  The result is shown once.
                </DialogDescription>
              </DialogHeader>
              {settingPassword ? (
                <form
                  className="flex flex-col gap-4"
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (!matches) return;
                    resetPassword.mutate(
                      { kind: "set", password },
                      {
                        onSuccess: () => {
                          setPassword("");
                          setConfirmation("");
                        },
                      },
                    );
                  }}
                >
                  <div className="flex flex-col gap-2">
                    <Label htmlFor={`participant-password-${participantId}`}>New password</Label>
                    <Input
                      id={`participant-password-${participantId}`}
                      type="password"
                      autoComplete="new-password"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                    />
                  </div>
                  <div className="flex flex-col gap-2">
                    <Label htmlFor={`participant-password-confirm-${participantId}`}>Confirm new password</Label>
                    <Input
                      id={`participant-password-confirm-${participantId}`}
                      type="password"
                      autoComplete="new-password"
                      value={confirmation}
                      onChange={(event) => setConfirmation(event.target.value)}
                    />
                  </div>
                  {confirmation && !matches ? (
                    <p className="text-sm text-destructive">Passwords must match.</p>
                  ) : null}
                  {error ? (
                    <Alert variant="destructive">
                      <AlertDescription>{error}</AlertDescription>
                    </Alert>
                  ) : null}
                  <DialogFooter>
                    <Button type="button" variant="ghost" onClick={() => setSettingPassword(false)}>
                      Use generated password
                    </Button>
                    <Button type="submit" disabled={!matches || resetPassword.isPending}>
                      Set participant password
                    </Button>
                  </DialogFooter>
                </form>
              ) : (
                <>
                  {error ? (
                    <Alert variant="destructive">
                      <AlertDescription>{error}</AlertDescription>
                    </Alert>
                  ) : null}
                  <DialogFooter>
                    <Button type="button" variant="ghost" onClick={() => setSettingPassword(true)}>
                      Set a password instead
                    </Button>
                    <Button
                      type="button"
                      disabled={resetPassword.isPending}
                      onClick={() => resetPassword.mutate({ kind: "generated" })}
                    >
                      Generate new password
                    </Button>
                  </DialogFooter>
                </>
              )}
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
