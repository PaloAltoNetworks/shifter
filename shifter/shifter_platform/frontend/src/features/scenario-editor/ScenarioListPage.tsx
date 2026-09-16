import { useMemo, useState } from "react";
import { Link } from "react-router";

import { useScenarioCatalog } from "@/api/scenarios";
import type { ScenarioCatalogEntry } from "@/api/types";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import { EnabledBadge, SourceBadge, StaffOnlyBadge } from "./badges";
import { titleCase } from "./format";
import { scenarioPath } from "./routes";

const ALL = "all";
const SOURCES = ["raes"] as const;

export function ScenarioListPage() {
  const query = useScenarioCatalog();

  const [search, setSearch] = useState("");
  const [source, setSource] = useState<string>(ALL);
  const [availability, setAvailability] = useState<string>(ALL);

  const filtersActive = Boolean(search.trim() || source !== ALL || availability !== ALL);

  const entries = useMemo(() => {
    const all = query.data ?? [];
    const term = search.trim().toLowerCase();
    return all.filter((entry) => {
      if (term && !entry.name.toLowerCase().includes(term) && !entry.id.toLowerCase().includes(term)) {
        return false;
      }
      if (source !== ALL && entry.source !== source) {
        return false;
      }
      if (availability === "enabled" && !entry.enabled) return false;
      if (availability === "disabled" && entry.enabled) return false;
      return true;
    });
  }, [query.data, search, source, availability]);

  const total = query.data?.length ?? 0;
  const noun = total === 1 ? "scenario" : "scenarios";
  const description = query.data ? `${total} ${noun} in the catalog` : "Scenario catalog";

  return (
    <>
      <PageHeader title="Scenarios" description={description} />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search scenarios"
          aria-label="Search scenarios"
          className="h-9 w-[220px]"
        />
        <Select value={source} onValueChange={setSource}>
          <SelectTrigger size="sm" className="w-[160px]" aria-label="Filter by source">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All sources</SelectItem>
            {SOURCES.map((value) => (
              <SelectItem key={value} value={value}>
                {titleCase(value)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={availability} onValueChange={setAvailability}>
          <SelectTrigger size="sm" className="w-[160px]" aria-label="Filter by availability">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All availability</SelectItem>
            <SelectItem value="enabled">Enabled</SelectItem>
            <SelectItem value="disabled">Disabled</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <Card className="overflow-hidden py-0" aria-busy={query.isFetching}>
        <ScenarioListBody query={query} entries={entries} filtersActive={filtersActive} />
      </Card>
    </>
  );
}

function ScenarioListBody({
  query,
  entries,
  filtersActive,
}: Readonly<{
  query: ReturnType<typeof useScenarioCatalog>;
  entries: ScenarioCatalogEntry[];
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
    return (
      <div className="p-4">
        <Alert variant="destructive">
          <AlertTitle>Could not load scenarios</AlertTitle>
          <AlertDescription>Please retry.</AlertDescription>
        </Alert>
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <div className="grid place-items-center px-6 py-16 text-center">
        <p className="text-sm font-medium">{filtersActive ? "No scenarios match these filters" : "No scenarios yet"}</p>
        <p className="mt-1 text-sm text-muted-foreground">
          {filtersActive ? "Adjust or clear the filters to see more." : "Register a RAES pack to populate the catalog."}
        </p>
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead>Name</TableHead>
          <TableHead className="w-[130px]">Source</TableHead>
          <TableHead className="w-[220px]">Availability</TableHead>
          <TableHead className="w-[120px]">Launchable</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {entries.map((entry) => (
          <TableRow key={entry.id}>
            <TableCell className="font-medium">
              <Link className="hover:underline" to={scenarioPath(entry.id)}>
                {entry.name}
              </Link>
              <span className="ml-2 font-mono text-xs text-muted-foreground">{entry.id}</span>
            </TableCell>
            <TableCell>
              <SourceBadge source={entry.source} />
            </TableCell>
            <TableCell>
              <div className="flex flex-wrap items-center gap-1.5">
                <EnabledBadge enabled={entry.enabled} />
                {entry.staff_only ? <StaffOnlyBadge /> : null}
              </div>
            </TableCell>
            <TableCell className="text-sm text-muted-foreground">{entry.launchable ? "Yes" : "No"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
