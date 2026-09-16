/**
 * Organization settings surface (#1939, PLAT-232). Replaces the PLAT-231 route
 * slot with a real read/edit form over the organization profile.
 *
 * Authority lives on the server: `/api/v1/workspaces/organizations/{uuid}/`
 * authorizes an organization admin (or a superuser override) via ADR-048 and is
 * the audit boundary. This surface only presents the profile and posts a PATCH;
 * it never compares roles client-side. Organizations are addressed by public
 * UUID, and selection is always explicit — the chooser lists the principal's
 * reachable organizations (or opens the only one) rather than guessing.
 */
import { useEffect, useState } from "react";
import { Link, Navigate, useParams } from "react-router";

import {
  useAdministrableOrganizations,
  useOrganizationProfile,
  useUpdateOrganizationProfile,
} from "@/api/organization";
import { ApiError } from "@/api/errors";
import type { OrganizationProfile, OrganizationProfileUpdate } from "@/api/types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";

import { organizationSettingsPath } from "../routes";

/** Chooser: pick which administrable organization to edit (or open the only one).
 *
 * Driven by the authority-owned list endpoint (ADR-048), never by workspace
 * reachability, so the actor is offered exactly the organizations they may edit.
 */
export function OrganizationSettingsPage() {
  const query = useAdministrableOrganizations();

  if (query.isLoading) {
    return <Skeleton className="h-40 w-full max-w-xl" />;
  }
  if (query.isError || !query.data) {
    return (
      <Alert variant="destructive" className="max-w-xl">
        <AlertTitle>Could not load your organizations</AlertTitle>
        <AlertDescription>Please retry. If the problem persists, contact an administrator.</AlertDescription>
      </Alert>
    );
  }

  const organizations = query.data.results;

  if (organizations.length === 1) {
    return <Navigate to={organizationSettingsPath(organizations[0].uuid)} replace />;
  }

  if (organizations.length === 0) {
    return (
      <Alert className="max-w-xl">
        <AlertTitle>No organizations available</AlertTitle>
        <AlertDescription>You do not administer any organization yet.</AlertDescription>
      </Alert>
    );
  }

  return (
    <Card className="max-w-xl p-6">
      <h2 className="text-sm font-medium">Choose an organization to administer</h2>
      <ul className="mt-3 space-y-2">
        {organizations.map((organization) => (
          <li key={organization.uuid}>
            <Link to={organizationSettingsPath(organization.uuid)} className="text-sm text-foreground/90 hover:underline">
              {organization.name}
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  );
}

interface FormState {
  name: string;
  description: string;
  support_email: string;
  support_url: string;
}

function toFormState(data: OrganizationProfile): FormState {
  return {
    name: data.name,
    description: data.description,
    support_email: data.support_email,
    support_url: data.support_url,
  };
}

function loadErrorTitle(error: unknown): string {
  if (error instanceof ApiError && error.status === 403) return "You do not have permission to manage this organization";
  return "Could not load the organization";
}

/** Editor: view and edit one organization's profile, keyed by its public UUID. */
export function OrganizationSettingsDetailPage() {
  const { organizationUuid } = useParams();
  const uuid = organizationUuid ?? "";
  const query = useOrganizationProfile(uuid);

  if (query.isLoading) {
    return <Skeleton className="h-64 w-full max-w-xl" />;
  }
  if (query.isError || !query.data) {
    return (
      <Alert variant="destructive" className="max-w-xl">
        <AlertTitle>{loadErrorTitle(query.error)}</AlertTitle>
        <AlertDescription>
          <Link to={organizationSettingsPath()} className="underline">
            Back to organizations
          </Link>
        </AlertDescription>
      </Alert>
    );
  }

  return <OrganizationSettingsForm uuid={uuid} data={query.data} />;
}

function changedFields(form: FormState, baseline: FormState): OrganizationProfileUpdate {
  const changes: OrganizationProfileUpdate = {};
  for (const field of Object.keys(form) as (keyof FormState)[]) {
    if (form[field] !== baseline[field]) {
      changes[field] = form[field];
    }
  }
  return changes;
}

function OrganizationSettingsForm({ uuid, data }: Readonly<{ uuid: string; data: OrganizationProfile }>) {
  const [form, setForm] = useState<FormState>(() => toFormState(data));
  // The last server snapshot the form is diffed against, so only fields the user
  // actually changed are sent (the PATCH mask). Sending an untouched field would
  // let a stale form revert another admin's concurrent edit to it.
  const [baseline, setBaseline] = useState<FormState>(() => toFormState(data));
  const [saved, setSaved] = useState(false);
  const mutation = useUpdateOrganizationProfile(uuid);

  // Re-seed the form and baseline when a fresh server snapshot arrives.
  useEffect(() => {
    const next = toFormState(data);
    setForm(next);
    setBaseline(next);
  }, [data]);

  const fieldErrors = mutation.error instanceof ApiError ? mutation.error.fieldErrors() : {};
  const topLevelError =
    mutation.error instanceof ApiError && Object.keys(fieldErrors).length === 0 ? mutation.error.message : null;

  function update(field: keyof FormState, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
    setSaved(false);
  }

  function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSaved(false);
    mutation.mutate(changedFields(form, baseline), { onSuccess: () => setSaved(true) });
  }

  return (
    <Card className="max-w-xl p-6">
      <form className="space-y-5" onSubmit={onSubmit} aria-label="Organization settings">
        <Field id="org-name" label="Display name" errors={fieldErrors.name}>
          <Input
            id="org-name"
            value={form.name}
            aria-invalid={fieldErrors.name ? true : undefined}
            onChange={(event) => update("name", event.target.value)}
          />
        </Field>
        <Field id="org-description" label="Description" errors={fieldErrors.description}>
          <Textarea
            id="org-description"
            rows={3}
            value={form.description}
            aria-invalid={fieldErrors.description ? true : undefined}
            onChange={(event) => update("description", event.target.value)}
          />
        </Field>
        <Field id="org-support-email" label="Support email" errors={fieldErrors.support_email}>
          <Input
            id="org-support-email"
            type="email"
            value={form.support_email}
            aria-invalid={fieldErrors.support_email ? true : undefined}
            onChange={(event) => update("support_email", event.target.value)}
          />
        </Field>
        <Field id="org-support-url" label="Support URL" errors={fieldErrors.support_url}>
          <Input
            id="org-support-url"
            type="url"
            value={form.support_url}
            aria-invalid={fieldErrors.support_url ? true : undefined}
            onChange={(event) => update("support_url", event.target.value)}
          />
        </Field>

        {topLevelError ? (
          <Alert variant="destructive">
            <AlertTitle>Could not save changes</AlertTitle>
            <AlertDescription>{topLevelError}</AlertDescription>
          </Alert>
        ) : null}
        {saved && !mutation.isPending ? (
          <output className="text-sm text-muted-foreground">Saved.</output>
        ) : null}

        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? "Saving…" : "Save changes"}
        </Button>
      </form>
    </Card>
  );
}

function Field({
  id,
  label,
  errors,
  children,
}: Readonly<{ id: string; label: string; errors?: string[]; children: React.ReactNode }>) {
  const errorId = `${id}-error`;
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {errors?.length ? (
        <p id={errorId} className="text-sm text-destructive">
          {errors.join(" ")}
        </p>
      ) : null}
    </div>
  );
}
