"""Closed provider outcomes; no upstream payloads or credentials in exceptions."""

from shared.model_access import ContractError
from shared.model_access.core_models import BillingComponent
from shared.model_access.provider import ProviderUsage, VerifiedUsage


class NoBillableEffect(ContractError):
    """The adapter proves it never started a billable invocation."""

    def __init__(self, code: str, *, count_only: bool) -> None:
        super().__init__(code)
        components = (
            (BillingComponent.REQUEST,)
            if count_only
            else (BillingComponent.INPUT_TOKENS, BillingComponent.OUTPUT_TOKENS)
        )
        self.usage = ProviderUsage(
            items=tuple(VerifiedUsage(component=component, units=0, provider_verified=True) for component in components)
        )
