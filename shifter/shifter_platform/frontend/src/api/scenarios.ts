/**
 * TanStack Query hooks for the Scenario Editor API surface (#1371). All caching,
 * invalidation, and retry policy live here; components call these hooks and never
 * fetch directly. The SPA uses the canonical `/api/v1/cms/` DRF routes only — it
 * never touches the legacy `/scenario-editor/` Django form/action URLs.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "./client";
import type {
  ScenarioCatalogEntry,
  ScenarioClone,
  ScenarioCreate,
  ScenarioCreated,
  ScenarioDetail,
  ScenarioExport,
  ScenarioMetadataState,
  ScenarioMetadataUpdate,
  ScenarioUpdate,
  ScenarioYamlValidation,
} from "./types";

const BASE = "/cms/scenario-editor/scenarios";

export const scenarioKeys = {
  all: ["scenarios"] as const,
  catalog: () => ["scenarios", "catalog"] as const,
  detail: (id: string) => ["scenarios", "detail", id] as const,
};

function invalidateScenarios(queryClient: ReturnType<typeof useQueryClient>, scenarioId?: string) {
  queryClient.invalidateQueries({ queryKey: scenarioKeys.all });
  if (scenarioId !== undefined) {
    queryClient.invalidateQueries({ queryKey: scenarioKeys.detail(scenarioId) });
  }
}

export function useScenarioCatalog() {
  return useQuery({
    queryKey: scenarioKeys.catalog(),
    queryFn: ({ signal }) => apiFetch<ScenarioCatalogEntry[]>("/cms/catalog/", { signal }),
  });
}

export function useScenario(scenarioId: string, enabled = true) {
  return useQuery({
    queryKey: scenarioKeys.detail(scenarioId),
    enabled: enabled && Boolean(scenarioId),
    queryFn: ({ signal }) => apiFetch<ScenarioDetail>(`${BASE}/${scenarioId}/`, { signal }),
  });
}

export function useCreateScenario() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ScenarioCreate) => apiFetch<ScenarioCreated>(`${BASE}/`, { method: "POST", body }),
    onSuccess: () => invalidateScenarios(queryClient),
  });
}

export function useCreateScenarioFromYaml() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (yamlContent: string) =>
      apiFetch<ScenarioCreated>(`${BASE}/from-yaml/`, { method: "POST", body: { yaml_content: yamlContent } }),
    onSuccess: () => invalidateScenarios(queryClient),
  });
}

export function useUpdateScenario(scenarioId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ScenarioUpdate) =>
      apiFetch<ScenarioDetail>(`${BASE}/${scenarioId}/`, { method: "PATCH", body }),
    onSuccess: () => invalidateScenarios(queryClient, scenarioId),
  });
}

export function useDeleteScenario() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (scenarioId: string) => apiFetch<void>(`${BASE}/${scenarioId}/`, { method: "DELETE" }),
    onSuccess: (_data, scenarioId) => invalidateScenarios(queryClient, scenarioId),
  });
}

export function useCloneScenario(sourceScenarioId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ScenarioClone) =>
      apiFetch<ScenarioCreated>(`${BASE}/${sourceScenarioId}/clone/`, { method: "POST", body }),
    onSuccess: () => invalidateScenarios(queryClient),
  });
}

export function useUpdateScenarioMetadata(scenarioId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ScenarioMetadataUpdate) =>
      apiFetch<ScenarioMetadataState>(`${BASE}/${scenarioId}/metadata/`, { method: "PATCH", body }),
    onSuccess: () => invalidateScenarios(queryClient, scenarioId),
  });
}

export function useValidateYaml() {
  return useMutation({
    mutationFn: (yamlContent: string) =>
      apiFetch<ScenarioYamlValidation>("/cms/scenario-editor/validate-yaml/", {
        method: "POST",
        body: { yaml_content: yamlContent },
      }),
  });
}

/** Fetch a scenario's YAML rendering (used for the imperative download action). */
export function fetchScenarioExport(scenarioId: string): Promise<ScenarioExport> {
  return apiFetch<ScenarioExport>(`${BASE}/${scenarioId}/export/`);
}
