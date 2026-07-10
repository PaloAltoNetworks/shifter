import { Outlet } from "react-router-dom";

import { ShieldOff } from "lucide-react";

import { AppShell } from "@/components/app-shell";

import { BootstrapProvider, useBootstrapContext } from "./bootstrap-context";

function AccessDenied() {
  // Advisory only; does not reveal whether any specific risk exists. The API
  // remains the authoritative boundary and returns 403 regardless.
  return (
    <div className="grid place-items-center py-24 text-center">
      <div className="max-w-sm">
        <ShieldOff className="mx-auto mb-4 size-8 text-muted-foreground" />
        <h1 className="text-lg font-semibold tracking-tight">Access denied</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          You do not have access to the Risk Register. Contact an administrator if you believe this is an error.
        </p>
      </div>
    </div>
  );
}

function WorkspaceFrame() {
  const bootstrap = useBootstrapContext();
  return (
    <AppShell principalName={bootstrap.principal.display_name}>
      {bootstrap.permissions.can_access_risk_register ? <Outlet /> : <AccessDenied />}
    </AppShell>
  );
}

export function RootLayout() {
  return (
    <BootstrapProvider>
      <WorkspaceFrame />
    </BootstrapProvider>
  );
}
