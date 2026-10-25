"""Typed relationship changes accepted by the OpenFGA adapter."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID

from .catalog import (
    AuthorizationContractError,
    PredefinedPolicyDefinition,
    action_definition,
    predefined_policy_definition,
)
from .contracts import TargetRef
from .model import deny_relation_for_action, grant_relation_for_action

SubjectKind = Literal["principal", "group", "role"]
RelationshipObjectType = Literal[
    "principal",
    "group",
    "role",
    "installation",
    "account",
    "organization",
    "workspace",
    "event",
    "range",
]


@dataclass(frozen=True, slots=True)
class RelationshipSubject:
    """Closed principal or native group/role userset identity."""

    kind: SubjectKind
    uuid: UUID

    def __post_init__(self) -> None:
        if self.kind not in {"principal", "group", "role"} or not isinstance(self.uuid, UUID) or self.uuid.int == 0:
            raise AuthorizationContractError("Invalid authorization relationship subject")

    @property
    def openfga_user(self) -> str:
        suffix = {"principal": "", "group": "#member", "role": "#assignee"}[self.kind]
        return f"{self.kind}:{self.uuid}{suffix}"


@dataclass(frozen=True, slots=True)
class RelationshipTuple:
    """Adapter-ready tuple assembled only from closed application contracts."""

    user: str
    relation: str
    object: str


class AuthorizationProviderError(RuntimeError):
    """A sanitized evaluator/store failure with no provider payload."""


@dataclass(frozen=True, slots=True)
class RelationshipState:
    """Exact primary-backed state used only for write reconciliation."""

    grant_present: bool
    deny_present: bool


@dataclass(frozen=True, slots=True)
class RelationshipChangePage:
    """Bounded diagnostic change-feed metadata; tuple payloads stay provider-local."""

    change_count: int
    continuation_token: str


class PolicyEffect(StrEnum):
    """Explicit grant or revoke intent for a typed relationship mutation."""

    GRANT = "grant"
    REVOKE = "revoke"


class RelationshipChange(Protocol):
    """Closed tuple mutation shape accepted by the provider adapter."""

    effect: PolicyEffect

    @property
    def grant_tuple(self) -> RelationshipTuple: ...

    @property
    def deny_tuple(self) -> RelationshipTuple: ...

    @property
    def writes(self) -> tuple[RelationshipTuple, ...]: ...

    @property
    def deletes(self) -> tuple[RelationshipTuple, ...]: ...


class _MonotonicChange(ABC):
    """Shared positive/explicit-exclusion mutation behavior."""

    effect: PolicyEffect

    @property
    @abstractmethod
    def grant_tuple(self) -> RelationshipTuple:
        """Return the positive relationship for this typed change."""
        raise NotImplementedError

    @property
    @abstractmethod
    def deny_tuple(self) -> RelationshipTuple:
        """Return the explicit exclusion for this typed change."""
        raise NotImplementedError

    @property
    def writes(self) -> tuple[RelationshipTuple, ...]:
        return (self.grant_tuple,) if self.effect == PolicyEffect.GRANT else (self.deny_tuple,)

    @property
    def deletes(self) -> tuple[RelationshipTuple, ...]:
        return (self.deny_tuple,) if self.effect == PolicyEffect.GRANT else (self.grant_tuple,)


@dataclass(frozen=True, slots=True)
class PolicyRelationshipChange(_MonotonicChange):
    """One action assignment with a monotonic revocation fence."""

    subject: RelationshipSubject
    action: str
    target: TargetRef
    effect: PolicyEffect

    def __post_init__(self) -> None:
        definition = action_definition(self.action)
        if definition.target_type != self.target.type:
            raise AuthorizationContractError("Action target type does not match relationship target")
        if not isinstance(self.effect, PolicyEffect):
            raise AuthorizationContractError("Invalid policy relationship effect")

    @property
    def _object(self) -> str:
        if self.target.type == "installation":
            return "installation:root"
        return f"{self.target.type}:{self.target.uuid}"

    @property
    def grant_tuple(self) -> RelationshipTuple:
        return RelationshipTuple(self.subject.openfga_user, grant_relation_for_action(self.action), self._object)

    @property
    def deny_tuple(self) -> RelationshipTuple:
        return RelationshipTuple(self.subject.openfga_user, deny_relation_for_action(self.action), self._object)


@dataclass(frozen=True, slots=True)
class GroupMembershipChange(_MonotonicChange):
    """Native group membership with an exclusion tuple as its revoke fence."""

    group_uuid: UUID
    principal_uuid: UUID
    effect: PolicyEffect

    def __post_init__(self) -> None:
        if (
            not isinstance(self.group_uuid, UUID)
            or self.group_uuid.int == 0
            or not isinstance(self.principal_uuid, UUID)
            or self.principal_uuid.int == 0
            or not isinstance(self.effect, PolicyEffect)
        ):
            raise AuthorizationContractError("Invalid group membership relationship")

    @property
    def grant_tuple(self) -> RelationshipTuple:
        return RelationshipTuple(f"principal:{self.principal_uuid}", "direct_member", f"group:{self.group_uuid}")

    @property
    def deny_tuple(self) -> RelationshipTuple:
        return RelationshipTuple(f"principal:{self.principal_uuid}", "excluded", f"group:{self.group_uuid}")


@dataclass(frozen=True, slots=True)
class RoleAssignmentChange(_MonotonicChange):
    """Native custom-role assignment for a principal or group userset."""

    role_uuid: UUID
    subject: RelationshipSubject
    effect: PolicyEffect

    def __post_init__(self) -> None:
        if (
            not isinstance(self.role_uuid, UUID)
            or self.role_uuid.int == 0
            or self.subject.kind not in {"principal", "group"}
            or not isinstance(self.effect, PolicyEffect)
        ):
            raise AuthorizationContractError("Invalid role assignment relationship")

    @property
    def grant_tuple(self) -> RelationshipTuple:
        return RelationshipTuple(self.subject.openfga_user, "direct_assignee", f"role:{self.role_uuid}")

    @property
    def deny_tuple(self) -> RelationshipTuple:
        return RelationshipTuple(self.subject.openfga_user, "excluded", f"role:{self.role_uuid}")


@dataclass(frozen=True, slots=True)
class AdministrativeRoleChange(_MonotonicChange):
    """Assignment of one closed predefined administrator/operator policy."""

    subject: RelationshipSubject
    policy_code: str
    target: TargetRef
    effect: PolicyEffect

    def __post_init__(self) -> None:
        definition = predefined_policy_definition(self.policy_code)
        if self.subject.kind not in {"principal", "group"}:
            raise AuthorizationContractError("Invalid predefined policy subject")
        if definition.target_type != self.target.type:
            raise AuthorizationContractError("Predefined policy target does not match relationship target")
        if not isinstance(self.effect, PolicyEffect):
            raise AuthorizationContractError("Invalid predefined policy relationship effect")

    @property
    def _object(self) -> str:
        if self.target.type == "installation":
            return "installation:root"
        return f"{self.target.type}:{self.target.uuid}"

    @property
    def _definition(self) -> PredefinedPolicyDefinition:
        return predefined_policy_definition(self.policy_code)

    @property
    def grant_tuple(self) -> RelationshipTuple:
        return RelationshipTuple(
            self.subject.openfga_user,
            f"direct_{self._definition.relation}",
            self._object,
        )

    @property
    def deny_tuple(self) -> RelationshipTuple:
        return RelationshipTuple(
            self.subject.openfga_user,
            f"deny_{self._definition.relation}",
            self._object,
        )


type AuthorizationRelationshipChange = (
    PolicyRelationshipChange | GroupMembershipChange | RoleAssignmentChange | AdministrativeRoleChange
)


@dataclass(frozen=True, slots=True)
class VersionedRelationshipChange:
    """Append-only provider mutation whose prior generation is made inert.

    Each generation writes through its own binding object. A later generation
    adds a permanent supersession tuple to the prior binding, so a delayed
    earlier OpenFGA transaction can only populate an already-inert object.
    """

    change: AuthorizationRelationshipChange
    fence_key: str
    generation: int

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", self.fence_key):
            raise AuthorizationContractError("Invalid relationship fence key")
        if not isinstance(self.generation, int) or isinstance(self.generation, bool) or self.generation < 1:
            raise AuthorizationContractError("Invalid relationship generation")

    @property
    def effect(self) -> PolicyEffect:
        return self.change.effect

    @property
    def grant_tuple(self) -> RelationshipTuple:
        return self.change.grant_tuple

    @property
    def deny_tuple(self) -> RelationshipTuple:
        return self.change.deny_tuple

    def _binding_object(self, generation: int) -> str:
        return f"authorization_binding:{self.fence_key}-{generation}"

    @property
    def _candidate_tuple(self) -> RelationshipTuple:
        return RelationshipTuple(
            self.change.grant_tuple.user,
            "candidate",
            self._binding_object(self.generation),
        )

    @property
    def _effective_tuple(self) -> RelationshipTuple:
        target = self.change.grant_tuple if self.effect == PolicyEffect.GRANT else self.change.deny_tuple
        return RelationshipTuple(
            f"{self._binding_object(self.generation)}#active",
            target.relation,
            target.object,
        )

    @property
    def _superseded_tuple(self) -> RelationshipTuple | None:
        if self.generation == 1:
            return None
        return RelationshipTuple(
            self.change.grant_tuple.user,
            "superseded",
            self._binding_object(self.generation - 1),
        )

    @property
    def writes(self) -> tuple[RelationshipTuple, ...]:
        superseded = self._superseded_tuple
        writes = [self._candidate_tuple, self._effective_tuple]
        if superseded is not None:
            writes.append(superseded)
        return tuple(writes)

    @property
    def deletes(self) -> tuple[RelationshipTuple, ...]:
        return ()
