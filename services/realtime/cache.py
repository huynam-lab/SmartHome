import threading
import time
from typing import Any, Dict, Optional


class TTLCache:
    def __init__(self, default_ttl: float = 30.0) -> None:
        self.default_ttl = max(1.0, float(default_ttl))
        self._lock = threading.Lock()
        self._store: Dict[str, Dict[str, Any]] = {}
        self._clock = time.monotonic

    def get(self, key: str) -> Optional[Any]:
        now = self._clock()
        with self._lock:
            item = self._store.get(key)
            if not item:
                return None
            if now >= item["expires_at"]:
                self._store.pop(key, None)
                return None
            return item.get("value")

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        lifetime = self.default_ttl if ttl is None else max(1.0, float(ttl))
        with self._lock:
            self._store[key] = {
                "value": value,
                "expires_at": self._clock() + lifetime,
            }
