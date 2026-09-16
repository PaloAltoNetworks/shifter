import { createBrowserRouter, Navigate } from "react-router";

import { RootLayout, type RouteHandle } from "@/app/RootLayout";
import { NotFoundPage } from "@/components/not-found";
import { RaesImageRegistryPage } from "@/features/raes-image-registry/RaesImageRegistryPage";
import { AuditPage } from "@/features/administer/AuditPage";
import { CostPage } from "@/features/administer/CostPage";
import { PlatformSettingsPage } from "@/features/administer/PlatformSettingsPage";
import { platformSettingsPath } from "@/features/administer/routes";
import { UserDetailPage } from "@/features/administer/UserDetailPage";
import { UsersListPage } from "@/features/administer/UsersListPage";
import { ConsoleSlotPage } from "@/features/administer/organization/ConsoleSlotPage";
import { OrganizationConsoleLayout } from "@/features/administer/organization/OrganizationConsoleLayout";
import { OrganizationOverviewPage } from "@/features/administer/organization/OrganizationOverviewPage";
import {
  OrganizationSettingsDetailPage,
  OrganizationSettingsPage,
} from "@/features/administer/organization/OrganizationSettingsPage";
import { WorkspaceDetailPage } from "@/features/administer/organization/WorkspaceDetailPage";
import { WorkspaceListPage } from "@/features/administer/organization/WorkspaceListPage";
import { WorkspaceMembershipPage } from "@/features/administer/organization/WorkspaceMembershipPage";
import { WorkspaceInvitationsPage } from "@/features/administer/organization/WorkspaceInvitationsPage";
import { WorkspaceRangeScopingPage } from "@/features/administer/organization/WorkspaceRangeScopingPage";
import { WorkspaceQuotaPage } from "@/features/administer/organization/WorkspaceQuotaPage";
import { WorkspaceScopeLayout } from "@/features/administer/organization/WorkspaceScopeLayout";
import {
  WORKSPACE_SURFACES,
  type WorkspaceSurface,
} from "@/features/administer/organization/surfaces";
import { ChallengeDetailPage } from "@/features/ctf/ChallengeDetailPage";
import { ChallengesPage } from "@/features/ctf/ChallengesPage";
import { AdminDashboardPage } from "@/features/ctf/admin/AdminDashboardPage";
import { ChallengeAdminDetailPage } from "@/features/ctf/admin/ChallengeAdminDetailPage";
import { ChallengeFormPage } from "@/features/ctf/admin/ChallengeFormPage";
import { ChallengesAdminPage } from "@/features/ctf/admin/ChallengesAdminPage";
import { EventDetailPage } from "@/features/ctf/admin/EventDetailPage";
import { EventFormPage } from "@/features/ctf/admin/EventFormPage";
import { EventsListPage } from "@/features/ctf/admin/EventsListPage";
import { MonitoringPage } from "@/features/ctf/admin/MonitoringPage";
import { ParticipantDetailPage } from "@/features/ctf/admin/ParticipantDetailPage";
import { ParticipantsPage } from "@/features/ctf/admin/ParticipantsPage";
import { BriefingPage } from "@/features/ctf/BriefingPage";
import { EventHomePage } from "@/features/ctf/EventHomePage";
import { HelpPage } from "@/features/ctf/HelpPage";
import { RangePage } from "@/features/ctf/RangePage";
import { ScoreboardPage } from "@/features/ctf/ScoreboardPage";
import { AccountPage } from "@/features/ctf/AccountPage";
import { CtfWorkspaceLayout } from "@/features/ctf/CtfWorkspaceLayout";
import { CtfTerminalPage } from "@/features/ctf/CtfTerminalPage";
import { TeamPage } from "@/features/ctf/TeamPage";
import { HomePage } from "@/features/home/HomePage";
import { AgentsPage } from "@/features/mission-control/AgentsPage";
import { CredentialsPage } from "@/features/mission-control/CredentialsPage";
import { NgfwDetailPage } from "@/features/mission-control/NgfwDetailPage";
import { NgfwListPage } from "@/features/mission-control/NgfwListPage";
import { NgfwWizardPage } from "@/features/mission-control/NgfwWizardPage";

function workspaceSurfaceElement(surface: WorkspaceSurface) {
  if (surface.key === "membership") return <WorkspaceMembershipPage />;
  if (surface.key === "invitations") return <WorkspaceInvitationsPage />;
  if (surface.key === "range-scoping") return <WorkspaceRangeScopingPage />;
  if (surface.key === "quota") return <WorkspaceQuotaPage />;
  return <ConsoleSlotPage title={surface.label} />;
}
import { RangeDashboardPage } from "@/features/mission-control/RangeDashboardPage";
import { RangeDetailPage } from "@/features/mission-control/RangeDetailPage";
import { RangeHistoryPage } from "@/features/mission-control/RangeHistoryPage";
import { RangeLaunchPage } from "@/features/mission-control/RangeLaunchPage";
import { TerminalPage } from "@/features/mission-control/TerminalPage";
import { TerminalWorkspacePage } from "@/features/mission-control/TerminalWorkspacePage";
import { ScenarioDetailPage } from "@/features/scenario-editor/ScenarioDetailPage";
import { ScenarioListPage } from "@/features/scenario-editor/ScenarioListPage";

// One platform router at the site root (#1369). The Django host serves the
// shell for the SPA-owned page paths, so deep links and refresh resolve to this
// client router.
// Mission Control (#1370) is gated the same way the "Operate" nav group is:
// any authenticated principal, same as its legacy Django views.
const missionControlHandle: RouteHandle = { permissionPolicy: "authenticated" };
// Scenario Editor (#1371) is gated on CMS-authoring access, the same advisory
// policy the existing "Author" nav group / legacy threat-research views use.
const scenarioEditorHandle: RouteHandle = { permissionPolicy: "threat_research" };
// RAES image registry (#1566) shares the "Author" CMS-authoring gate.
const raesImageRegistryHandle: RouteHandle = { permissionPolicy: "threat_research" };
// Administer workspace (#1373) is gated on staff, the same advisory policy the
// "Administer" nav group and the /api/v1/administer/ endpoints enforce.
const administerHandle: RouteHandle = { permissionPolicy: "staff" };
// CTF participant workspace (#1372) is gated on CTF-participant access, the same
// advisory policy the legacy participant Django views use.
const ctfHandle: RouteHandle = { permissionPolicy: "ctf_participant" };
// CTF organizer workspace (#1372) is gated on CTF-organizer access, the same
// advisory policy the legacy organizer (/ctf/admin/) Django views use. Declared
// as its own `ctf/admin` route group (a sibling of the participant `ctf` group)
// so the more-specific admin paths carry the organizer gate while participant
// paths keep the participant gate.
const ctfOrganizerHandle: RouteHandle = { permissionPolicy: "ctf_organizer" };

export const router = createBrowserRouter(
  [
    {
      path: "/",
      element: <RootLayout />,
      children: [
        { index: true, element: <HomePage /> },
        {
          // The F1 foundation chunk registered only the dashboard; the
          // live-access chunk added the per-instance terminal page; the
          // range-pages chunk added the range-history list, the launch form,
          // and the per-range detail page; this chunk adds the asset pages
          // (agents, NGFW, credentials — see features/mission-control/routes.ts
          // for the matching path builders). "ngfw/setup" is listed before the
          // "ngfw/:appId" dynamic route for readability; React Router ranks
          // static segments over dynamic ones regardless of declaration order,
          // so this ordering is not load-bearing.
          path: "mission-control",
          handle: missionControlHandle,
          children: [
            { index: true, element: <RangeDashboardPage /> },
            { path: "ranges", element: <RangeHistoryPage /> },
            { path: "launch", element: <RangeLaunchPage /> },
            { path: "ranges/:requestId", element: <RangeDetailPage /> },
            // The workspace owns both: `terminal/` is the nav destination and
            // the legacy multi-device console's path, and `terminal/:instanceUuid`
            // is a deep link that preselects one of its devices (#1661).
            { path: "terminal", element: <TerminalWorkspacePage /> },
            { path: "terminal/:instanceUuid", element: <TerminalWorkspacePage /> },
            { path: "agents", element: <AgentsPage /> },
            { path: "ngfw", element: <NgfwListPage /> },
            { path: "ngfw/setup", element: <NgfwWizardPage /> },
            { path: "ngfw/:appId", element: <NgfwDetailPage /> },
            { path: "credentials", element: <CredentialsPage /> },
            // Preserve the stable Django route/bookmark while keeping Platform
            // Settings owned and staff-gated by the Administer workspace.
            { path: "settings", element: <Navigate to={platformSettingsPath()} replace /> },
          ],
        },
        {
          // Scenario Editor (#1371) rehomed under the unified client router.
          // The workspace is a read-only catalog over registered RAES packs;
          // pack ingestion remains an authenticated API/operator workflow.
          path: "scenario-editor",
          handle: scenarioEditorHandle,
          children: [
            { index: true, element: <ScenarioListPage /> },
            { path: ":scenarioId", element: <ScenarioDetailPage /> },
          ],
        },
        {
          // CTF participant workspace (#1372) rehomed under the unified client
          // router. Its legacy Django counterpart lives at the same /ctf/
          // participant page paths (see features/ctf/routes.ts); the static
          // "challenges" segment outranks the ":id" dynamic route regardless of
          // declaration order. Organizer (/ctf/admin/) pages are not part of this
          // slice and stay Django-served.
          path: "ctf",
          handle: ctfHandle,
          element: <CtfWorkspaceLayout />,
          children: [
            { index: true, element: <EventHomePage /> },
            { path: "event", element: <EventHomePage /> },
            { path: "challenges", element: <ChallengesPage /> },
            { path: "challenges/:id", element: <ChallengeDetailPage /> },
            { path: "range", element: <RangePage /> },
            { path: "terminal", element: <CtfTerminalPage /> },
            { path: "terminal/:instanceUuid", element: <TerminalPage /> },
            { path: "scoreboard", element: <ScoreboardPage /> },
            { path: "team", element: <TeamPage /> },
            { path: "account", element: <AccountPage /> },
            { path: "help", element: <HelpPage /> },
            { path: "briefing", element: <BriefingPage /> },
          ],
        },
        {
          // CTF organizer workspace (#1372). A sibling `ctf/admin` group (not a
          // child of the `ctf` participant group) so its more-specific paths win
          // and carry the organizer permission gate. The legacy Django organizer
          // pages live at the same /ctf/admin/ paths (see features/ctf/routes.ts).
          // Create/edit client routes intentionally match the legacy Django form
          // URLs: those exact server routes stay Django-served for rollback, so a
          // deep-link GET lands on the classic form while in-SPA navigation
          // renders the client form here. Every wrapped organizer GET page path
          // resolves to a page below so a refresh never dead-ends at Not Found.
          path: "ctf/admin",
          handle: ctfOrganizerHandle,
          children: [
            { index: true, element: <AdminDashboardPage /> },
            { path: "events", element: <EventsListPage /> },
            { path: "events/create", element: <EventFormPage mode="create" /> },
            { path: "events/:eventId", element: <EventDetailPage /> },
            { path: "events/:eventId/edit", element: <EventFormPage mode="edit" /> },
            { path: "events/:eventId/challenges", element: <ChallengesAdminPage /> },
            { path: "events/:eventId/challenges/create", element: <ChallengeFormPage mode="create" /> },
            { path: "challenges/:challengeId", element: <ChallengeAdminDetailPage /> },
            { path: "challenges/:challengeId/edit", element: <ChallengeFormPage mode="edit" /> },
            { path: "events/:eventId/participants", element: <ParticipantsPage /> },
            { path: "events/:eventId/teams", element: <ParticipantsPage /> },
            { path: "participants/:participantId", element: <ParticipantDetailPage /> },
            { path: "events/:eventId/scoreboard", element: <MonitoringPage defaultTab="scoreboard" /> },
            { path: "events/:eventId/monitoring", element: <MonitoringPage defaultTab="scoreboard" /> },
            { path: "events/:eventId/ranges", element: <MonitoringPage defaultTab="ranges" /> },
            { path: "events/:eventId/notifications", element: <MonitoringPage defaultTab="notifications" /> },
            { path: "events/:eventId/analytics", element: <MonitoringPage defaultTab="analytics" /> },
            { path: "events/:eventId/brackets", element: <MonitoringPage defaultTab="scoreboard" /> },
            { path: "events/:eventId/email-templates", element: <MonitoringPage defaultTab="notifications" /> },
          ],
        },
        {
          // RAES image registry (#1566): greenfield SPA-only surface. The Django
          // host serves the shell for /raes-image-registry/* GET paths.
          path: "raes-image-registry",
          handle: raesImageRegistryHandle,
          children: [{ index: true, element: <RaesImageRegistryPage /> }],
        },
        {
          // Administer workspace (#1373): greenfield SPA surface. The Django host
          // serves the shell for /administer/* GET paths; Django admin stays at
          // /admin/ and is never captured here. Users is the index;
          // static segments (cost, settings) outrank the users/:id dynamic route.
          path: "administer",
          handle: administerHandle,
          children: [
            { index: true, element: <UsersListPage /> },
            { path: "users/:id", element: <UserDetailPage /> },
            { path: "cost", element: <CostPage /> },
            { path: "settings", element: <PlatformSettingsPage /> },
            // Administrator audit / activity history (#1947, PLAT-240): a
            // deployment-global, staff-only surface. Top-level (not workspace
            // scoped) because the audit store carries no per-row tenant scope.
            { path: "audit", element: <AuditPage /> },
            {
              // Organization/workspace admin console (#1938, PLAT-231). The shell
              // owns routing, the switcher, context, and capability-aware nav; the
              // child surface slots (org settings, workspaces, membership, and
              // invitations are implemented; later scoped surfaces remain
              // placeholders owned by PLAT-236–239). The
              // selected workspace is the public-UUID route param; the host
              // catch-all already serves /administer/* so deep links resolve.
              path: "organization",
              element: <OrganizationConsoleLayout />,
              children: [
                { index: true, element: <OrganizationOverviewPage /> },
                { path: "settings", element: <OrganizationSettingsPage /> },
                { path: "settings/:organizationUuid", element: <OrganizationSettingsDetailPage /> },
                { path: "workspaces", element: <WorkspaceListPage /> },
                {
                  path: "workspaces/:workspaceUuid",
                  element: <WorkspaceScopeLayout />,
                  children: [
                    { index: true, element: <WorkspaceDetailPage /> },
                    // Membership (#1941) and invitations (#1942) are real surfaces;
                    // later scoped slots stay placeholders until PLAT-236–239 land.
                    ...WORKSPACE_SURFACES.map((surface) => ({
                      path: surface.key,
                      element: workspaceSurfaceElement(surface),
                    })),
                  ],
                },
              ],
            },
          ],
        },
        { path: "*", element: <NotFoundPage /> },
      ],
    },
  ],
  { basename: "/" },
);
