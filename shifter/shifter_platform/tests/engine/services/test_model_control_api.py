"""Exercise the private HTTP boundary through real Engine transactions."""

import asyncio
import threading

import httpx
import pytest

from engine.model_access_control.server import ControlApplication
from shared.model_access import ContractError

from .test_model_credentials import _PEER, enrolled_allocation, issue

__all__ = ["enrolled_allocation"]
pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


@pytest.fixture
def control_case(enrolled_allocation):
    enrollment = issue(enrolled_allocation)

    def verify(assertion, *, operation_id):
        expected = f"provisioner:{operation_id}" if operation_id else "broker"
        if assertion != expected:
            raise ContractError("control.unauthorized")

    return ControlApplication(verify_identity=verify, ready=lambda: True), enrollment, enrolled_allocation


async def test_control_exchange_and_authenticate_use_actual_guest_binding(control_case):
    app, enrollment, allocation = control_case
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://control.invalid") as client:
        payload = {"token": enrollment.enrollment_token.get_secret_value(), "transport_peer": _PEER}
        denied = await client.post("/control/v1/exchange", json=payload)
        assert denied.status_code == 401
        accepted = await client.post("/control/v1/exchange", json=payload, headers={"authorization": "broker"})
        assert accepted.status_code == 200, accepted.text
        token = accepted.json()["access_token"]
        authorized = await client.post(
            "/control/v1/authenticate",
            json={"token": token, "transport_peer": _PEER},
            headers={"authorization": "broker"},
        )
        assert authorized.status_code == 200
        assert authorized.json()["allocation_id"] == str(allocation.pk)
        assert "refresh_token" not in authorized.json()
        replay = await client.post("/control/v1/exchange", json=payload, headers={"authorization": "broker"})
        assert replay.status_code == 401


async def test_broker_identity_cannot_issue_enrollment(control_case):
    app, _, allocation = control_case
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://control.invalid") as client:
        payload = {"allocation_id": str(allocation.pk), "operation_id": str(allocation.operation_id)}
        denied = await client.post("/control/v1/enroll", json=payload, headers={"authorization": "broker"})
        assert denied.status_code == 401
        accepted = await client.post(
            "/control/v1/enroll", json=payload, headers={"authorization": f"provisioner:{allocation.operation_id}"}
        )
        assert accepted.status_code == 200, accepted.text


async def test_unsupported_routes_and_prompt_fields_do_not_reach_services(control_case):
    app, enrollment, _ = control_case
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://control.invalid") as client:
        for path in ["/v1/messages", "/api/v1/admin", "/control/v1/finish?x=1", "/control/v1/unknown"]:
            result = await client.post(path, json={}, headers={"authorization": "broker"})
            assert result.status_code != 200
        result = await client.post(
            "/control/v1/exchange",
            json={
                "token": enrollment.enrollment_token.get_secret_value(),
                "transport_peer": _PEER,
                "prompt": "sensitive marker must not be reflected",
            },
            headers={"authorization": "broker"},
        )
        assert result.status_code == 400
        assert "sensitive marker" not in result.text


async def test_slow_identity_work_remains_bounded_after_caller_cancellation():
    release = threading.Event()
    entered = []

    def verify(assertion, *, operation_id):
        if assertion == "lifecycle":
            return
        entered.append(assertion)
        release.wait(5)

    app = ControlApplication(verify_identity=verify, ready=lambda: True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://control.invalid") as client:
        tasks = [
            asyncio.create_task(client.post("/control/v1/exchange", json={"token": "x", "transport_peer": "10.0.0.1"}))
            for _ in range(24)
        ]
        try:
            await asyncio.sleep(0.2)
            assert len(entered) <= 8, "identity verification must not create an unbounded synchronous backlog"
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            response = await client.post("/control/v1/exchange", json={"token": "x", "transport_peer": "10.0.0.1"})
            assert response.status_code == 503
            assert len(entered) <= 8
            response = await client.post("/control/v1/ready", json={}, headers={"authorization": "lifecycle"})
            assert response.status_code == 200, "control admission load must not starve the lifecycle lane"
        finally:
            release.set()
            await asyncio.gather(*tasks, return_exceptions=True)


async def test_control_readiness_requires_workload_identity_and_closed_payload(control_case):
    app, _, _ = control_case
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://control.invalid") as client:
        assert (await client.post("/control/v1/ready", json={})).status_code == 401
        response = await client.post("/control/v1/ready", json={}, headers={"authorization": "broker"})
        assert response.json() == {"ready": True}
        assert (
            await client.post("/control/v1/ready", json={"extra": True}, headers={"authorization": "broker"})
        ).status_code == 400


@pytest.mark.postgres
async def test_control_database_statement_wait_is_bounded():
    from django.db import OperationalError, connection

    from engine.model_access_control.work import ControlWork

    def stalled_database():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_sleep(5)")

    started = asyncio.get_running_loop().time()
    async with asyncio.timeout(3):
        with pytest.raises(OperationalError):
            await ControlWork().run(stalled_database, lifecycle=False, database=True)
    assert asyncio.get_running_loop().time() - started < 2.5
