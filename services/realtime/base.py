from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Dict, Optional, TypeVar

from core.event_bus import log_event
from services.realtime.cache import TTLCache
from services.realtime.types import RealtimeIntent, RealtimeProviderPayload, RealtimeResult

_VN_TIMEZONE = timezone(timedelta(hours=7))
_TIME_FORMAT = "%H:%M ngày %d/%m/%Y"
_JSON_HEADERS = {
    "User-Agent": "smart-home-realtime/1.0",
    "Accept": "application/json,text/plain;q=0.9,*/*;q=0.8",
}
_TEXT_HEADERS = {
    "User-Agent": "smart-home-realtime/1.0",
    "Accept": "application/xml,text/xml,text/plain;q=0.9,*/*;q=0.8",
}
_T = TypeVar("_T")


class BaseRealtimeHandler:
    domain = "unknown"
    cache_ttl_seconds = 30.0

    def __init__(self) -> None:
        self.cache = TTLCache(default_ttl=self.cache_ttl_seconds)
        self.provider_cache = TTLCache(default_ttl=max(self.cache_ttl_seconds, 30.0))

    def handle(self, intent: RealtimeIntent) -> RealtimeResult:
        cache_key = self.build_cache_key(intent)
        cached = self.cache.get(cache_key)
        if cached is not None:
            result = RealtimeResult(**cached)
            result.cache_hit = True
            return result

        result = self._handle(intent)
        if result.status == "success":
            self.cache.set(cache_key, result.to_dict(), ttl=self.cache_ttl_seconds)
        return result

    def _handle(self, intent: RealtimeIntent) -> RealtimeResult:
        raise NotImplementedError

    def build_cache_key(self, intent: RealtimeIntent) -> str:
        entities_key = json.dumps(intent.entities, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return f"{self.domain}:{intent.time_scope}:{entities_key}"

    def _now_text(self) -> str:
        return datetime.now(_VN_TIMEZONE).strftime(_TIME_FORMAT)

    def _format_timestamp(self, value: Any) -> str:
        if value is None:
            return self._now_text()

        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=_VN_TIMEZONE).strftime(_TIME_FORMAT)

        raw = str(value).strip()
        if not raw:
            return self._now_text()

        if raw.isdigit():
            return datetime.fromtimestamp(float(raw), tz=_VN_TIMEZONE).strftime(_TIME_FORMAT)

        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(_VN_TIMEZONE).strftime(_TIME_FORMAT)
        except Exception:
            pass

        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(_VN_TIMEZONE).strftime(_TIME_FORMAT)
        except Exception:
            pass

        return raw

    def _cached_provider_value(self, key: str, fetcher: Callable[[], _T], ttl: float) -> _T:
        cached = self.provider_cache.get(key)
        if cached is not None:
            return cached
        value = fetcher()
        self.provider_cache.set(key, value, ttl=ttl)
        return value

    def _success(self, message: str, data: Dict[str, Any], source: str) -> RealtimeResult:
        result = RealtimeResult(
            ok=True,
            domain=self.domain,
            message=message,
            data=data,
            source=source,
            updated_at=self._now_text(),
            status="success",
        )
        self._log("success", "realtime handler success", {"domain": self.domain, "data": data, "source": source})
        return result

    def _clarify(self, message: str, data: Optional[Dict[str, Any]] = None) -> RealtimeResult:
        result = RealtimeResult(
            ok=False,
            domain=self.domain,
            message=message,
            data=data or {},
            source="internal",
            updated_at="",
            status="clarify",
            should_ask_followup=True,
            followup_question=message,
        )
        self._log("warning", "realtime handler clarify", {"domain": self.domain, "message": message, "data": data or {}})
        return result

    def _unavailable(self, message: str, data: Optional[Dict[str, Any]] = None) -> RealtimeResult:
        result = RealtimeResult(
            ok=False,
            domain=self.domain,
            message=message,
            data=data or {},
            source="internal",
            updated_at="",
            status="unavailable",
        )
        self._log("warning", "realtime handler unavailable", {"domain": self.domain, "message": message, "data": data or {}})
        return result

    def _provider_not_configured(self, intent: RealtimeIntent, hint: str) -> RealtimeProviderPayload:
        return RealtimeProviderPayload(
            ok=False,
            data={"entities": intent.entities, "hint": hint},
            source="internal",
            updated_at="",
            message=hint,
        )

    def _log(self, level: str, message: str, payload: Dict[str, Any]) -> None:
        log_event(source="realtime", level=level, message=message, payload=payload)

    def _http_get_json(self, url: str, timeout: float = 8.0) -> Dict[str, Any]:
        request = urllib.request.Request(url, headers=_JSON_HEADERS)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
        return json.loads(payload)

    def _http_get_text(self, url: str, timeout: float = 8.0) -> str:
        request = urllib.request.Request(url, headers=_TEXT_HEADERS)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", "ignore")
