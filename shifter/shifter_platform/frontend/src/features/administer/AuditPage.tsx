/**
 * Administrator audit / activity-history surface (#1947, PLAT-240). Rendered at
 * the deployment-level `/administer/audit`, NOT under a selected workspace: the
 * audit store is deployment-global and has no per-row workspace scope, so the
 * workspace switcher neither filters nor authorizes this feed. Authority lives on
 * the server — `/api/v1/audit/` is staff-session only and re-checks every read.
 *
 * The structured actor / entity / time / action filters are the authoritative
 * search surface and are URL-backed, so a refresh or shared link reproduces the
 * same query with no local storage. Historical rows can carry retired
 * vocabulary, so the filter inputs are free-text/numeric rather than closed
 * enums that would drift from the shared vocabulary. Durable evidence
 * (`previous_state` / `new_state` / `context`, source IP, user agent) is
 * sensitive staff-only data shown only in an explicit, escaped detail disclosure
 * and never treated as current entity state or authorization.
 */
import { useState } from "react";
import { useSearchParams } from "react-router";

import { useAuditEvents, type AuditFilters } from "@/api/audit";
import { ApiError } from "@/api/errors";
import type { AuditLog } from "@/api/types";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import { formatTimestamp } from "./format";

/** Convert a `datetime-local` value to a timezone-aware ISO string for the API.
 * A non-empty but unparseable value is passed through so the server validates it
 * and returns the shared 400 envelope rather than the client silently dropping it. */
function toApiDate(value: string | null): string | undefined {
  if (!value) return undefined;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toISOString();
}

function parseFilters(params: URLSearchParams): AuditFilters {
  const page = Number(params.get("page") ?? "1");
  return {
    action: params.get("action")?.trim() || undefined,
    entityType: params.get("entity_type")?.trim() || undefined,
    // Ids pass through as raw values; the server validates them and returns 400
    // for a malformed value rather than the client silently dropping the filter.
    entityId: params.get("entity_id")?.trim() || undefined,
    actorType: params.get("actor_type")?.trim() || undefined,
    actorId: params.get("actor_id")?.trim() || undefined,
    fromDate: toApiDate(params.get("from")),
    toDate: toApiDate(params.get("to")),
    page: Number.isFinite(page) && page > 1 ? page : undefined,
  };
}

interface DraftFilters {
  action: string;
  entityType: string;
  entityId: string;
  actorType: string;
  actorId: string;
  from: string;
  to: string;
}

function draftFromParams(params: URLSearchParams): DraftFilters {
  return {
    action: params.get("action") ?? "",
    entityType: params.get("entity_type") ?? "",
    entityId: params.get("entity_id") ?? "",
    actorType: params.get("actor_type") ?? "",
    actorId: params.get("actor_id") ?? "",
    from: params.get("from") ?? "",
    to: params.get("to") ?? "",
  };
}

const FILTER_TO_PARAM: Record<keyof DraftFilters, string> = {
  action: "action",
  entityType: "entity_type",
  entityId: "entity_id",
  actorType: "actor_type",
  actorId: "actor_id",
  from: "from",
  to: "to",
};

export function AuditPage() {
  const [params, setParams] = useSearchParams();
  const filters = parseFilters(params);
  const [draft, setDraft] = useState<DraftFilters>(() => draftFromParams(params));
  const query = useAuditEvents(filters);

  const filtersActive = Object.values(FILTER_TO_PARAM).some((param) => Boolean(params.get(param)));

  function applyFilters(event: React.FormEvent) {
    event.preventDefault();
    const next = new URLSearchParams();
    for (const [key, param] of Object.entries(FILTER_TO_PARAM)) {
      const value = draft[key as keyof DraftFilters].trim();
      if (value) next.set(param, value);
    }
    // A filter change resets to the first page.
    setParams(next);
  }

  function clearFilters() {
    setDraft(draftFromParams(new URLSearchParams()));
    setParams(new URLSearchParams());
  }

  function goToPage(page: number) {
    const next = new URLSearchParams(params);
    if (page > 1) {
      next.set("page", String(page));
    } else {
      next.delete("page");
    }
    setParams(next);
  }

  const count = query.data?.count ?? 0;
  const countNoun = count === 1 ? "event" : "events";
  const description = query.data ? `${count} ${countNoun}` : "Search and filter administrative activity";

  return (
    <>
      <PageHeader title="Audit" description={description} />

      <form className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3" onSubmit={applyFilters} role="search">
        <FilterField id="audit-action" label="Event type (action)" value={draft.action} onChange={(v) => setDraft({ ...draft, action: v })} placeholder="e.g. role_sync" />
        <FilterField id="audit-entity-type" label="Entity type" value={draft.entityType} onChange={(v) => setDraft({ ...draft, entityType: v })} placeholder="e.g. workspace_membership" />
        <FilterField id="audit-entity-id" label="Entity id" type="number" value={draft.entityId} onChange={(v) => setDraft({ ...draft, entityId: v })} />
        <FilterField id="audit-actor-type" label="Actor type" value={draft.actorType} onChange={(v) => setDraft({ ...draft, actorType: v })} placeholder="e.g. user" />
        <FilterField id="audit-actor-id" label="Actor id" type="number" value={draft.actorId} onChange={(v) => setDraft({ ...draft, actorId: v })} />
        <div className="hidden lg:block" aria-hidden="true" />
        <FilterField id="audit-from" label="From" type="datetime-local" value={draft.from} onChange={(v) => setDraft({ ...draft, from: v })} />
        <FilterField id="audit-to" label="To" type="datetime-local" value={draft.to} onChange={(v) => setDraft({ ...draft, to: v })} />
        <div className="flex items-end gap-2">
          <Button type="submit" variant="outline" size="sm">
            Apply filters
          </Button>
          {filtersActive ? (
            <Button type="button" variant="ghost" size="sm" onClick={clearFilters}>
              Clear
            </Button>
          ) : null}
        </div>
      </form>

      <Card className="overflow-hidden py-0" aria-busy={query.isFetching}>
        <AuditListBody query={query} filtersActive={filtersActive} />
      </Card>

      {query.data && (query.data.next || query.data.previous) ? (
        <div className="mt-4 flex items-center gap-2">
          <Button variant="outline" size="sm" disabled={!query.data.previous} onClick={() => goToPage((filters.page ?? 1) - 1)}>
            Previous
          </Button>
          <Button variant="outline" size="sm" disabled={!query.data.next} onClick={() => goToPage((filters.page ?? 1) + 1)}>
            Next
          </Button>
        </div>
      ) : null}
    </>
  );
}

function FilterField({
  id,
  label,
  value,
  onChange,
  type = "text",
  placeholder,
}: Readonly<{
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  placeholder?: string;
}>) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type={type}
        value={value}
        placeholder={placeholder}
        min={type === "number" ? 0 : undefined}
        maxLength={type === "text" ? 64 : undefined}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}

function AuditListBody({
  query,
  filtersActive,
}: Readonly<{
  query: ReturnType<typeof useAuditEvents>;
  filtersActive: boolean;
}>) {
  if (query.isLoading) {
    return (
      <div className="space-y-3 p-4">
        {[0, 1, 2, 3].map((row) => (
          <Skeleton key={row} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  if (query.isError) {
    const error = query.error;
    const forbidden = error instanceof ApiError && error.status === 403;
    const invalid = error instanceof ApiError && error.status === 400;
    let title = "Could not load audit events";
    let detail = "Please retry. If the problem persists, contact an administrator.";
    if (forbidden) {
      title = "You do not have permission to view audit events";
      detail = "The audit log requires a staff session. Contact an administrator if you believe this is an error.";
    } else if (invalid) {
      title = "Those filters are not valid";
      detail = "Check the ids and the date range (the start must not be after the end), then try again.";
    }
    return (
      <div className="p-4">
        <Alert variant="destructive">
          <AlertTitle>{title}</AlertTitle>
          <AlertDescription>{detail}</AlertDescription>
        </Alert>
      </div>
    );
  }

  const results = query.data?.results ?? [];
  if (results.length === 0) {
    return (
      <div className="grid place-items-center px-6 py-16 text-center">
        <p className="text-sm font-medium">{filtersActive ? "No events match these filters" : "No audit events yet"}</p>
        <p className="mt-1 text-sm text-muted-foreground">
          {filtersActive ? "Adjust or clear the filters to see more." : "Administrative activity appears here as it happens."}
        </p>
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="w-[200px]">Time</TableHead>
          <TableHead className="w-[160px]">Action</TableHead>
          <TableHead>Entity</TableHead>
          <TableHead>Actor</TableHead>
          <TableHead className="w-[220px]">Details</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {results.map((event) => (
          <TableRow key={event.id}>
            <TableCell className="text-sm text-muted-foreground">{formatTimestamp(event.timestamp)}</TableCell>
            <TableCell className="font-medium">{event.action}</TableCell>
            <TableCell className="text-sm">
              {event.entity_type} #{event.entity_id}
            </TableCell>
            <TableCell className="text-sm">
              {event.actor_type}
              {event.actor_id === null ? "" : ` #${event.actor_id}`}
            </TableCell>
            <TableCell>
              <AuditDetail event={event} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/** Explicit, escaped disclosure of the sensitive durable evidence for one row.
 * Minimal by default: the evidence is not rendered into the DOM until the staff
 * user opens the disclosure. React escapes all rendered text; nothing here uses
 * dangerouslySetInnerHTML, and state/context is shown as data, never interpreted
 * as HTML or as current entity state. */
function AuditDetail({ event }: Readonly<{ event: AuditLog }>) {
  const [open, setOpen] = useState(false);

  const rows: [string, string][] = [];
  if (event.request_id) rows.push(["Request id", event.request_id]);
  if (event.source_ip) rows.push(["Source IP", event.source_ip]);
  if (event.user_agent) rows.push(["User agent", event.user_agent]);
  if (event.context) rows.push(["Context", event.context]);
  const hasState = event.previous_state != null || event.new_state != null;

  if (rows.length === 0 && !hasState) {
    return <span className="text-sm text-muted-foreground">—</span>;
  }

  return (
    <div className="text-sm">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        {open ? "Hide details" : "View details"}
      </Button>
      {open ? (
        <div className="mt-2">
          <dl className="grid grid-cols-1 gap-1">
            {rows.map(([term, value]) => (
              <div key={term} className="flex flex-col">
                <dt className="text-xs text-muted-foreground">{term}</dt>
                <dd className="break-all">{value}</dd>
              </div>
            ))}
          </dl>
          {hasState ? (
            <pre className="mt-2 max-h-64 overflow-auto rounded bg-muted p-2 text-xs">
              {JSON.stringify({ previous_state: event.previous_state, new_state: event.new_state }, null, 2)}
            </pre>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
