"""Provider port for the application authorization evaluator."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

from .contracts import AuthorizationDecision, AuthorizationRequest
from .relationships import (
    AuthorizationRelationshipChange,
    RelationshipChangePage,
    RelationshipObjectType,
    RelationshipState,
    VersionedRelationshipChange,
)


class AuthorizationProvider(Protocol):
    """The only evaluator surface owning services may consume."""

    @property
    def store_id(self) -> str: ...

    @property
    def model_id(self) -> str: ...

    def check(self, request: AuthorizationRequest) -> AuthorizationDecision: ...

    def batch_check(self, requests: Sequence[AuthorizationRequest]) -> tuple[AuthorizationDecision, ...]: ...

    def write_relationships(self, change: AuthorizationRelationshipChange | VersionedRelationshipChange) -> None: ...

    def read_relationships(
        self,
        change: AuthorizationRelationshipChange | VersionedRelationshipChange,
    ) -> RelationshipState: ...

    def read_changes(
        self,
        object_type: RelationshipObjectType,
        *,
        continuation_token: str = "",
        page_size: int = 100,
    ) -> RelationshipChangePage: ...


class AuthorizationProviderBindingError(RuntimeError):
    """No unique runtime authorization provider factory is available."""


AuthorizationProviderFactory = Callable[[], AuthorizationProvider]
_provider_factory: AuthorizationProviderFactory | None = None


def bind_authorization_provider_factory(factory: AuthorizationProviderFactory) -> None:
    """Bind the config-owned SDK factory once at composition startup."""
    global _provider_factory
    if _provider_factory is not None and _provider_factory is not factory:
        raise AuthorizationProviderBindingError("A different authorization provider factory is already bound")
    _provider_factory = factory


def configured_authorization_provider() -> AuthorizationProvider:
    """Build the configured provider or fail closed when composition is absent."""
    if _provider_factory is None:
        raise AuthorizationProviderBindingError("No authorization provider factory is bound")
    try:
        return _provider_factory()
    except Exception as exc:
        raise AuthorizationProviderBindingError("Authorization provider is unavailable") from exc
