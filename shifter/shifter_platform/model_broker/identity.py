"""Broker workload authentication independent of provider invocation credentials."""

from shared.model_access import ContractError
from shared.model_access.work import BoundedWork
from shared.model_access.workload_identity import workload_assertion

_IDENTITY_WORK = BoundedWork(8, name="broker-identity")


class WorkloadIdentity:
    """Use the broker's own cloud identity for the fixed Engine audience."""

    def __init__(self, *, provider: str, region: str, audience: str) -> None:
        if provider not in {"aws", "gcp"} or not audience or len(audience) > 256:
            raise ValueError("invalid broker control identity configuration")
        self.provider, self.region, self.audience = provider, region, audience

    async def __call__(self) -> str:
        try:
            return await _IDENTITY_WORK.run(self._assertion)
        except Exception:
            raise ContractError("control.identity_unavailable") from None

    def _assertion(self) -> str:
        return workload_assertion(provider=self.provider, region=self.region, audience=self.audience)
