from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from threading import RLock
from time import monotonic
from typing import Any, Hashable


class TtlCache:
    """Small process-local cache with bounded memory and copy-on-read values."""

    def __init__(self, ttl_seconds: int = 60, max_entries: int = 128):
        self.ttl_seconds = max(1, ttl_seconds)
        self.max_entries = max(1, max_entries)
        self._items: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self._lock = RLock()

    def get(self, key: Hashable) -> Any | None:
        now = monotonic()
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at <= now:
                self._items.pop(key, None)
                return None
            self._items.move_to_end(key)
            return deepcopy(value)

    def set(self, key: Hashable, value: Any) -> None:
        with self._lock:
            self._items[key] = (monotonic() + self.ttl_seconds, deepcopy(value))
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
