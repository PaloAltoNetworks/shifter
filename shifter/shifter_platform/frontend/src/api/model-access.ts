/**
 * Scoped model-access management API client (M09, #2126 / PLAT-202).
 *
 * Typed access to the sharing/catalog binding boundary (validate / selector- and
 * policy-preview / publish / drain), the organizer event assessment, the range
 * revoke action, and the participant's own-range read. Mutations never auto-retry
 * and route through the same-origin `apiFetch` client so session/CSRF is handled
 * centrally; a stale-revision publish/drain surfaces a 409 the caller must reload.
 */
import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "./client";
import type { components } from "./schema";

export type SelectorPreview = components["schemas"]["SelectorPreviewResponse"];
export type EffectivePolicyPreview = components["schemas"]["EffectivePolicyResponse"];
export type BindingRevision = components["schemas"]["RevisionResponse"];
export type EventModelAssessment = components["schemas"]["EventModelAccessAssessment"];
export type ParticipantModelAccess = components["schemas"]["ParticipantModelAccess"];

const BINDINGS = "/model-access/bindings";

export function validateBinding(binding: unknown, pool: unknown) {
  return apiFetch<{ valid: boolean }>(`${BINDINGS}/validate/`, { method: "POST", body: { binding, pool } });
}

export function previewSelector(selector: unknown) {
  return apiFetch<SelectorPreview>(`${BINDINGS}/selector-preview/`, { method: "POST", body: { selector } });
}

export function previewEffectivePolicy(subject: unknown) {
  return apiFetch<EffectivePolicyPreview>(`${BINDINGS}/policy-preview/`, { method: "POST", body: { subject } });
}

export function publishBinding(binding: unknown, pool: unknown, expectedRevision: number, emptySnapshotAck = false) {
  return apiFetch<BindingRevision>(`${BINDINGS}/publish/`, {
    method: "POST",
    body: { binding, pool, expected_definition_revision: expectedRevision, empty_snapshot_ack: emptySnapshotAck },
  });
}

export function drainBinding(sharingBindingId: string, expectedRevision: number) {
  return apiFetch<BindingRevision>(`${BINDINGS}/drain/`, {
    method: "POST",
    body: { sharing_binding_id: sharingBindingId, expected_definition_revision: expectedRevision },
  });
}

export function revokeRangeModelAccess(requestId: string) {
  return apiFetch<components["schemas"]["RangeModelSources"]>(`/cms/ranges/${requestId}/model-sources/revoke/`, {
    method: "POST",
    body: {},
  });
}

export function useEventModelAssessment(eventId: string) {
  return useQuery({
    queryKey: ["model-access-assessment", eventId],
    enabled: Boolean(eventId),
    queryFn: ({ signal }) =>
      apiFetch<EventModelAssessment>(`/ctf/events/${eventId}/model-access/assessment/`, { signal }),
  });
}

export function useParticipantModelAccess(enabled = true) {
  return useQuery({
    queryKey: ["participant-model-access"],
    enabled,
    queryFn: ({ signal }) => apiFetch<ParticipantModelAccess>("/ctf/me/model-access/", { signal }),
  });
}
