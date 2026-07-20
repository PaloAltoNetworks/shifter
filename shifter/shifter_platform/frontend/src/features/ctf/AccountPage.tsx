import { useEffect, useState } from "react";

import { useChangeCtfUsername, useCtfProfile, useUpdateCtfProfile } from "@/api/ctf";
import { describeMutationError } from "@/api/errors";
import type { CtfParticipantProfile } from "@/api/types";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";

function MutationError({ error }: Readonly<{ error: unknown }>) {
  const message = describeMutationError(error, "That did not work. Try again.");
  if (!message) return null;
  return <p className="mt-2 text-xs text-destructive">{message}</p>;
}

/** Display name + affiliation form (CTF-610). */
function ProfileForm({ profile }: Readonly<{ profile: CtfParticipantProfile }>) {
  const update = useUpdateCtfProfile();
  const [name, setName] = useState(profile.name);
  const [affiliation, setAffiliation] = useState(profile.affiliation);
  useEffect(() => {
    setName(profile.name);
    setAffiliation(profile.affiliation);
  }, [profile.name, profile.affiliation]);

  const dirty = name.trim() !== profile.name || affiliation.trim() !== profile.affiliation;
  return (
    <Card>
      <CardContent>
        <h2 className="text-sm font-semibold">Profile</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Your display name appears on the scoreboard; affiliation is your team, region, or organization.
        </p>
        <form
          className="mt-3 flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (name.trim() && dirty) update.mutate({ name: name.trim(), affiliation: affiliation.trim() });
          }}
        >
          <div className="flex flex-col gap-1">
            <Label htmlFor="account-name">Display name</Label>
            <Input id="account-name" value={name} onChange={(event) => setName(event.target.value)} />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="account-affiliation">Affiliation</Label>
            <Input
              id="account-affiliation"
              value={affiliation}
              onChange={(event) => setAffiliation(event.target.value)}
            />
          </div>
          <div>
            <Button type="submit" disabled={!name.trim() || !dirty || update.isPending}>
              Save profile
            </Button>
          </div>
        </form>
        <MutationError error={update.error} />
      </CardContent>
    </Card>
  );
}

/** Self-service login-handle change (#1593); isolated CTF accounts only. */
function UsernameForm({ profile }: Readonly<{ profile: CtfParticipantProfile }>) {
  const change = useChangeCtfUsername();
  const [username, setUsername] = useState(profile.username ?? "");
  useEffect(() => setUsername(profile.username ?? ""), [profile.username]);

  if (!profile.username) return null;
  return (
    <Card>
      <CardContent>
        <h2 className="text-sm font-semibold">Login username</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          You sign in with this handle. It must start with <code className="font-mono">range-</code> and stay
          globally unique; you will use the new handle at your next login.
        </p>
        <form
          className="mt-3 flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (username.trim() && username.trim() !== profile.username) {
              change.mutate({ username: username.trim() });
            }
          }}
        >
          <div className="flex min-w-56 flex-1 flex-col gap-1">
            <Label htmlFor="account-username">Username</Label>
            <Input id="account-username" value={username} onChange={(event) => setUsername(event.target.value)} />
          </div>
          <Button
            type="submit"
            variant="outline"
            disabled={!username.trim() || username.trim() === profile.username || change.isPending}
          >
            Change username
          </Button>
        </form>
        <MutationError error={change.error} />
      </CardContent>
    </Card>
  );
}

export function AccountPage() {
  const query = useCtfProfile();

  if (query.isLoading) {
    return (
      <>
        <PageHeader title="Account" />
        <Skeleton className="h-40 w-full" />
      </>
    );
  }

  if (query.isError || !query.data) {
    return (
      <>
        <PageHeader title="Account" />
        <Alert variant="destructive">
          <AlertTitle>Could not load your account</AlertTitle>
          <AlertDescription>Please retry.</AlertDescription>
        </Alert>
      </>
    );
  }

  const profile = query.data;
  return (
    <>
      <PageHeader
        title="Account"
        description={`${profile.event.name} · ${profile.score} points · ${profile.solve_count} solves`}
      />
      <div className="space-y-4">
        {profile.role === "observer" ? (
          <Badge variant="secondary">Observer — you can watch this event but not submit flags</Badge>
        ) : null}
        <ProfileForm profile={profile} />
        <UsernameForm profile={profile} />
      </div>
    </>
  );
}
