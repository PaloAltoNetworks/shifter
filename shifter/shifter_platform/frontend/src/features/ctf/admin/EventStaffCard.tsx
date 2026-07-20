import { useState } from "react";

import { useAssignCtfEventStaff, useCtfEventStaff, useRevokeCtfEventStaff } from "@/api/ctfAdmin";
import { describeMutationError } from "@/api/errors";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

/** Delegated staff management (CTF-607): moderators and judges by email. */
export function EventStaffCard({ eventId }: Readonly<{ eventId: string }>) {
  const staff = useCtfEventStaff(eventId);
  const assign = useAssignCtfEventStaff(eventId);
  const revoke = useRevokeCtfEventStaff(eventId);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("moderator");

  const assignError = describeMutationError(assign.error, "Could not assign staff.");
  const revokeError = describeMutationError(revoke.error, "Could not remove staff.");

  return (
    <Card>
      <CardContent className="space-y-4">
        <div>
          <h2 className="text-sm font-semibold">Event staff</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Moderators manage participants and announcements; judges review submissions and grant awards. Staff
            need an organizer account and never gain access to event configuration or challenges.
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
            <Select value={role} onValueChange={setRole}>
              <SelectTrigger id="staff-role" className="w-36">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="moderator">Moderator</SelectItem>
                <SelectItem value="judge">Judge</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Button type="submit" disabled={!email.trim() || assign.isPending}>
            Add staff
          </Button>
        </form>
        {assign.error ? <p className="text-xs text-destructive">{assignError}</p> : null}
        {revoke.error ? <p className="text-xs text-destructive">{revokeError}</p> : null}
        {staff.data?.staff?.length ? (
          <ul className="divide-y divide-border/60">
            {staff.data.staff.map((member) => (
              <li key={member.user_id} className="flex items-center justify-between gap-3 py-2 text-sm">
                <span>
                  {member.email} <span className="text-muted-foreground">· {member.role}</span>
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  disabled={revoke.isPending}
                  onClick={() => revoke.mutate(member.user_id)}
                >
                  Remove
                </Button>
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
