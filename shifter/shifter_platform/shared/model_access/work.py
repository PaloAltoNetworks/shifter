"""Bound asynchronous admission to synchronous credential and control work."""

import asyncio
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from shared.model_access import ContractError


class BoundedWork:
    """Keep capacity occupied until the worker finishes, not the caller's timeout."""

    def __init__(self, capacity: int, *, name: str) -> None:
        self.executor = ThreadPoolExecutor(max_workers=capacity, thread_name_prefix=name)
        self.slots = threading.BoundedSemaphore(capacity)

    async def run[Result](self, function: Callable[[], Result]) -> Result:
        if not self.slots.acquire(blocking=False):
            raise ContractError("control.busy")

        def execute() -> Result:
            """Release capacity only after the synchronous work ends."""
            try:
                return function()
            finally:
                self.slots.release()

        try:
            future = asyncio.get_running_loop().run_in_executor(self.executor, execute)
        except BaseException:
            self.slots.release()
            raise

        def finished(completed: asyncio.Future[Result]) -> None:
            """Retrieve failures after cancellation without logging inputs."""
            if not completed.cancelled():
                completed.exception()

        future.add_done_callback(finished)
        return await asyncio.shield(future)
