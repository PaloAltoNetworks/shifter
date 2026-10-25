"""Synchronous work must stay bounded after async callers stop waiting."""

import asyncio
import threading

import pytest

from shared.model_access import ContractError
from shared.model_access.work import BoundedWork


@pytest.mark.asyncio
async def test_cancelled_waiters_cannot_reopen_slots_or_queue_more_work():
    pool = BoundedWork(2, name="synthetic-work")
    release = threading.Event()
    entered = []

    def blocked():
        entered.append(True)
        release.wait(5)

    tasks = [asyncio.create_task(pool.run(blocked)) for _ in range(2)]
    try:
        async with asyncio.timeout(1):
            while len(entered) < 2:
                await asyncio.sleep(0.01)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for _ in range(20):
            with pytest.raises(ContractError, match=r"control\.busy"):
                await pool.run(blocked)
        assert len(entered) == 2
        independent = BoundedWork(1, name="synthetic-lifecycle")
        assert await independent.run(lambda: "available") == "available"
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_failed_work_releases_admission_without_exposing_its_arguments():
    pool = BoundedWork(1, name="synthetic-work")

    def fail():
        raise ValueError("synthetic failure")

    with pytest.raises(ValueError):
        await pool.run(fail)
    assert await pool.run(lambda: "recovered") == "recovered"
