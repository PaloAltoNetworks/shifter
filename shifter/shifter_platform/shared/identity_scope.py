"""Neutral, explicit principal and customer resource identities (ADR-066).

These values describe identity and scope, not an authorization grant. Owning
services resolve ancestry and permissions before persisting or using a scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID


class ScopeContractError(ValueError):
    """An identity or resource-scope shape is invalid."""


def _valid_uuid(value: object) -> bool:
    """Return whether a value is a non-nil UUID identity."""
    return isinstance(value, UUID) and value.int != 0


@dataclass(frozen=True, slots=True)
class PrincipalRef:
    """One durable human or service identity, independent of credentials."""

    uuid: UUID
    kind: Literal["human", "service"]

    def __post_init__(self) -> None:
        if not _valid_uuid(self.uuid) or self.kind not in ("human", "service"):
            raise ScopeContractError("Invalid principal reference")


@dataclass(frozen=True, slots=True)
class ResourceScope:
    """Explicit installation or account scope with optional nested ancestry."""

    kind: Literal["installation", "account"]
    account_uuid: UUID | None = None
    organization_uuid: UUID | None = None
    workspace_uuid: UUID | None = None

    def __post_init__(self) -> None:
        if self.kind == "installation":
            if any(value is not None for value in (self.account_uuid, self.organization_uuid, self.workspace_uuid)):
                raise ScopeContractError("Installation scope cannot contain customer identities")
            return
        if self.kind != "account" or not _valid_uuid(self.account_uuid):
            raise ScopeContractError("Account scope requires a valid account identity")
        if self.organization_uuid is not None and not _valid_uuid(self.organization_uuid):
            raise ScopeContractError("Invalid organization identity")
        if self.workspace_uuid is not None and (self.organization_uuid is None or not _valid_uuid(self.workspace_uuid)):
            raise ScopeContractError("Workspace scope requires a valid organization identity")
