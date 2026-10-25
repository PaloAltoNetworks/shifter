"""Resolve deduplicated account references to their authoritative definitions (M04).

The reserve path consumes the already-deduplicated spend/rate/concurrency
reference sets from ``compile_effective_policy`` and must resolve each to a
single, dimension-matched, server-owned account definition. Statically declared
accounts live in the v3 catalog; dynamic event and standalone-owner accounts
arrive through a typed server-owned projection so the participant-authored demand
JSON is never overloaded. Resolution fails closed on any unresolved reference,
dimension mismatch, or a projection attempting to shadow a catalog account.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from shared.model_access.catalog import ContractError
from shared.model_access.catalog_v3 import ModelAccessCatalogV3
from shared.model_access.core_models import (
    AccountDefinition,
    AccountDimension,
    ClosedModel,
    _require_unique,
)

_UNRESOLVED = "contract.account_unresolved"
_SHADOWED = "contract.account_shadowed"


class AccountPolicyProjection(ClosedModel):
    """Typed, server-owned definitions for dynamic event and standalone-owner accounts."""

    contract_version: Literal["model-access-account-policy/v1"]
    deployment_id: UUID
    account_definitions: tuple[AccountDefinition, ...] = Field(max_length=256)

    @model_validator(mode="after")
    def _unique_accounts(self) -> AccountPolicyProjection:
        """Reject duplicate account references within one projection."""
        _require_unique(
            tuple(definition.account_ref for definition in self.account_definitions),
            "account_ref",
        )
        return self


class ResolvedRequestAccounts(ClosedModel):
    """The dimension-partitioned account definitions applicable to one request."""

    spend: tuple[AccountDefinition, ...] = ()
    rate: tuple[AccountDefinition, ...] = ()
    concurrency: tuple[AccountDefinition, ...] = ()


def resolve_request_accounts(
    *,
    catalog: ModelAccessCatalogV3,
    spend_account_refs: Iterable[str],
    rate_account_refs: Iterable[str],
    concurrency_account_refs: Iterable[str],
    projection: AccountPolicyProjection | None = None,
) -> ResolvedRequestAccounts:
    """Resolve each reference set to matching-dimension definitions, failing closed."""
    by_ref: dict[str, AccountDefinition] = {
        definition.account_ref: definition for definition in catalog.account_definitions
    }
    if projection is not None:
        for definition in projection.account_definitions:
            if definition.account_ref in by_ref:
                raise ContractError(_SHADOWED, definition.account_ref)
            by_ref[definition.account_ref] = definition
    return ResolvedRequestAccounts(
        spend=_resolve(spend_account_refs, AccountDimension.SPEND, by_ref),
        rate=_resolve(rate_account_refs, AccountDimension.RATE, by_ref),
        concurrency=_resolve(concurrency_account_refs, AccountDimension.CONCURRENCY, by_ref),
    )


def _resolve(
    refs: Iterable[str],
    dimension: AccountDimension,
    by_ref: dict[str, AccountDefinition],
) -> tuple[AccountDefinition, ...]:
    """Deduplicate references and resolve each to a definition of the given dimension."""
    resolved: dict[str, AccountDefinition] = {}
    for ref in refs:
        definition = by_ref.get(ref)
        if definition is None or definition.dimension is not dimension:
            raise ContractError(_UNRESOLVED, ref)
        resolved[ref] = definition
    return tuple(resolved[ref] for ref in sorted(resolved))
