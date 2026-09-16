import { useState } from "react";
import { useParams } from "react-router";

import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card } from "@/components/ui/card";

import { Terminal, useTerminalConnectionState } from "./Terminal";
import { ConnectionBadge, TerminalCloseAlert } from "./terminalStatus";

export interface TerminalPageProps {
  instanceUuid?: string;
  tmuxWheelScrolling?: boolean;
}

export function TerminalPage({
  instanceUuid: explicitInstanceUuid,
  tmuxWheelScrolling = false,
}: Readonly<TerminalPageProps> = {}) {
  const { instanceUuid: routeInstanceUuid } = useParams<{ instanceUuid: string }>();
  const instanceUuid = explicitInstanceUuid ?? routeInstanceUuid;
  const [reconnectKey, setReconnectKey] = useState(0);
  const { state, closeInfo, onConnectionStateChange } = useTerminalConnectionState();

  if (!instanceUuid) {
    return (
      <>
        <PageHeader title="Terminal" description="Open a terminal session on a range instance." />
        <Alert variant="destructive">
          <AlertTitle>No instance specified</AlertTitle>
          <AlertDescription>This terminal link is missing an instance to connect to.</AlertDescription>
        </Alert>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Terminal"
        description="SSH session on this range instance."
        actions={<ConnectionBadge state={state} />}
      />

      {state === "closed" && closeInfo ? (
        <TerminalCloseAlert
          closeInfo={closeInfo}
          className="mb-4"
          onReconnect={() => {
            onConnectionStateChange("connecting", null);
            setReconnectKey((key) => key + 1);
          }}
        />
      ) : null}

      <Card className="overflow-hidden p-2">
        <Terminal
          key={reconnectKey}
          instanceUuid={instanceUuid}
          tmuxWheelScrolling={tmuxWheelScrolling}
          onConnectionStateChange={onConnectionStateChange}
        />
      </Card>
    </>
  );
}
