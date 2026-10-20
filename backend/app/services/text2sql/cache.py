"""Small thread-safe TTL + LRU cache for pipeline answers (in-process; see D-004)."""

from __future__ import annotations

import copy
import threading
import time
from collections import OrderedDict

from app.services.text2sql.models import PipelineResult


class AnswerCache:
    def __init__(self, ttl_s: int = 3600, max_items: int = 512) -> None:
        self.ttl_s = ttl_s
        self.max_items = max_items
        self._data: OrderedDict[str, tuple[float, PipelineResult]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> PipelineResult | None:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            ts, value = item
            if time.monotonic() - ts > self.ttl_s:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return copy.deepcopy(value)

    def set(self, key: str, value: PipelineResult) -> None:
        with self._lock:
            self._data[key] = (time.monotonic(), copy.deepcopy(value))
            self._data.move_to_end(key)
            while len(self._data) > self.max_items:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
