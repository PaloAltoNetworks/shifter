/**
 * Domain types for the Risk Register, re-exported from the generated OpenAPI
 * schema (`schema.d.ts`, produced by `npm run gen:api`). Do not hand-copy Risk,
 * Comment, AuditLog, severity, status, or STRIDE shapes — regenerate instead.
 */
import type { components } from "./schema";

export type Risk = components["schemas"]["Risk"];
export type RiskCreate = components["schemas"]["RiskCreate"];
export type RiskUpdate = components["schemas"]["RiskUpdate"];
export type PatchedRiskUpdate = components["schemas"]["PatchedRiskUpdate"];
export type Comment = components["schemas"]["Comment"];
export type AuditLog = components["schemas"]["AuditLog"];
export type PaginatedRiskList = components["schemas"]["PaginatedRiskList"];
export type PaginatedAuditLogList = components["schemas"]["PaginatedAuditLogList"];
export type Bootstrap = components["schemas"]["Bootstrap"];

export type Severity = components["schemas"]["SeverityEnum"];
export type Status = components["schemas"]["StatusEnum"];

export type StrideCode = "S" | "T" | "R" | "I" | "D" | "E";

/**
 * Runtime option lists for filters/forms. Typed against the generated enums so
 * an invalid value fails typecheck; the backend serializers remain the
 * authoritative validator (these are UI affordances only).
 */
export const SEVERITIES: readonly Severity[] = ["critical", "high", "medium", "low"];
export const STATUSES: readonly Status[] = ["open", "acknowledged", "mitigating", "resolved", "closed"];
export const STRIDE_OPTIONS: ReadonlyArray<{ code: StrideCode; label: string }> = [
  { code: "S", label: "Spoofing" },
  { code: "T", label: "Tampering" },
  { code: "R", label: "Repudiation" },
  { code: "I", label: "Information Disclosure" },
  { code: "D", label: "Denial of Service" },
  { code: "E", label: "Elevation of Privilege" },
];

/** Normalize the JSONField `stride_categories` (typed `unknown`) into a string list. */
export function strideList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}
