import { useId, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import { Loader2 } from "lucide-react";

import { describeMutationError } from "@/api/errors";
import { useCreateNgfw } from "@/api/mission-control";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { missionControlNgfwDetailPath, missionControlNgfwListPath } from "./routes";

interface FormErrors {
  name?: string;
  deploymentProfileId?: string;
  scmCredentialId?: string;
}

function FieldError({ id, message }: Readonly<{ id: string; message?: string }>) {
  if (!message) return null;
  return (
    <p id={id} role="alert" className="text-sm text-destructive">
      {message}
    </p>
  );
}

/** Parse a form field into a positive integer id, or `null` if it isn't one. */
function parsePositiveId(value: string): number | null {
  const trimmed = value.trim();
  if (!/^\d+$/.test(trimmed)) return null;
  const parsed = Number(trimmed);
  return parsed > 0 ? parsed : null;
}

/**
 * NGFW setup form (#1370). Mirrors the only registration path the legacy
 * wizard actually implements (`templates/mission_control/ngfw/wizard.html`):
 * "Use Stored PIN" (`registration_method: "pin"`) against a deployment
 * profile and an SCM credential. The OTP registration method is commented
 * out in the legacy template ("no backend flow implemented yet") and is
 * likewise omitted here.
 *
 * `mission_control/api/urls.py` has no `/api/v1` read endpoint for either
 * deployment profiles or SCM credentials (only `POST credentials/` to create
 * one), so — per the #1370 preflight — the picker for each is a plain
 * numeric id input rather than an invented list call; resolving that gap is
 * tracked by #1328/#1329.
 */
export function NgfwWizardPage() {
  const navigate = useNavigate();
  const createNgfw = useCreateNgfw();

  const [name, setName] = useState("");
  const [deploymentProfileId, setDeploymentProfileId] = useState("");
  const [scmCredentialId, setScmCredentialId] = useState("");
  const [errors, setErrors] = useState<FormErrors>({});

  const nameId = useId();
  const profileId = useId();
  const credentialId = useId();

  const serverError = describeMutationError(createNgfw.error, "The NGFW could not be created.");

  function onSubmit(event: FormEvent) {
    event.preventDefault();

    const nextErrors: FormErrors = {};
    if (!name.trim()) nextErrors.name = "Enter a name for this NGFW.";
    const profile = parsePositiveId(deploymentProfileId);
    if (profile == null) nextErrors.deploymentProfileId = "Enter the deployment profile's credential id.";
    const credential = parsePositiveId(scmCredentialId);
    if (credential == null) nextErrors.scmCredentialId = "Enter the SCM credential's id.";
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;

    createNgfw.mutate(
      {
        name: name.trim(),
        deployment_profile_id: profile,
        registration_method: "pin",
        scm_credential_id: credential,
      },
      { onSuccess: (result) => navigate(missionControlNgfwDetailPath(result.id)) },
    );
  }

  return (
    <div className="mx-auto max-w-2xl">
      <nav className="mb-3 text-sm text-muted-foreground" aria-label="Breadcrumb">
        <Link className="hover:text-foreground" to={missionControlNgfwListPath()}>
          NGFWs
        </Link>
        <span className="px-1.5">/</span>
        <span className="text-foreground">Setup</span>
      </nav>

      <PageHeader title="Setup NGFW" description="Provision a persistent NGFW registered via a stored SCM PIN." />

      {serverError ? (
        <Alert variant="destructive" className="mb-4">
          <AlertTitle>Could not create this NGFW</AlertTitle>
          <AlertDescription>{serverError}</AlertDescription>
        </Alert>
      ) : null}

      <Alert className="mb-4">
        <AlertTitle>Deployment profile / SCM credential pickers are pending</AlertTitle>
        <AlertDescription>
          There is no `/api/v1` read endpoint yet for listing deployment profiles or SCM credentials (#1328,
          #1329), so enter the credential id directly. Credential ids are shown after creating a credential on the{" "}
          <Link className="underline" to="/mission-control/credentials/">
            Credentials
          </Link>{" "}
          page.
        </AlertDescription>
      </Alert>

      <form onSubmit={onSubmit} noValidate>
        <Card>
          <CardContent className="flex flex-col gap-5">
            <div className="flex flex-col gap-2">
              <Label htmlFor={nameId}>NGFW name</Label>
              <Input
                id={nameId}
                placeholder="e.g., My Lab NGFW"
                maxLength={100}
                value={name}
                aria-invalid={errors.name ? true : undefined}
                aria-describedby={errors.name ? `${nameId}-e` : undefined}
                onChange={(event) => setName(event.target.value)}
              />
              <FieldError id={`${nameId}-e`} message={errors.name} />
            </div>

            <div className="flex flex-col gap-2">
              <Label htmlFor={profileId}>Deployment profile credential id</Label>
              <Input
                id={profileId}
                inputMode="numeric"
                placeholder="e.g., 4"
                value={deploymentProfileId}
                aria-invalid={errors.deploymentProfileId ? true : undefined}
                aria-describedby={errors.deploymentProfileId ? `${profileId}-e` : undefined}
                onChange={(event) => setDeploymentProfileId(event.target.value)}
              />
              <p className="text-sm text-muted-foreground">
                The authcode credential used to license this NGFW during provisioning.
              </p>
              <FieldError id={`${profileId}-e`} message={errors.deploymentProfileId} />
            </div>

            <div className="flex flex-col gap-2">
              <Label htmlFor={credentialId}>SCM credential id</Label>
              <Input
                id={credentialId}
                inputMode="numeric"
                placeholder="e.g., 7"
                value={scmCredentialId}
                aria-invalid={errors.scmCredentialId ? true : undefined}
                aria-describedby={errors.scmCredentialId ? `${credentialId}-e` : undefined}
                onChange={(event) => setScmCredentialId(event.target.value)}
              />
              <p className="text-sm text-muted-foreground">
                Registers this NGFW with Strata Cloud Manager using the stored registration PIN.
              </p>
              <FieldError id={`${credentialId}-e`} message={errors.scmCredentialId} />
            </div>
          </CardContent>
          <CardFooter className="justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => navigate(missionControlNgfwListPath())}>
              Cancel
            </Button>
            <Button type="submit" disabled={createNgfw.isPending}>
              {createNgfw.isPending ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : null}
              {createNgfw.isPending ? "Provisioning…" : "Provision NGFW"}
            </Button>
          </CardFooter>
        </Card>
      </form>
    </div>
  );
}
