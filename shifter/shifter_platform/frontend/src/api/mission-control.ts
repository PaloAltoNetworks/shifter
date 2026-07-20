/**
 * TanStack Query hooks for the Mission Control API surface (#1370). All
 * caching, invalidation, and retry policy live here; components call these
 * hooks and never fetch directly (mirrors `./risks.ts`).
 *
 * Request bodies below are hand-typed against the DRF serializers in
 * `mission_control/api/serializers.py`: those views validate a request body
 * but are not annotated with `@extend_schema(request=...)`, so
 * openapi-typescript has no generated request shape to re-export (only the
 * response shapes are generated). Response types come from `./types`
 * (generated) as usual.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiDownload, apiFetch } from "./client";
import type {
  AgentListResponse,
  CredentialCreateResponse,
  CurrentRangeResponse,
  GuacamoleBootstrapQueued,
  LaunchRangeResponse,
  NGFWCreateResponse,
  NGFWDestroyResponse,
  NGFWListResponse,
  RangeHistoryResponse,
  RangeLeaseResponse,
  RangeStatus,
  ScenarioListResponse,
  SuccessResponse,
  UploadCompleteResponse,
  UploadInitiateResponse,
} from "./types";

const MC_NS = "mission-control";

export const missionControlKeys = {
  all: [MC_NS] as const,
  currentRange: [MC_NS, "range", "current"] as const,
  history: [MC_NS, "range", "history"] as const,
  agents: [MC_NS, "agents"] as const,
  scenarios: [MC_NS, "scenarios"] as const,
  ngfwList: [MC_NS, "ngfw", "list"] as const,
};

function invalidateRange(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: missionControlKeys.currentRange });
  queryClient.invalidateQueries({ queryKey: missionControlKeys.history });
}

// Statuses that mean "the backend is still working on this" (cyberscript
// ResourceStatus, see `shared.enums.ResourceStatus` / ResourceStatusEnum). Polling
// stops once the range lands in a stable state (ready/paused) or a terminal
// one (destroyed/failed) — the ADR-025-R4 fallback until the websocket
// upgrade (a later chunk) replaces it.
const TRANSIENT_RANGE_STATUSES: ReadonlySet<RangeStatus> = new Set([
  "pending",
  "provisioning",
  "pausing",
  "resuming",
  "destroying",
]);

const RANGE_POLL_INTERVAL_MS = 4000;

export function useCurrentRange() {
  return useQuery({
    queryKey: missionControlKeys.currentRange,
    queryFn: ({ signal }) => apiFetch<CurrentRangeResponse>("/mission-control/range/", { signal }),
    refetchInterval: (query) => {
      const status = query.state.data?.range?.status;
      return status && TRANSIENT_RANGE_STATUSES.has(status) ? RANGE_POLL_INTERVAL_MS : false;
    },
  });
}

export function useRangeHistory() {
  return useQuery({
    queryKey: missionControlKeys.history,
    queryFn: ({ signal }) => apiFetch<RangeHistoryResponse>("/mission-control/ranges/", { signal }),
  });
}

export function useAgents() {
  return useQuery({
    queryKey: missionControlKeys.agents,
    queryFn: ({ signal }) => apiFetch<AgentListResponse>("/mission-control/agents/", { signal }),
  });
}

export function useScenarios() {
  return useQuery({
    queryKey: missionControlKeys.scenarios,
    queryFn: ({ signal }) => apiFetch<ScenarioListResponse>("/mission-control/scenarios/", { signal }),
  });
}

export function useNgfwList() {
  return useQuery({
    queryKey: missionControlKeys.ngfwList,
    queryFn: ({ signal }) => apiFetch<NGFWListResponse>("/mission-control/ngfw/list/", { signal }),
  });
}

/** Body for `POST /mission-control/range/launch/` (`LaunchRangeSerializer`). */
export interface LaunchRangeRequest {
  scenario?: string;
  agent_id?: number;
  agents?: Record<string, number>;
}

export function useLaunchRange() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: LaunchRangeRequest) =>
      apiFetch<LaunchRangeResponse>("/mission-control/range/launch/", { method: "POST", body }),
    onSuccess: () => invalidateRange(queryClient),
  });
}

/**
 * Body for the range lifecycle mutations (`RangeLifecycleSerializer`). The
 * serializer also accepts a legacy `range_id`, but the SPA always has the
 * durable `request_id` UUID correlation key from `RangePresentation` and uses
 * that exclusively.
 */
export interface RangeLifecycleRequest {
  request_id: string;
}

function useRangeLifecycleMutation(path: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: RangeLifecycleRequest) => apiFetch<SuccessResponse>(path, { method: "POST", body }),
    onSuccess: () => invalidateRange(queryClient),
  });
}

export function useCancelRange() {
  return useRangeLifecycleMutation("/mission-control/range/cancel/");
}

export function useDestroyRange() {
  return useRangeLifecycleMutation("/mission-control/range/destroy/");
}

export function usePauseRange() {
  return useRangeLifecycleMutation("/mission-control/range/pause/");
}

export function useResumeRange() {
  return useRangeLifecycleMutation("/mission-control/range/resume/");
}

export function useExtendRange() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<RangeLeaseResponse>("/mission-control/range/extend/", {
        method: "POST",
      }),
    onSuccess: () => invalidateRange(queryClient),
  });
}

const VPN_PROFILE_MEDIA_TYPE = "application/x-openvpn-profile";
const VPN_PROFILE_FILENAME = "shifter-range.ovpn";

export function useDownloadRangeVpnProfile() {
  return useMutation({
    mutationFn: async () => {
      const blob = await apiDownload("/mission-control/range/vpn-profile/", {
        method: "POST",
        expectedMediaType: VPN_PROFILE_MEDIA_TYPE,
        maxBytes: 64 * 1024,
      });
      const url = URL.createObjectURL(blob);
      try {
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = VPN_PROFILE_FILENAME;
        anchor.click();
      } finally {
        URL.revokeObjectURL(url);
      }
    },
  });
}

/** Body for `POST /mission-control/ngfw/` (`NGFWCreateSerializer`). */
export interface NgfwCreateRequest {
  name?: string;
  deployment_profile_id?: number | null;
  registration_method?: string;
  scm_credential_id?: number | null;
  otp_value?: string | null;
  otp_folder?: string | null;
}

export function useCreateNgfw() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: NgfwCreateRequest) =>
      apiFetch<NGFWCreateResponse>("/mission-control/ngfw/", { method: "POST", body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: missionControlKeys.ngfwList }),
  });
}

export function useDestroyNgfw() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ appId, confirmName }: { appId: string; confirmName?: string }) =>
      apiFetch<NGFWDestroyResponse>(`/mission-control/ngfw/${appId}/destroy/`, {
        method: "POST",
        body: { confirm_name: confirmName ?? "" },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: missionControlKeys.ngfwList }),
  });
}

export function useNgfwSshUrl() {
  return useMutation({
    mutationFn: (appId: string) =>
      apiFetch<GuacamoleBootstrapQueued>(`/mission-control/ngfw/${appId}/ssh-url/`, { method: "POST" }),
  });
}

/** Body for `POST /mission-control/credentials/` (`CredentialCreateSerializer`). */
export interface CredentialCreateRequest {
  credential_type: "scm" | "deployment_profile";
  name?: string;
  expires_at?: string | null;
  scm_folder_name?: string;
  scm_pin_id?: string;
  scm_pin_value?: string;
  sls_region?: string;
  authcode?: string;
}

export function useCreateCredential() {
  return useMutation({
    mutationFn: (body: CredentialCreateRequest) =>
      apiFetch<CredentialCreateResponse>("/mission-control/credentials/", { method: "POST", body }),
  });
}

export function useDeleteCredential() {
  return useMutation({
    mutationFn: (credentialId: number) =>
      apiFetch<SuccessResponse>(`/mission-control/credentials/${credentialId}/delete/`, { method: "POST" }),
  });
}

/** Body for `POST /mission-control/upload/initiate/` (`UploadInitiateSerializer`). */
export interface UploadInitiateRequest {
  name: string;
  filename: string;
  file_size: number;
  agent_type?: "xdr" | "xdr_collector" | "cloud_identity_engine";
}

export function useInitiateUpload() {
  return useMutation({
    mutationFn: (body: UploadInitiateRequest) =>
      apiFetch<UploadInitiateResponse>("/mission-control/upload/initiate/", { method: "POST", body }),
  });
}

/** Body for `POST /mission-control/upload/complete/` (`UploadCompleteSerializer`). */
export interface UploadCompleteRequest {
  upload_token: string;
}

export function useCompleteUpload() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: UploadCompleteRequest) =>
      apiFetch<UploadCompleteResponse>("/mission-control/upload/complete/", { method: "POST", body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: missionControlKeys.agents }),
  });
}

/** Body for `POST /mission-control/upload/cancel/` (`UploadCancelSerializer`). */
export interface UploadCancelRequest {
  upload_token: string;
}

export function useCancelUpload() {
  return useMutation({
    mutationFn: (body: UploadCancelRequest) =>
      apiFetch<SuccessResponse>("/mission-control/upload/cancel/", { method: "POST", body }),
  });
}

export type GuacamoleProtocol = "rdp" | "ssh";

/**
 * Queue a Guacamole RDP/SSH bootstrap for a range instance. Returns the
 * queued-request envelope (`request_id` + `status_url`); polling that status
 * endpoint and opening the one-time signed URL is a later chunk's concern —
 * this hook only owns the initial request.
 */
export function useRequestGuacamoleUrl() {
  return useMutation({
    mutationFn: ({ protocol, instanceUuid }: { protocol: GuacamoleProtocol; instanceUuid: string }) =>
      apiFetch<GuacamoleBootstrapQueued>(`/mission-control/guacamole/${protocol}-url/`, {
        method: "POST",
        body: { instance_uuid: instanceUuid },
      }),
  });
}
