/** Shared types re-exported from the generated OpenAPI schema. */
import type { components } from "./schema";

export type AuditLog = components["schemas"]["AuditLog"];
export type PaginatedAuditLogList = components["schemas"]["PaginatedAuditLogList"];
export type Bootstrap = components["schemas"]["Bootstrap"];
export type BootstrapModes = components["schemas"]["BootstrapModes"];
export type BootstrapPermissions = components["schemas"]["BootstrapPermissions"];
export type UxMode = BootstrapModes["default"];
export type DashboardSummary = components["schemas"]["DashboardSummary"];

/**
 * Administer workspace domain types (#1373), re-exported from the generated
 * OpenAPI schema. The `management.services` domain seam and the DRF serializers
 * remain the authoritative validator; do not hand-copy these shapes — regenerate
 * `schema.d.ts` via `npm run gen:api` instead.
 */
export type AdminUserListItem = components["schemas"]["AdminUserListItem"];
export type AdminUserDetail = components["schemas"]["AdminUserDetail"];
export type PaginatedAdminUserListItemList = components["schemas"]["PaginatedAdminUserListItemList"];
export type OrganizerGrantResult = components["schemas"]["OrganizerGrantResult"];

/**
 * User lifecycle administration types (#1943, PLAT-236). The `management`
 * transition service + composition-root transfer command and their DRF
 * serializers are authoritative; regenerate `schema.d.ts` via `npm run gen:api`
 * rather than hand-copying. `lifecycle_state` and `available_actions` on
 * `AdminUserDetail` are server-derived; the SPA never reconstructs transition or
 * reset-eligibility policy from them.
 */
export type AccountLifecycleAction = components["schemas"]["LifecycleTransitionRequestActionEnum"];
export type LifecycleTransitionRequest = components["schemas"]["LifecycleTransitionRequest"];
export type TransferOwnershipRequest = components["schemas"]["TransferOwnershipRequest"];
export type TransferOwnershipResult = components["schemas"]["TransferOwnershipResult"];
export type TransferOwnershipResourceKind = components["schemas"]["TransferOwnershipRequest"]["resource_kinds"][number];

/** Runtime Mission Control lease-policy administration contracts (#2169). */
export type MissionControlLeasePolicy = components["schemas"]["LeasePolicy"];
export type MissionControlLeasePolicyOverride = components["schemas"]["LeasePolicyOverride"];
export type MissionControlLeasePolicyGroup = components["schemas"]["LeasePolicyGroupSettings"];
export type MissionControlLeasePolicySettings = components["schemas"]["MissionControlLeasePolicySettings"];
export type ReplaceMissionControlLeasePolicyRequest = components["schemas"]["ReplaceLeasePolicy"];
export type ResetMissionControlLeasePolicyRequest = components["schemas"]["ResetLeasePolicy"];

/**
 * Organization/workspace admin console types (#1938, PLAT-231), re-exported from
 * the generated OpenAPI schema. The `workspaces.services` projection + DRF
 * serializer are authoritative; regenerate `schema.d.ts` via `npm run gen:api`
 * rather than hand-copying. `role`/`capabilities` are advisory display data — the
 * `/api/v1/workspaces/` endpoints reauthorize every operation.
 */
export type PrincipalWorkspaceContext = components["schemas"]["PrincipalWorkspaceContext"];
export type PaginatedPrincipalWorkspaceContextList =
  components["schemas"]["PaginatedPrincipalWorkspaceContextList"];
export type OrganizationRef = components["schemas"]["OrganizationRef"];
export type WorkspaceRole = components["schemas"]["WorkspaceRoleEnum"];

/**
 * Organization profile & settings types (#1939, PLAT-232), re-exported from the
 * generated OpenAPI schema. The `workspaces.services` seam + DRF serializers are
 * authoritative (ADR-048); regenerate `schema.d.ts` rather than hand-copying.
 */
export type OrganizationProfile = components["schemas"]["OrganizationProfile"];
export type OrganizationProfileUpdate = components["schemas"]["PatchedOrganizationProfileUpdate"];
export type PaginatedOrganizationProfileList = components["schemas"]["PaginatedOrganizationProfileList"];

/**
 * Workspace lifecycle types (#1940, PLAT-233), re-exported from the generated
 * OpenAPI schema. The `workspaces.services` lifecycle seam + DRF serializers are
 * authoritative; regenerate `schema.d.ts` via `npm run gen:api` rather than
 * hand-copying. Workspaces are addressed by their public UUID only.
 */
export type Workspace = components["schemas"]["Workspace"];
export type CreateWorkspaceRequest = components["schemas"]["CreateWorkspace"];
export type TransferWorkspaceOwnershipRequest = components["schemas"]["TransferWorkspaceOwnership"];
// Workspace network egress policy (#1945, PLAT-238). The workspace-selectable
// subset of the canonical RangeEgressMode vocabulary; the server re-validates and
// authorizes every change.
export type WorkspaceEgressPolicy = components["schemas"]["EgressPolicyEnum"];
export type SetWorkspaceEgressPolicyRequest = components["schemas"]["SetWorkspaceEgressPolicy"];
// Workspace resource quotas & usage (#1946, PLAT-239). Read-only projection of
// usage against configured limits plus recent quota decisions; policy authoring
// is a superuser-only Django-admin escape hatch, never a SPA surface.
export type WorkspaceQuota = components["schemas"]["WorkspaceQuota"];
export type WorkspaceQuotaResource = components["schemas"]["WorkspaceQuotaResource"];
export type WorkspaceQuotaDecision = components["schemas"]["WorkspaceQuotaDecision"];

/**
 * Workspace membership & roles types (#1941, PLAT-234), re-exported from the
 * generated OpenAPI schema. The `workspaces.services` membership seam + DRF
 * serializers are authoritative; regenerate `schema.d.ts` via `npm run gen:api`
 * rather than hand-copying. A member is addressed by the server-provided
 * `user_id` the roster projection exposes; the closed `WorkspaceRole` vocabulary
 * is rendered as data/request values only and never used to reconstruct policy.
 */
export type WorkspaceMembership = components["schemas"]["WorkspaceMembership"];
export type AddWorkspaceMemberRequest = components["schemas"]["AddWorkspaceMember"];
export type ChangeWorkspaceMemberRoleRequest = components["schemas"]["ChangeWorkspaceMemberRole"];

/** Signed workspace invitation administration contracts (#1942, PLAT-235). */
export type WorkspaceInvitation = components["schemas"]["WorkspaceInvitation"];
export type IssueWorkspaceInvitationRequest = components["schemas"]["IssueWorkspaceInvitation"];

/**
 * Range-to-workspace scope administration types (#1944, PLAT-237), re-exported
 * from the generated OpenAPI schema. The `cms.services` scope-admin seam + DRF
 * serializers are authoritative; regenerate `schema.d.ts` via `npm run gen:api`
 * rather than hand-copying. Ranges are addressed by their public request UUID and
 * workspaces by their public UUID; `is_reassignable` is a server-derived
 * affordance and the endpoints reauthorize every call.
 */
export type RangeScopeBinding = components["schemas"]["RangeScopeBinding"];
export type PaginatedRangeScopeBindingList = components["schemas"]["PaginatedRangeScopeBindingList"];
export type RangeWorkspaceRebindRequest = components["schemas"]["RangeWorkspaceRebindRequest"];
export type RangeWorkspaceRebindResult = components["schemas"]["RangeWorkspaceRebindResult"];

/**
 * Mission Control domain types (#1370), re-exported from the generated OpenAPI
 * schema. Only the shapes this foundation chunk (and the pages/live-access
 * chunks that follow it) need are re-exported here; do not hand-copy field
 * shapes — regenerate `schema.d.ts` instead.
 */
export type RangeStatus = components["schemas"]["ResourceStatusEnum"];
export type RangePresentation = components["schemas"]["RangePresentation"];
export type InstancePresentation = components["schemas"]["InstancePresentation"];
export type CurrentRangeResponse = components["schemas"]["CurrentRangeResponse"];
export type RangeLease = components["schemas"]["RangeLease"];
export type RangeLeaseResponse = components["schemas"]["RangeLeaseResponse"];
export type LaunchRangeResponse = components["schemas"]["LaunchRangeResponse"];
export type SuccessResponse = components["schemas"]["SuccessResponse"];
export type AgentListResponse = components["schemas"]["AgentListResponse"];
export type AgentListItem = components["schemas"]["AgentListItem"];
export type ScenarioListResponse = components["schemas"]["ScenarioListResponse"];
export type ScenarioListItem = components["schemas"]["ScenarioListItem"];
export type RangeHistory = components["schemas"]["RangeHistory"];
export type RangeHistoryResponse = components["schemas"]["RangeHistoryResponse"];
export type GuacamoleBootstrapQueued = components["schemas"]["GuacamoleBootstrapQueued"];
export type GuacamoleBootstrapStatus = components["schemas"]["GuacamoleBootstrapStatus"];
export type NGFWListResponse = components["schemas"]["NGFWListResponse"];
export type NGFWListItem = components["schemas"]["NGFWListItem"];
export type NGFWCreateResponse = components["schemas"]["NGFWCreateResponse"];
export type NGFWDestroyResponse = components["schemas"]["NGFWDestroyResponse"];
export type CredentialCreateResponse = components["schemas"]["CredentialCreateResponse"];
export type UploadInitiateResponse = components["schemas"]["UploadInitiateResponse"];
export type UploadCompleteResponse = components["schemas"]["UploadCompleteResponse"];

/**
 * Read-only RAES catalog types, re-exported from the generated OpenAPI schema.
 * Do not hand-copy these shapes — regenerate `schema.d.ts` via
 * `npm run gen:api` instead.
 */
export type ScenarioCatalogEntry = components["schemas"]["CatalogEntry"];
export type ScenarioDetail = components["schemas"]["ScenarioDetail"];
export type ScenarioMetadataUpdate = components["schemas"]["PatchedScenarioMetadataUpdate"];
export type ScenarioMetadataState = components["schemas"]["ScenarioMetadataState"];
export type ScenarioRaesFields = components["schemas"]["RaesCatalogFields"];
export type ScenarioRealizability = components["schemas"]["ScenarioRealizability"];
export type ScenarioRealizabilityGap = components["schemas"]["RealizabilityGap"];

/** Scenario source classification the detail endpoint returns in `source`. */
export type ScenarioSource = "raes";

/**
 * RAES image registry types (#1566), re-exported from the generated OpenAPI
 * schema. The `engine.services` write path stays the authoritative validator;
 * regenerate `schema.d.ts` via `npm run gen:api` instead of hand-copying.
 */
export type RaesImageMapping = components["schemas"]["RaesImageMappingView"];
export type RaesImageMappingRegister = components["schemas"]["RaesImageMappingRegister"];
export type RaesImageMappingDisable = components["schemas"]["RaesImageMappingDisable"];

/** Provider choices mirroring engine.models.RaesImageMapping.Provider (UI affordance only). */
export type RaesImageProvider = "gce" | "aws";
export const RAES_IMAGE_PROVIDERS: ReadonlyArray<{ value: RaesImageProvider; label: string }> = [
  { value: "gce", label: "Google Compute Engine" },
  { value: "aws", label: "AWS EC2" },
];

/**
 * CTF participant workspace domain types (#1372), re-exported from the generated
 * OpenAPI schema. The participant-safe DRF projections (`ctf.api.projections` +
 * `ctf.api.serializers`) remain the authoritative shape; do not hand-copy these
 * — regenerate `schema.d.ts` via `npm run gen:api` instead. The participant
 * serializers deliberately never declare flag/solution/validator-config fields,
 * so those values cannot be expressed here.
 */
export type CtfCurrentEvent = components["schemas"]["ParticipantCurrentEvent"];
export type CtfParticipantSelf = components["schemas"]["ParticipantSelf"];
export type CtfEvent = components["schemas"]["ParticipantEvent"];
export type CtfChallengeListItem = components["schemas"]["ParticipantChallengeListItem"];
export type CtfChallengeDetail = components["schemas"]["ParticipantChallengeDetail"];
export type CtfHint = components["schemas"]["ParticipantHint"];
export type CtfChallengeFile = components["schemas"]["ParticipantChallengeFile"];
export type CtfTeam = components["schemas"]["ParticipantTeam"];
export type CtfTeamMember = components["schemas"]["ParticipantTeamMember"];
export type CtfSubmitFlagResult = components["schemas"]["SubmitFlagResult"];
export type CtfUseHintResult = components["schemas"]["UseHintResult"];
export type CtfRateChallengeResult = components["schemas"]["RateChallengeResult"];
export type CtfSubmissionList = components["schemas"]["SubmissionListResponse"];
export type CtfRangeStatus = components["schemas"]["RangeStatusResponse"];
export type CtfRangeAccess = components["schemas"]["RangeAccessResponse"];
export type CtfScoreboard = components["schemas"]["PublicScoreboardResponse"];

/**
 * CTF organizer workspace domain types (#1372), re-exported from the generated
 * OpenAPI schema. The organizer DRF serializers (`ctf.api.serializers` +
 * `ctf.api.organizer_views`) remain the authoritative shape; do not hand-copy
 * these — regenerate `schema.d.ts` via `npm run gen:api` instead.
 */
export type CtfEventSummary = components["schemas"]["EventSummary"];
export type CtfEventDetail = components["schemas"]["EventDetail"];
export type CtfEventWrite = components["schemas"]["EventWrite"];
export type CtfEventListResponse = components["schemas"]["EventListResponse"];
export type CtfEventMutationResult = components["schemas"]["EventMutationResult"];
export type CtfForceDeleteEventResult = components["schemas"]["ForceDeleteEventResult"];
export type CtfEventContentRefreshRequest = components["schemas"]["EventContentRefreshRequest"];
export type CtfEventContentRefreshResult = components["schemas"]["EventContentRefreshResult"];
export type CtfScenarioRef = components["schemas"]["CtfScenarioRef"];
export type CtfScenarioListResponse = components["schemas"]["CtfScenarioListResponse"];
export type CtfChallengeSummary = components["schemas"]["ChallengeSummary"];
export type CtfChallengeListResponse = components["schemas"]["ChallengeListResponse"];
export type CtfOrganizerChallengeDetail = components["schemas"]["OrganizerChallengeDetail"];
export type CtfChallengeWrite = components["schemas"]["ChallengeWrite"];
export type CtfChallengeMutationResult = components["schemas"]["ChallengeMutationResult"];
export type CtfChallengeHint = components["schemas"]["ChallengeHint"];
export type CtfHintWrite = components["schemas"]["HintWrite"];
export type CtfHintListResponse = components["schemas"]["HintListResponse"];
export type CtfFlagWrite = components["schemas"]["FlagWrite"];
export type CtfFlagCreateResult = components["schemas"]["FlagCreateResult"];
export type CtfChallengeFileMeta = components["schemas"]["ChallengeFileMeta"];
export type CtfChallengeFileListResponse = components["schemas"]["ChallengeFileListResponse"];
export type CtfChallengeFileUploadResult = components["schemas"]["ChallengeFileUploadResult"];
export type CtfPrerequisite = components["schemas"]["Prerequisite"];
export type CtfPrerequisiteWrite = components["schemas"]["PrerequisiteWrite"];
export type CtfPrerequisiteListResponse = components["schemas"]["PrerequisiteListResponse"];
export type CtfParticipantSummary = components["schemas"]["ParticipantSummary"];
export type CtfOrganizerParticipantDetail = components["schemas"]["ParticipantDetail"];
export type CtfAward = components["schemas"]["Award"];
export type CtfAwardListResponse = components["schemas"]["AwardListResponse"];
export type CtfParticipantListResponse = components["schemas"]["ParticipantListResponse"];
export type CtfParticipantAdd = components["schemas"]["ParticipantAdd"];
export type CtfParticipantImportResult = components["schemas"]["ParticipantImportResult"];
export type CtfParticipantPasswordRequest = components["schemas"]["ParticipantPasswordRequest"];
export type CtfParticipantPasswordResult = components["schemas"]["ParticipantPasswordResult"];
export type CtfPublicRegistrationRequest = components["schemas"]["PublicRegistrationRequest"];
export type CtfPublicRegistrationRequestListResponse =
  components["schemas"]["PublicRegistrationRequestListResponse"];
export type CtfPublicRegistrationDispositionAction =
  components["schemas"]["PublicRegistrationDispositionActionEnum"];
export type CtfPublicRegistrationDispositionResult =
  components["schemas"]["PublicRegistrationDispositionResult"];
export type CtfParticipantProfile = components["schemas"]["ParticipantProfile"];
export type CtfProfileUpdateRequest = components["schemas"]["PatchedProfileUpdateRequest"];
export type CtfEventStaffMember = components["schemas"]["EventStaffMember"];
export type CtfEventLifecycleAction =
  components["schemas"]["EventLifecycleRequest"]["action"];
export type CtfScheduledTask = components["schemas"]["ScheduledTask"];
export type CtfScheduledTaskListResponse = components["schemas"]["ScheduledTaskListResponse"];
export type CtfCleanupControlRequest = components["schemas"]["CleanupControlRequest"];
export type CtfEventStaffListResponse = components["schemas"]["EventStaffListResponse"];
export type CtfEventStaffAssignRequest = components["schemas"]["EventStaffAssignRequest"];
export type CtfAssignBracketRequest = components["schemas"]["AssignBracketRequest"];
export type CtfAssignBracketResult = components["schemas"]["AssignBracketResult"];
export type CtfNotificationListItem = components["schemas"]["NotificationListItem"];
export type CtfAnnouncement = components["schemas"]["ParticipantAnnouncement"];
export type CtfChallengeImportResult = components["schemas"]["ChallengeImportResult"];
export type CtfWebhook = components["schemas"]["Webhook"];
export type CtfWebhookListResponse = components["schemas"]["WebhookListResponse"];
export type CtfWebhookWrite = components["schemas"]["WebhookWrite"];
export type CtfEventPage = components["schemas"]["EventPage"];

/** Analytics dashboard payload (CTF-1302); the endpoint is schemaless JSON. */
export interface CtfEventAnalytics {
  event_id: string;
  score_distribution: Array<{ from: number; to: number; count: number }>;
  solve_timeline: Array<{ hour: string | null; solves: number }>;
  challenges: Array<{ name: string; points: number; solves: number; attempts: number; solve_rate: number }>;
  engagement: {
    registered: number;
    active: number;
    with_submissions: number;
    avg_challenges_attempted: number;
    hints_used: number;
  };
}
export type CtfEventPagesResponse = components["schemas"]["EventPagesResponse"];
export type CtfEventPageWrite = components["schemas"]["EventPageWrite"];
export type CtfAnnouncementListResponse = components["schemas"]["ParticipantAnnouncementList"];
export type CtfNotificationListResponse = components["schemas"]["NotificationListResponse"];
export type CtfNotificationAnnounceRequest = components["schemas"]["NotificationAnnounceRequest"];
export type CtfNotificationSendResult = components["schemas"]["NotificationSendResult"];
export type CtfRangeListItem = components["schemas"]["RangeListItem"];
export type CtfRangeListResponse = components["schemas"]["RangeListResponse"];
export type CtfRangeProvisionQueued = components["schemas"]["RangeProvisionQueued"];
export type CtfParticipantRangeActionResult = components["schemas"]["ParticipantRangeActionResult"];
export type CtfScoreTimelineResponse = components["schemas"]["ScoreTimelineResponse"];
export type CtfOrganizerScoreboard = components["schemas"]["OrganizerScoreboardResponse"];

/**
 * Runtime option lists for organizer forms/filters. Typed as plain strings (the
 * write serializers accept strings); the backend enums (`ctf.enums`) stay the
 * authoritative validator. These are UI affordances only.
 */
export const CTF_CHALLENGE_CATEGORIES: readonly string[] = [
  "web",
  "forensics",
  "crypto",
  "reverse",
  "pwn",
  "misc",
  "osint",
  "hardware",
  "network",
];
export const CTF_CHALLENGE_DIFFICULTIES: readonly string[] = ["easy", "medium", "hard", "expert"];
export const CTF_EVENT_STATUSES: readonly string[] = [
  "draft",
  "registration",
  "active",
  "paused",
  "ended",
  "cancelled",
  "archived",
];
