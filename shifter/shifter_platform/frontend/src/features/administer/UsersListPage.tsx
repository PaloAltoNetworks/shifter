import { useState } from "react";
import { Link, useSearchParams } from "react-router";

import { useAdminUsers, type AdminUserFilters } from "@/api/administer";
import { ApiError } from "@/api/errors";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

import { AccountOriginBadge, AccountStatusBadge, RoleBadge } from "./badges";
import { formatTimestamp, titleCase } from "./format";
import { userPath } from "./routes";

const ALL = "all";

const USER_TYPES = ["standard", "ctf_organizer", "ctf_participant"] as const;
const ACCOUNT_ORIGINS = ["provider", "local", "ctf"] as const;

/** Parse a tri-state boolean URL param ("true"/"false"/absent). */
function parseTristateBool(value: string | null): boolean | undefined {
  if (value === "true") return true;
  if (value === "false") return false;
  return undefined;
}

/** Map the `isActive` filter to its Select control value. */
function activeFilterValue(isActive: boolean | undefined): string {
  if (isActive === undefined) return ALL;
  return isActive ? "true" : "false";
}

function parseFilters(params: URLSearchParams): AdminUserFilters {
  const page = Number(params.get("page") ?? "1");
  return {
    search: params.get("q")?.trim() || undefined,
    userType: USER_TYPES.includes(params.get("type") as (typeof USER_TYPES)[number])
      ? (params.get("type") as string)
      : undefined,
    isActive: parseTristateBool(params.get("active")),
    accountOrigin: ACCOUNT_ORIGINS.includes(params.get("origin") as (typeof ACCOUNT_ORIGINS)[number])
      ? (params.get("origin") as string)
      : undefined,
    includeDeleted: params.get("deleted") === "1",
    page: Number.isFinite(page) && page > 1 ? page : undefined,
  };
}

export function UsersListPage() {
  const [params, setParams] = useSearchParams();
  const filters = parseFilters(params);
  const [searchInput, setSearchInput] = useState(filters.search ?? "");
  const query = useAdminUsers(filters);

  const filtersActive = Boolean(
    filters.search || filters.userType || filters.isActive !== undefined || filters.accountOrigin || filters.includeDeleted,
  );

  function updateParam(key: string, value: string | null) {
    const next = new URLSearchParams(params);
    if (value) {
      next.set(key, value);
    } else {
      next.delete(key);
    }
    next.delete("page");
    setParams(next);
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
  const countNoun = count === 1 ? "user" : "users";
  const description = query.data ? `${count} ${countNoun}` : "Manage platform users and access";

  return (
    <>
      <PageHeader title="Users" description={description} />

      <form
        className="mb-4 flex flex-wrap items-center gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          updateParam("q", searchInput.trim() || null);
        }}
        role="search"
      >
        <Input
          type="search"
          value={searchInput}
          onChange={(event) => setSearchInput(event.target.value)}
          placeholder="Search username or email"
          aria-label="Search users by username or email"
          className="w-[240px]"
          maxLength={100}
        />
        <Button type="submit" variant="outline" size="sm">
          Search
        </Button>

        <Select value={filters.userType ?? ALL} onValueChange={(value) => updateParam("type", value === ALL ? null : value)}>
          <SelectTrigger size="sm" className="w-[170px]" aria-label="Filter by account type">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All types</SelectItem>
            {USER_TYPES.map((value) => (
              <SelectItem key={value} value={value}>
                {titleCase(value.replaceAll("_", " "))}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select
          value={activeFilterValue(filters.isActive)}
          onValueChange={(value) => updateParam("active", value === ALL ? null : value)}
        >
          <SelectTrigger size="sm" className="w-[150px]" aria-label="Filter by status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All statuses</SelectItem>
            <SelectItem value="true">Active</SelectItem>
            <SelectItem value="false">Disabled</SelectItem>
          </SelectContent>
        </Select>

        <Select
          value={filters.accountOrigin ?? ALL}
          onValueChange={(value) => updateParam("origin", value === ALL ? null : value)}
        >
          <SelectTrigger size="sm" className="w-[150px]" aria-label="Filter by account origin">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All origins</SelectItem>
            {ACCOUNT_ORIGINS.map((value) => (
              <SelectItem key={value} value={value}>
                {titleCase(value)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <label className="flex select-none items-center gap-2 text-sm text-muted-foreground">
          <input
            type="checkbox"
            className="size-4 rounded border-input bg-transparent accent-primary"
            checked={filters.includeDeleted ?? false}
            onChange={(event) => updateParam("deleted", event.target.checked ? "1" : null)}
          />
          <span>Show deleted</span>
        </label>
      </form>

      <Card className="overflow-hidden py-0" aria-busy={query.isFetching}>
        <UsersListBody query={query} filtersActive={filtersActive} />
      </Card>

      {query.data && (query.data.next || query.data.previous) ? (
        <div className="mt-4 flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={!query.data.previous}
            onClick={() => goToPage((filters.page ?? 1) - 1)}
          >
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

function UsersListBody({
  query,
  filtersActive,
}: Readonly<{
  query: ReturnType<typeof useAdminUsers>;
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
    const forbidden = query.error instanceof ApiError && query.error.status === 403;
    return (
      <div className="p-4">
        <Alert variant="destructive">
          <AlertTitle>{forbidden ? "You do not have permission to view users" : "Could not load users"}</AlertTitle>
          <AlertDescription>
            {forbidden ? "Ask an administrator to grant you user-view access." : "Please retry."}
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  const results = query.data?.results ?? [];
  if (results.length === 0) {
    return (
      <div className="grid place-items-center px-6 py-16 text-center">
        <p className="text-sm font-medium">{filtersActive ? "No users match these filters" : "No users yet"}</p>
        <p className="mt-1 text-sm text-muted-foreground">
          {filtersActive ? "Adjust or clear the filters to see more." : "Users appear here once accounts exist."}
        </p>
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead>User</TableHead>
          <TableHead className="w-[120px]">Origin</TableHead>
          <TableHead className="w-[140px]">Type</TableHead>
          <TableHead className="w-[130px]">Status</TableHead>
          <TableHead>Roles</TableHead>
          <TableHead className="w-[180px]">Joined</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {results.map((user) => (
          <TableRow key={user.id}>
            <TableCell className="font-medium">
              <Link className="hover:underline" to={userPath(user.id)}>
                {user.display_name}
              </Link>
              <div className="text-xs text-muted-foreground">{user.email || user.username}</div>
            </TableCell>
            <TableCell>
              <AccountOriginBadge origin={user.account_origin} />
            </TableCell>
            <TableCell className="text-sm text-muted-foreground">{titleCase(user.user_type.replaceAll("_", " "))}</TableCell>
            <TableCell>
              <AccountStatusBadge isActive={user.is_active} isDeleted={user.is_deleted} />
            </TableCell>
            <TableCell>
              <div className="flex flex-wrap gap-1.5">
                {user.is_superuser ? <RoleBadge label="Superuser" /> : null}
                {user.is_staff ? <RoleBadge label="Staff" /> : null}
                {user.is_ctf_organizer ? <RoleBadge label="Organizer" /> : null}
              </div>
            </TableCell>
            <TableCell className="text-sm text-muted-foreground">{formatTimestamp(user.date_joined)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
