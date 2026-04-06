from __future__ import annotations

from typing import Dict, Optional

from core.event_bus import log_event
from services.realtime.crypto_service import CryptoRealtimeHandler
from services.realtime.fx_service import FXRealtimeHandler
from services.realtime.gold_service import GoldRealtimeHandler
from services.realtime.news_service import NewsRealtimeHandler
from services.realtime.types import RealtimeIntent


class RealtimeRouter:
    def __init__(self) -> None:
        self._handlers: Dict[str, object] = {
            "fx": FXRealtimeHandler(),
            "gold": GoldRealtimeHandler(),
            "crypto": CryptoRealtimeHandler(),
            "news": NewsRealtimeHandler(),
        }

    def handle(self, intent: RealtimeIntent) -> Optional[dict]:
        handler = self._handlers.get(intent.domain)
        if handler is None:
            log_event(
                source="realtime",
                level="warning",
                message="realtime domain not registered",
                payload={"domain": intent.domain, "entities": intent.entities},
            )
            return None

        result = handler.handle(intent)
        payload = result.to_dict()
        payload["intent"] = {
            "domain": intent.domain,
            "raw_text": intent.raw_text,
            "entities": intent.entities,
            "time_scope": intent.time_scope,
            "confidence": intent.confidence,
        }
        return payload


_REALTIME_ROUTER = RealtimeRouter()


def get_realtime_router() -> RealtimeRouter:
    return _REALTIME_ROUTER
