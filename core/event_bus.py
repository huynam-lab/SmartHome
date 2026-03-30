import threading
import time
from collections import deque
from itertools import count
from typing import Any, Dict, List, Optional


_MAX_EVENTS = 500
_EVENTS = deque(maxlen=_MAX_EVENTS)
_LOCK = threading.Lock()
_COUNTER = count(1)


def log_event(source: str, message: str, level: str = "info", payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    event = {
        "id": next(_COUNTER),
        "ts": int(time.time() * 1000),
        "source": source,
        "level": level,
        "message": message,
        "payload": payload or {},
    }

    with _LOCK:
        _EVENTS.append(event)

    return event


def list_events(since_id: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
    limit = max(1, min(limit, 200))

    with _LOCK:
        if since_id <= 0:
            data = list(_EVENTS)
        else:
            data = [e for e in _EVENTS if e["id"] > since_id]

    if len(data) > limit:
        return data[-limit:]

    return data
