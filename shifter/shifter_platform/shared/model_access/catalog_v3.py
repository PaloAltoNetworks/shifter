"""Versioned account definitions give spend/rate/concurrency refs meaning (M04).

v3 closes the contract gap that blocks budget enforcement: `SharingPool` carried
opaque spend/rate/concurrency account references, but no catalog version defined
their dimension, unit, currency, ceiling, UTC window, revision, or authority
source. v1/v2 wire digests and semantics are unchanged.
"""

from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from shared.model_access.catalog_v2 import ModelAccessCatalogV2
from shared.model_access.core_models import AccountDefinition, AccountDimension, _require_unique

# Each monetary/rate/concurrency facet reference on a sharing pool must resolve
# to an account definition of the matching dimension. Capacity references remain
# quota (M03) and are validated against quota pools, not account definitions.
_DIMENSION_FACETS: tuple[tuple[AccountDimension, str], ...] = (
    (AccountDimension.SPEND, "spend_account_refs"),
    (AccountDimension.RATE, "rate_account_refs"),
    (AccountDimension.CONCURRENCY, "concurrency_account_refs"),
)


class ModelAccessCatalogV3(ModelAccessCatalogV2):
    """v3 defines every referenced spend/rate/concurrency account; v1/v2 stay readable."""

    # Pydantic version subclasses intentionally replace the wire discriminant;
    # mypy treats the disjoint Literal override as an incompatible assignment.
    contract_version: Literal["model-access-policy/v3"]  # type: ignore[assignment]
    account_definitions: Annotated[tuple[AccountDefinition, ...], Field(max_length=256)]

    @field_validator("account_definitions")
    @classmethod
    def _normalize_account_definitions(cls, values: tuple[AccountDefinition, ...]) -> tuple[AccountDefinition, ...]:
        """Make declaration order immaterial to catalog identity and reject duplicates."""
        _require_unique(tuple(definition.account_ref for definition in values), "account_ref")
        return tuple(sorted(values, key=lambda definition: definition.account_ref))

    @model_validator(mode="after")
    def _validate_account_references(self) -> Self:
        """Every statically referenced account resolves to a matching-dimension definition."""
        by_ref = {definition.account_ref: definition for definition in self.account_definitions}
        for pool in self.sharing_pools:
            for dimension, field_name in _DIMENSION_FACETS:
                for ref in getattr(pool, field_name):
                    definition = by_ref.get(ref)
                    if definition is None or definition.dimension is not dimension:
                        raise ValueError("sharing pool references an undefined or mismatched account")
        return self
