"""Closed-contract normalization for model allocation service boundaries."""

from pydantic import BaseModel, ValidationError

from shared.model_access import ContractError
from shared.model_access.reservation import ModelQuotaObservation


def validated[TContractModel: BaseModel](model: type[TContractModel], value: object) -> TContractModel:
    """Normalize one service-boundary value through its closed contract."""
    try:
        return model.model_validate(value.model_dump(mode="json") if isinstance(value, model) else value)
    except (ValueError, TypeError, ValidationError):
        raise ContractError("allocation.invalid_input") from None


def normalize_observations(observations: tuple[object, ...]) -> dict[str, ModelQuotaObservation]:
    """Validate readings and reject ambiguous duplicates before locking."""
    validated_observations = tuple(validated(ModelQuotaObservation, item) for item in observations)
    observed = {item.quota_pool_id: item for item in validated_observations}
    if len(observed) != len(validated_observations):
        raise ContractError("allocation.duplicate_observation")
    return observed
