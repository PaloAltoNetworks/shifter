/**
 * Shared, role-aware platform navigation contract (#1369, ADR-013).
 *
 * This is the single source of navigation truth the platform shell renders from:
 * primary side navigation, mode switching, breadcrumbs, and contextual subnav
 * all derive from these entries. Adding a surface adds one entry here rather
 * than editing shell components (the navigation extensibility seam). The
 * per-surface issues (#1370–#1374) register their entries into this contract.
 *
 * Each entry carries the UX-003 minimum contract (`surface`, `audience`,
 * `routeName`, `permissionPolicy`, `ownerApp`, `purpose`) plus the #1368
 * presentation fields (`mode`, `group`, `routePath`, `iconKey`, `activeContext`,
 * `featureFlag`, `children`). See `docs/design/ux-003-information-architecture-sitemap.md`.
 *
 * Navigation visibility is advisory UX only, never authorization: entries may be
 * hidden for clarity, but every endpoint stays the authority (ADR-013-R3/R4). A
 * surface not yet migrated to the SPA is an `external` entry that links to its
 * existing Django route via full-page navigation; it moves to an in-SPA route
 * when its module issue lands.
 *
 * Entries are declared as compact per-entry specs and expanded by `makeGroup`,
 * which folds each group's shared defaults (mode, group, owner app, audience,
 * permission policy) into every entry so the registry data stays DRY.
 */
import type { Bootstrap } from "@/api/types";

export type UxMode = "participant" | "operator";

export type NavAudience = "participant" | "organizer" | "both" | "system";

export type NavGroupName = "Participate" | "Operate" | "Author" | "Govern" | "Administer";

/**
 * Advisory permission policy keys. The shell maps each to bootstrap flags in
 * `isNavEntryVisible`; the backend endpoints remain the authority.
 */
export type PermissionPolicy =
  | "authenticated"
  | "risk_register_access"
  | "threat_research"
  | "ctf_organizer"
  | "ctf_participant"
  | "staff";

export type NavIconKey =
  | "home"
  | "layout-dashboard"
  | "flag"
  | "server"
  | "trophy"
  | "users"
  | "help-circle"
  | "boxes"
  | "bot"
  | "shield"
  | "key-round"
  | "terminal"
  | "settings"
  | "file-code"
  | "shield-alert"
  | "user-cog"
  | "circle-dollar-sign";

export interface NavEntry {
  /** Canonical surface name (UX-003 taxonomy). */
  readonly surface: string;
  /** UX-003 audience classification. */
  readonly audience: NavAudience;
  /** Stable route name (Django route name / durable id). */
  readonly routeName: string;
  /** Advisory permission policy key (not authorization). */
  readonly permissionPolicy: PermissionPolicy;
  /** Owning Django app. */
  readonly ownerApp: string;
  /** Short purpose statement. */
  readonly purpose: string;
  /** UX mode this entry belongs to. */
  readonly mode: UxMode;
  /** IA group placement. */
  readonly group: NavGroupName;
  /** SPA path (in-app) or absolute legacy URL (when `external`). */
  readonly routePath: string;
  /** lucide icon key rendered by the shell. */
  readonly iconKey: NavIconKey;
  /** Optional active range/event context this surface reads. */
  readonly activeContext?: "range" | "event";
  /** Optional rollout flag gating visibility. */
  readonly featureFlag?: keyof Bootstrap["feature_flags"];
  /** True when the entry links to a legacy Django route via full-page nav. */
  readonly external?: boolean;
  /** Optional nested/contextual entries. */
  readonly children?: readonly NavEntry[];
}

export interface NavGroup {
  readonly group: NavGroupName;
  readonly mode: UxMode;
  readonly entries: readonly NavEntry[];
}

/** Fully-resolved per-entry declaration (after group defaults are folded in). */
interface EntrySpec {
  surface: string;
  routeName: string;
  ownerApp: string;
  purpose: string;
  routePath: string;
  iconKey: NavIconKey;
  permissionPolicy: PermissionPolicy;
  audience: NavAudience;
  activeContext?: "range" | "event";
  featureFlag?: keyof Bootstrap["feature_flags"];
  external?: boolean;
  children?: EntrySpec[];
}

/** Per-entry input; group-level defaults supply the omitted fields. */
type EntrySpecInput = Partial<Omit<EntrySpec, "children">> & { children?: EntrySpecInput[] };

/** Defaults applied to every entry in a group (folded before per-entry fields). */
type GroupDefaults = Partial<EntrySpec>;

function toEntry(mode: UxMode, group: NavGroupName, spec: EntrySpec): NavEntry {
  const entry: NavEntry = {
    surface: spec.surface,
    audience: spec.audience,
    routeName: spec.routeName,
    permissionPolicy: spec.permissionPolicy,
    ownerApp: spec.ownerApp,
    purpose: spec.purpose,
    mode,
    group,
    routePath: spec.routePath,
    iconKey: spec.iconKey,
    ...(spec.activeContext ? { activeContext: spec.activeContext } : {}),
    ...(spec.featureFlag ? { featureFlag: spec.featureFlag } : {}),
    ...(spec.external ? { external: true } : {}),
    ...(spec.children ? { children: spec.children.map((child) => toEntry(mode, group, child)) } : {}),
  };
  return entry;
}

function makeGroup(
  group: NavGroupName,
  mode: UxMode,
  defaults: GroupDefaults,
  specs: EntrySpecInput[],
): NavGroup {
  const expand = (spec: EntrySpecInput): EntrySpec =>
    ({
      ...defaults,
      ...spec,
      children: spec.children?.map(expand),
    }) as EntrySpec;
  return { group, mode, entries: specs.map((spec) => toEntry(mode, group, expand(spec))) };
}

/**
 * The seeded platform IA (UX-003 sitemap + #1368). Durable, revisited surfaces
 * only; event/entity-scoped surfaces (participants, per-event challenges) render
 * as contextual subnav within their entity, not as top-level nav. Surfaces not
 * yet on the SPA link to their legacy Django route (`external`).
 */
export const NAV_GROUPS: readonly NavGroup[] = [
  makeGroup(
    "Participate",
    "participant",
    // In-SPA once CTF_WORKSPACE_SPA_ENABLED is on (#1372); every participant
    // entry is internal (client-routed to features/ctf) and feature-flag gated so
    // the entries stay hidden until the flag flips, matching the Scenario Editor
    // rollout pattern. The organizer "CTF Events" entry lives in the Operate group
    // and stays external until the organizer SPA slice lands.
    {
      audience: "participant",
      permissionPolicy: "ctf_participant",
      ownerApp: "ctf",
      external: false,
      featureFlag: "ctf_workspace_spa",
    },
    [
      { surface: "Event Home", routeName: "ctf:dashboard", purpose: "Event entry point with current participant state.", routePath: "/ctf/", iconKey: "home", activeContext: "event" },
      { surface: "Challenges", routeName: "ctf:challenges", purpose: "Browse available challenges and progression.", routePath: "/ctf/challenges/", iconKey: "flag" },
      { surface: "Range", routeName: "ctf:range", purpose: "Access range status and participant resources.", routePath: "/ctf/range/", iconKey: "server", activeContext: "range" },
      { surface: "Scoreboard", routeName: "ctf:scoreboard", purpose: "Compare event scoring and rank.", routePath: "/ctf/scoreboard/", iconKey: "trophy" },
      { surface: "Team", routeName: "ctf:team", purpose: "Inspect team membership and status.", routePath: "/ctf/team/", iconKey: "users" },
      { surface: "Help", routeName: "ctf:help", purpose: "Get CTF-specific help.", routePath: "/ctf/help/", iconKey: "help-circle" },
    ],
  ),
  makeGroup(
    "Operate",
    "operator",
    { audience: "organizer", permissionPolicy: "authenticated", ownerApp: "mission_control", external: true },
    [
      { surface: "Overview", routeName: "home", ownerApp: "config", purpose: "Role-aware operational dashboard.", routePath: "/", iconKey: "layout-dashboard", external: false },
      { surface: "Ranges", routeName: "mission_control:dashboard", purpose: "Launch and monitor ranges.", routePath: "/mission-control/", iconKey: "server", activeContext: "range", external: false },
      // In-SPA once CTF_WORKSPACE_SPA_ENABLED is on (#1372); the organizer
      // workspace is client-routed (features/ctf/admin) and feature-flag gated so
      // the entry stays hidden until the flag flips, matching the participant and
      // Scenario Editor rollout pattern.
      { surface: "CTF Events", routeName: "ctf:admin_dashboard", ownerApp: "ctf", permissionPolicy: "ctf_organizer", purpose: "Monitor and manage CTF operations.", routePath: "/ctf/admin/", iconKey: "flag", activeContext: "event", external: false, featureFlag: "ctf_workspace_spa" },
      {
        surface: "Assets",
        routeName: "mission_control:agents",
        purpose: "Operational resources: agents, NGFW, credentials.",
        routePath: "/mission-control/agents/",
        iconKey: "boxes",
        children: [
          { surface: "Agents", routeName: "mission_control:agents", purpose: "Inspect or delete available agents.", routePath: "/mission-control/agents/", iconKey: "bot", external: false },
          { surface: "NGFW", routeName: "mission_control:ngfw_list", purpose: "List NGFW instances.", routePath: "/mission-control/ngfw/", iconKey: "shield", external: false },
          { surface: "Credentials", routeName: "mission_control:credentials", purpose: "List reusable credentials.", routePath: "/mission-control/credentials/", iconKey: "key-round", external: false },
        ],
      },
      { surface: "Terminal", routeName: "mission_control:terminal", audience: "both", purpose: "Access terminal sessions when a range is available.", routePath: "/mission-control/terminal/", iconKey: "terminal", activeContext: "range", external: false },
      { surface: "Settings", routeName: "mission_control:settings", purpose: "Change user or platform settings.", routePath: "/mission-control/settings/", iconKey: "settings" },
    ],
  ),
  makeGroup(
    "Author",
    "operator",
    { audience: "organizer", permissionPolicy: "threat_research", ownerApp: "cms", external: true },
    [
      // In-SPA once SCENARIO_EDITOR_SPA_ENABLED is on (#1371); the feature-flag
      // gate hides the entry until the flag flips, matching the rollout pattern.
      {
        surface: "Scenarios",
        routeName: "scenario_editor:list",
        purpose: "Browse scenarios and readiness metadata.",
        routePath: "/scenario-editor/",
        iconKey: "file-code",
        external: false,
        featureFlag: "scenario_editor_spa",
      },
      // In-SPA ACES image registry management (#1566). Greenfield surface gated
      // by `aces_native_provisioning` (mirrors SHIFTER_ACES_NATIVE_PROVISIONING);
      // hidden until the native path is enabled. Advisory visibility only — the
      // /api/v1/cms/aces-image-mappings/ endpoints remain the authority.
      {
        surface: "ACES Images",
        routeName: "aces_image_registry",
        purpose: "Map authored ACES image sources to concrete provider images.",
        routePath: "/aces-image-registry/",
        iconKey: "boxes",
        external: false,
        featureFlag: "aces_native_provisioning",
      },
    ],
  ),
  makeGroup(
    "Govern",
    "operator",
    { audience: "organizer", permissionPolicy: "risk_register_access", ownerApp: "risk_register" },
    [
      { surface: "Risk Register", routeName: "risk_register:risk_list", purpose: "List current and historical risks.", routePath: "/risk-register", iconKey: "shield-alert" },
    ],
  ),
  makeGroup(
    "Administer",
    "operator",
    { audience: "organizer", permissionPolicy: "staff", ownerApp: "management" },
    [
      // In-SPA Administer workspace (#1373), gated by administer_spa. Hidden until
      // the flag flips; the Django admin escape hatch below stays available in
      // every rollout state so /admin/ is never lost from the nav.
      {
        surface: "Users",
        routeName: "administer:users",
        purpose: "Manage users and access.",
        routePath: "/administer",
        iconKey: "user-cog",
        external: false,
        featureFlag: "administer_spa",
      },
      {
        surface: "Cost",
        routeName: "administer:cost",
        purpose: "Cost reporting.",
        routePath: "/administer/cost",
        iconKey: "circle-dollar-sign",
        external: false,
        featureFlag: "administer_spa",
      },
      {
        surface: "Platform Settings",
        routeName: "administer:settings",
        purpose: "Read-only platform configuration.",
        routePath: "/administer/settings",
        iconKey: "settings",
        external: false,
        featureFlag: "administer_spa",
      },
      // Django admin escape hatch: always available, linked as a full-page legacy
      // handoff and never wrapped or described as a SPA-native workflow.
      {
        surface: "Django Admin",
        routeName: "admin:index",
        purpose: "Full Django administration.",
        routePath: "/admin/",
        iconKey: "shield",
        external: true,
      },
    ],
  ),
];

/** Evaluate an advisory permission policy against the bootstrap payload. */
export function permissionAllows(policy: PermissionPolicy, bootstrap: Bootstrap): boolean {
  switch (policy) {
    case "authenticated":
      return bootstrap.principal.is_authenticated;
    case "risk_register_access":
      return bootstrap.permissions.can_access_risk_register;
    case "threat_research":
      return bootstrap.permissions.can_access_threat_research;
    case "ctf_organizer":
      return bootstrap.permissions.is_ctf_organizer;
    case "ctf_participant":
      return bootstrap.permissions.is_ctf_participant;
    case "staff":
      return bootstrap.principal.is_staff;
    default:
      return false;
  }
}

/** True when an entry should be shown (advisory permission + feature flag). */
export function isNavEntryVisible(entry: NavEntry, bootstrap: Bootstrap): boolean {
  if (entry.featureFlag && !bootstrap.feature_flags[entry.featureFlag]) {
    return false;
  }
  return permissionAllows(entry.permissionPolicy, bootstrap);
}

/**
 * Return the visible nav groups for a mode: filtered to the current mode, with
 * each group's entries (and any children) filtered by advisory visibility, and
 * empty groups dropped.
 */
export function visibleNavGroups(mode: UxMode, bootstrap: Bootstrap): NavGroup[] {
  return NAV_GROUPS.filter((group) => group.mode === mode)
    .map((group) => ({
      ...group,
      entries: group.entries
        .filter((entry) => isNavEntryVisible(entry, bootstrap))
        .map((entry) => ({
          ...entry,
          children: entry.children?.filter((child) => isNavEntryVisible(child, bootstrap)),
        })),
    }))
    .filter((group) => group.entries.length > 0);
}
