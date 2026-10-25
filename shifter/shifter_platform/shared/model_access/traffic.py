"""Bounded process-local abuse admission, independent of financial authority."""

import time

from shared.model_access import ContractError


class TrafficBudget:
    """Fixed-window load shedding for one event loop, with bounded key cardinality.

    Deployment-wide spend/rate/concurrency enforcement remains in Engine. No
    token, prompt or content fingerprint may be used as a key here.
    """

    def __init__(self, *, per_key: int = 120, total: int = 4096, window: int = 60) -> None:
        self.per_key, self.total, self.window = per_key, total, window
        self.until = 0.0
        self.count = 0
        self.keys: dict[str, int] = {}

    def consume(self, key: str) -> None:
        """Fail closed once a peer/principal or the process exhausts its window."""
        moment = time.monotonic()
        if moment >= self.until:
            self.until = moment + self.window
            self.count = 0
            self.keys.clear()
        count = self.keys.get(key, 0)
        if self.count >= self.total or count >= self.per_key or len(key) > 128:
            raise ContractError("http.rate_limited")
        self.count += 1
        self.keys[key] = count + 1
