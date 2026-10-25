"""Malformed private replies cannot become credentials or dispatch authority."""

import ssl

import httpx
import pytest

from model_broker.control import ControlClient
from shared.model_access import ContractError


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route", "payload", "reply"),
    [
        ("ready", {}, {"ready": "true"}),
        ("exchange", {}, {"access_token": "unbounded-private-material"}),
        ("reserve", {}, {"request_uuid": "not-a-request", "canonical_request_cost": -1}),
        ("advance", {"action": "check"}, {"valid": False}),
        ("advance", {"action": "check"}, {"valid": 1}),
        ("advance", {"action": "dispatch"}, {"dispatch_token": "token", "deadline": "invalid"}),
        ("advance", {"action": "continue"}, {"revision": 1, "deadline": "2020-01-01"}),
        ("finish", {"action": "unknown"}, {"recorded": False}),
        ("finish", {"action": "unknown"}, {"recorded": 1}),
        ("finish", {"action": "release"}, {"released": 1}),
    ],
)
async def test_control_rejects_invalid_authority_replies(route, payload, reply):
    async def identity():
        return "synthetic-workload-assertion"

    control = ControlClient(
        url="https://control.invalid", ca_file=ssl.get_default_verify_paths().cafile, identity=identity
    )
    await control.client.aclose()
    control.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=reply)))
    try:
        with pytest.raises(ContractError, match=r"control.invalid_response"):
            await control.call(route, payload)
    finally:
        await control.close()
