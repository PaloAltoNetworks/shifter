import { useState } from "react";

import { useCreateCtfWebhook, useCtfWebhooks, useDeleteCtfWebhook } from "@/api/ctfAdmin";
import { describeMutationError } from "@/api/errors";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/** Outbound webhook registration for event milestones (CTF-1203). */
export function EventWebhooksCard({ eventId }: Readonly<{ eventId: string }>) {
  const webhooks = useCtfWebhooks(eventId);
  const create = useCreateCtfWebhook(eventId);
  const remove = useDeleteCtfWebhook(eventId);
  const [url, setUrl] = useState("");
  const [secret, setSecret] = useState("");
  const errorMessage = describeMutationError(create.error, "Could not register the webhook.");

  return (
    <Card>
      <CardContent className="space-y-4">
        <div>
          <h2 className="text-sm font-semibold">Webhooks</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            POSTs JSON payloads on flag solves, first blood, event state changes, and registrations. Failed
            deliveries retry with backoff; a secret adds an HMAC signature header.
          </p>
        </div>
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (!url.trim()) return;
            create.mutate(
              { url: url.trim(), ...(secret.trim() ? { secret: secret.trim() } : {}) },
              {
                onSuccess: () => {
                  setUrl("");
                  setSecret("");
                },
              },
            );
          }}
        >
          <div className="flex min-w-64 flex-1 flex-col gap-1">
            <Label htmlFor="webhook-url">Endpoint URL</Label>
            <Input id="webhook-url" type="url" value={url} onChange={(e) => setUrl(e.target.value)} />
          </div>
          <div className="flex w-48 flex-col gap-1">
            <Label htmlFor="webhook-secret">Secret (optional)</Label>
            <Input id="webhook-secret" value={secret} onChange={(e) => setSecret(e.target.value)} />
          </div>
          <Button type="submit" disabled={!url.trim() || create.isPending}>
            Add webhook
          </Button>
        </form>
        {create.error ? <p className="text-xs text-destructive">{errorMessage}</p> : null}
        {webhooks.data?.webhooks?.length ? (
          <ul className="divide-y divide-border/60">
            {webhooks.data.webhooks.map((hook) => (
              <li key={hook.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs">{hook.url}</span>
                  {hook.last_status ? (
                    <Badge variant={hook.last_status.startsWith("ok") ? "secondary" : "destructive"}>
                      {hook.last_status}
                    </Badge>
                  ) : null}
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(hook.id)}
                >
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-muted-foreground">No webhooks registered.</p>
        )}
      </CardContent>
    </Card>
  );
}
