"""Read-only, fail-closed classification of legacy customer structures.

The S8 migrator supplies complete owner evidence from owning domains. This
module never edits, deletes, or rehomes a legacy organization or workspace.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from workspaces.models import Organization, OrganizationMembership, Workspace, WorkspaceMembership


@dataclass(frozen=True, slots=True)
class MappingBlocker:
    """One fact that prevents a legacy row from receiving an inferred mapping."""

    reason: str
    entity_id: int


@dataclass(frozen=True, slots=True)
class IndividualMapping:
    """Proposed account mapping for one unambiguous personal workspace."""

    principal_uuid: UUID
    user_id: int
    legacy_organization_id: int
    legacy_workspace_id: int


@dataclass(frozen=True, slots=True)
class OrganizationMapping:
    """Proposed account mapping for one shared legacy organization."""

    organization_id: int
    account_kind: str
    default_workspace_id: int | None


@dataclass(frozen=True, slots=True)
class MembershipMapping:
    """Proposed principal membership retained from a legacy scope."""

    scope_kind: str
    scope_id: int
    principal_uuid: UUID
    role: str


@dataclass(frozen=True, slots=True)
class LegacyAccountMappingPlan:
    """Complete read-only legacy-account mapping result and its blockers."""

    individuals: tuple[IndividualMapping, ...]
    organizations: tuple[OrganizationMapping, ...]
    memberships: tuple[MembershipMapping, ...]
    blockers: tuple[MappingBlocker, ...]


def _classify_personal(
    organization: Organization,
    workspace: Workspace,
    principal_by_user: Mapping[int, UUID],
    owner_ids_by_workspace: Mapping[int, set[int]],
) -> tuple[IndividualMapping | None, list[MappingBlocker]]:
    """Classify one personal workspace only when every ownership fact agrees."""
    user_id = workspace.personal_for_user_id
    if user_id is None:
        return None, [MappingBlocker("personal_structure_ambiguous", workspace.pk)]
    blockers: list[MappingBlocker] = []
    members = list(WorkspaceMembership.objects.filter(workspace=workspace).values_list("user_id", "role"))
    admins = list(OrganizationMembership.objects.filter(organization=organization).values_list("user_id", "role"))
    if members != [(user_id, "owner")] or admins != [(user_id, "admin")]:
        blockers.append(MappingBlocker("personal_membership_ambiguous", workspace.pk))
    if workspace.pk not in owner_ids_by_workspace:
        blockers.append(MappingBlocker("resource_owner_evidence_missing", workspace.pk))
    elif set(owner_ids_by_workspace[workspace.pk]) - {user_id}:
        blockers.append(MappingBlocker("resource_owner_mismatch", workspace.pk))
    principal_uuid = principal_by_user.get(user_id)
    if not isinstance(principal_uuid, UUID) or principal_uuid.int == 0:
        blockers.append(MappingBlocker("principal_missing", user_id))
    if blockers or not isinstance(principal_uuid, UUID):
        return None, blockers
    return IndividualMapping(principal_uuid, user_id, organization.pk, workspace.pk), []


def _classify_shared_memberships(
    organization: Organization,
    workspaces: list[Workspace],
    principal_by_user: Mapping[int, UUID],
) -> tuple[list[MembershipMapping], list[MappingBlocker]]:
    """Map shared memberships only when every member has a valid principal."""
    mappings: list[MembershipMapping] = []
    blockers: list[MappingBlocker] = []
    rows = [
        ("organization", organization.pk, member.user_id, member.role)
        for member in OrganizationMembership.objects.filter(organization=organization).order_by("pk")
    ]
    for workspace in workspaces:
        rows.extend(
            ("workspace", workspace.pk, member.user_id, member.role)
            for member in WorkspaceMembership.objects.filter(workspace=workspace).order_by("pk")
        )
    for scope_kind, scope_id, user_id, role in rows:
        if user_id is None:
            # Principal-only facts already have their durable identity. They are
            # not legacy user/role rows and must remain untouched by this plan.
            continue
        principal_uuid = principal_by_user.get(user_id)
        if not isinstance(principal_uuid, UUID) or principal_uuid.int == 0:
            blockers.append(MappingBlocker("principal_missing", user_id))
        else:
            mappings.append(MembershipMapping(scope_kind, scope_id, principal_uuid, role))
    return mappings, blockers


def _principal_mapping_blockers(principal_by_user: Mapping[int, UUID]) -> list[MappingBlocker]:
    """Validate that every supplied user-to-principal mapping is unique and usable."""
    blockers: list[MappingBlocker] = []
    seen_principals: set[UUID] = set()
    for user_id, principal_uuid in principal_by_user.items():
        if not isinstance(principal_uuid, UUID) or principal_uuid.int == 0:
            blockers.append(MappingBlocker("principal_invalid", user_id))
        elif principal_uuid in seen_principals:
            blockers.append(MappingBlocker("duplicate_principal_mapping", user_id))
        else:
            seen_principals.add(principal_uuid)
    return blockers


def _classify_personal_organization(
    organization: Organization,
    workspaces: list[Workspace],
    personal: list[Workspace],
    principal_by_user: Mapping[int, UUID],
    owner_ids_by_workspace: Mapping[int, set[int]],
) -> tuple[IndividualMapping | None, list[MappingBlocker]]:
    """Classify an organization containing a personal workspace shape."""
    if len(workspaces) != 1 or len(personal) != 1:
        return None, [MappingBlocker("personal_structure_ambiguous", organization.pk)]
    return _classify_personal(organization, personal[0], principal_by_user, owner_ids_by_workspace)


def _classify_shared_organization(
    organization: Organization,
    workspaces: list[Workspace],
    principal_by_user: Mapping[int, UUID],
    owner_ids_by_workspace: Mapping[int, set[int]],
    account_types_by_organization: Mapping[UUID, str],
) -> tuple[OrganizationMapping | None, list[MembershipMapping], list[MappingBlocker]]:
    """Classify a shared organization when its default and owner evidence agree."""
    account_kind, blocker = _shared_structure(
        organization, workspaces, principal_by_user, owner_ids_by_workspace, account_types_by_organization
    )
    if blocker is not None:
        return None, [], [blocker]
    memberships, blockers = _classify_shared_memberships(organization, workspaces, principal_by_user)
    if blockers:
        return None, [], blockers
    return OrganizationMapping(organization.pk, account_kind, workspaces[0].pk), memberships, []


def _shared_structure(
    organization: Organization,
    workspaces: list[Workspace],
    principal_by_user: Mapping[int, UUID],
    owner_ids_by_workspace: Mapping[int, set[int]],
    account_types_by_organization: Mapping[UUID, str],
) -> tuple[str, MappingBlocker | None]:
    """Return the shared-account kind and the first missing structural fact."""
    account_kind = account_types_by_organization.get(organization.uuid, "")
    reason: str | None = None
    if account_kind not in ("team", "enterprise"):
        reason = "account_type_missing"
    elif not workspaces:
        reason = "default_workspace_missing"
    elif len(workspaces) > 1:
        reason = "default_workspace_ambiguous"
    elif any(workspace.pk not in owner_ids_by_workspace for workspace in workspaces):
        reason = "resource_owner_evidence_missing"
    elif any(
        user_id not in principal_by_user for workspace in workspaces for user_id in owner_ids_by_workspace[workspace.pk]
    ):
        reason = "principal_missing_for_resource_owner"
    blocker = MappingBlocker(reason, organization.pk) if reason is not None else None
    return account_kind, blocker


def _classify_legacy_organization(
    organization: Organization,
    principal_by_user: Mapping[int, UUID],
    owner_ids_by_workspace: Mapping[int, set[int]],
    account_types_by_organization: Mapping[UUID, str],
) -> tuple[IndividualMapping | None, OrganizationMapping | None, list[MembershipMapping], list[MappingBlocker]]:
    """Classify one unbound legacy organization as personal or shared."""
    workspaces = list(Workspace.objects.filter(organization=organization).order_by("pk"))
    personal = [workspace for workspace in workspaces if workspace.personal_for_user_id is not None]
    if personal:
        individual, blockers = _classify_personal_organization(
            organization, workspaces, personal, principal_by_user, owner_ids_by_workspace
        )
        return individual, None, [], blockers
    shared, memberships, blockers = _classify_shared_organization(
        organization, workspaces, principal_by_user, owner_ids_by_workspace, account_types_by_organization
    )
    return None, shared, memberships, blockers


def plan_legacy_account_mapping(
    *,
    principal_by_user: Mapping[int, UUID],
    owner_ids_by_workspace: Mapping[int, set[int]],
    account_types_by_organization: Mapping[UUID, str],
) -> LegacyAccountMappingPlan:
    """Classify unbound rows using exact user, UUID, membership, and owner facts.

    The caller must supply complete CMS/Engine/CTF owner evidence keyed by the
    existing workspace primary key. An empty owner set means no scoped owner
    rows; it is never a permission grant or installation scope.
    """
    individuals: list[IndividualMapping] = []
    organizations: list[OrganizationMapping] = []
    memberships: list[MembershipMapping] = []
    blockers: list[MappingBlocker] = []

    blockers.extend(_principal_mapping_blockers(principal_by_user))
    if blockers:
        return LegacyAccountMappingPlan((), (), (), tuple(blockers))

    for organization in Organization.objects.filter(account__isnull=True).order_by("pk"):
        individual, shared, mapped_members, organization_blockers = _classify_legacy_organization(
            organization, principal_by_user, owner_ids_by_workspace, account_types_by_organization
        )
        blockers.extend(organization_blockers)
        if individual is not None:
            individuals.append(individual)
        if shared is not None:
            organizations.append(shared)
            memberships.extend(mapped_members)

    return LegacyAccountMappingPlan(tuple(individuals), tuple(organizations), tuple(memberships), tuple(blockers))
