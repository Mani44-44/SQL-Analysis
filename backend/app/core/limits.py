"""In-process rate limiting and daily LLM cost caps (single instance; see D-004).

Both are keyed by "user:<id>" for signed-in users and "ip:<addr>" for anonymous demo visitors.
A Redis-backed implementation can replace these classes behind the same methods.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime


class RateLimiter:
    """Sliding-window limiter: at most `limit` events per `window_s` seconds per key."""

    def __init__(self, limit: int, window_s: float = 60.0) -> None:
        self.limit = limit
        self.window_s = window_s
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> float | None:
        """Record an event; return None if allowed, else seconds until the next slot."""
        now = time.monotonic()
        with self._lock:
            q = self._events[key]
            while q and now - q[0] >= self.window_s:
                q.popleft()
            if len(q) >= self.limit:
                return max(0.0, self.window_s - (now - q[0]))
            q.append(now)
            return None

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


class CostTracker:
    """Accumulates LLM spend per key per UTC day."""

    def __init__(self) -> None:
        self._spend: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _today() -> str:
        return datetime.now(UTC).date().isoformat()

    def spent(self, key: str) -> float:
        with self._lock:
            day, value = self._spend.get(key, ("", 0.0))
            return value if day == self._today() else 0.0

    def add(self, key: str, cost: float) -> None:
        if cost <= 0:
            return
        with self._lock:
            today = self._today()
            day, value = self._spend.get(key, (today, 0.0))
            self._spend[key] = (today, (value if day == today else 0.0) + cost)

    def reset(self) -> None:
        with self._lock:
            self._spend.clear()


_rate: RateLimiter | None = None
_cost = CostTracker()


def rate_limiter() -> RateLimiter:
    global _rate
    from app.core.config import get_settings

    limit = get_settings().rate_limit_per_min
    if _rate is None or _rate.limit != limit:
        _rate = RateLimiter(limit)
    return _rate


def cost_tracker() -> CostTracker:
    return _cost
