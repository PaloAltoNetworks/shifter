import { useState } from "react";

import {
  useAssignCtfEventStaff,
  useCtfEventStaff,
  useRevokeCtfEventStaff,
  useTransferCtfEventOwnership,
} from "@/api/ctfAdmin";
import { describeMutationError } from "@/api/errors";
import type { CtfEventStaffAssignRequest } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

/**
 * Delegated staff management (CTF-607, #1922): moderators, judges, and full
 * co-organizers by email. Staff management and ownership transfer are owner-only,
 * so this card renders only for the event owner (`canManage`). Ownership can be
 * handed to a current co-organizer via "Make owner".
 */
export function EventStaffCard({ eventId, canManage = true }: Readonly<{ eventId: string; canManage?: boolean }>) {
  const staff = useCtfEventStaff(eventId, canManage);
  const assign = useAssignCtfEventStaff(eventId);
  const revoke = useRevokeCtfEventStaff(eventId);
  const transfer = useTransferCtfEventOwnership(eventId);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<CtfEventStaffAssignRequest["role"]>("moderator");

  const assignError = describeMutationError(assign.error, "Could not assign staff.");
  const revokeError = describeMutationError(revoke.error, "Could not remove staff.");
  const transferError = describeMutationError(transfer.error, "Could not transfer ownership.");

  if (!canManage) {
    return null;
  }

  return (
    <Card>
      <CardContent className="space-y-4">
        <div>
          <h2 className="text-sm font-semibold">Event staff</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Moderators manage participants and announcements; judges review submissions and grant awards; co-organizers
            hold every operational capability the owner has (configuration, challenges, participants, lifecycle,
            deletion) but cannot manage staff or transfer ownership. Staff need an organizer account.
          </p>
        </div>
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (email.trim()) {
              assign.mutate({ email: email.trim(), role }, { onSuccess: () => setEmail("") });
            }
          }}
        >
          <div className="flex min-w-56 flex-1 flex-col gap-1">
            <Label htmlFor="staff-email">Organizer email</Label>
            <Input id="staff-email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="staff-role">Role</Label>
            <Select value={role} onValueChange={(value) => setRole(value as CtfEventStaffAssignRequest["role"])}>
              <SelectTrigger id="staff-role" className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="moderator">Moderator</SelectItem>
                <SelectItem value="judge">Judge</SelectItem>
                <SelectItem value="co_organizer">Co-organizer</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Button type="submit" disabled={!email.trim() || assign.isPending}>
            Add staff
          </Button>
        </form>
        {assign.error ? <p className="text-xs text-destructive">{assignError}</p> : null}
        {revoke.error ? <p className="text-xs text-destructive">{revokeError}</p> : null}
        {transfer.error ? <p className="text-xs text-destructive">{transferError}</p> : null}
        {staff.data?.staff?.length ? (
          <ul className="divide-y divide-border/60">
            {staff.data.staff.map((member) => (
              <li key={member.user_id} className="flex items-center justify-between gap-3 py-2 text-sm">
                <span>
                  {member.email} <span className="text-muted-foreground">· {member.role}</span>
                </span>
                <div className="flex items-center gap-1">
                  {member.role === "co_organizer" ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      disabled={transfer.isPending}
                      onClick={() => transfer.mutate(member.user_id)}
                    >
                      Make owner
                    </Button>
                  ) : null}
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    disabled={revoke.isPending}
                    onClick={() => revoke.mutate(member.user_id)}
                  >
                    Remove
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-muted-foreground">No staff assigned.</p>
        )}
      </CardContent>
    </Card>
  );
}
