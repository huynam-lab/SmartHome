import threading
import time
from collections import deque
from itertools import count
import json
import sys
from typing import Any, Dict, List, Optional

from config import DEBUG_VOICE


_MAX_EVENTS = 500
_EVENTS = deque(maxlen=_MAX_EVENTS)
_LOCK = threading.Lock()
_COUNTER = count(1)
_NOISY_CONSOLE_SOURCES = {
    "tts",
    "stt",
    "jetson-mic",
    "voice-worker",
    "web-chat",
    "web-voice",
    "web-text",
    "intent-parser",
    "semantic-resolver",
    "gemini",
    "device-state",
    "device-control",
    "rf-controller",
    "broadlink-rf",
    "broadlink-ir",
    "broadlink-discover",
    "device-schedule",
    "realtime",
}
_CONSOLE_SOURCE_ALIAS = {
    "tts": "speaker",
    "music-player": "speaker",
    "stt": "mic",
    "jetson-mic": "mic",
    "voice-worker": "mic",
    "broadlink-rf": "broadlink",
    "broadlink-ir": "broadlink",
    "broadlink-discover": "broadlink",
    "rf-controller": "broadlink",
    "device-control": "broadlink",
    "device-state": "device",
    "device-schedule": "schedule",
}
_REDACTED_PAYLOAD_KEYS = {
    "text",
    "reply_text",
    "message",
    "stdout",
    "stderr",
    "accumulated_text",
    "last_tts_text",
}


def _summarize_console_value(value: Any) -> Any:
    if isinstance(value, str):
        compact = " ".join(value.split())
        if len(compact) > 96:
            compact = f"{compact[:93]}..."
        return compact
    if isinstance(value, dict):
        return {str(k): _summarize_console_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_summarize_console_value(item) for item in value[:8]]
    return value


def _sanitize_console_payload(event: Dict[str, Any]) -> Dict[str, Any]:
    payload = event.get("payload") or {}
    if not isinstance(payload, dict):
        return {"payload_type": type(payload).__name__}

    sanitized: Dict[str, Any] = {}
    for key, value in payload.items():
        key_text = str(key)
        if key_text in _REDACTED_PAYLOAD_KEYS and value not in {None, ""}:
            text_value = " ".join(str(value).split())
            sanitized[key_text] = f"<redacted len={len(text_value)}>"
            continue
        sanitized[key_text] = _summarize_console_value(value)
    return sanitized


def _should_print_console_event(event: Dict[str, Any]) -> bool:
    level = str(event.get("level") or "").lower()
    source = str(event.get("source") or "").strip().lower()
    if DEBUG_VOICE:
        return True
    if level in {"error", "warning"}:
        return True
    return source not in _NOISY_CONSOLE_SOURCES and level not in {"info", "success"}


def _should_include_console_payload(event: Dict[str, Any]) -> bool:
    if DEBUG_VOICE:
        return True
    level = str(event.get("level") or "").lower()
    return level in {"error", "warning"}


def _format_console_event(event: Dict[str, Any]) -> str:
    ts = int(event.get("ts") or 0)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts / 1000 if ts else time.time()))
    source = str(event.get("source") or "unknown").strip()
    normalized_source = source.lower()
    level = str(event.get("level") or "info").lower()
    message = str(event.get("message") or "").strip()
    payload = _sanitize_console_payload(event) if _should_include_console_payload(event) else {}

    if not DEBUG_VOICE and level in {"error", "warning"}:
        label = _CONSOLE_SOURCE_ALIAS.get(normalized_source, normalized_source or "system")
        return f"[{timestamp}] {label}: false"

    base = f"[{timestamp}] [{level.upper()}] [{source}] {message}"
    if not payload:
        return base

    try:
        payload_text = json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)
    except Exception:
        payload_text = repr(payload)
    return f"{base} | payload={payload_text}"


def _print_console_event(event: Dict[str, Any]) -> None:
    if not _should_print_console_event(event):
        return
    stream = sys.stderr if str(event.get("level") or "").lower() in {"error", "warning"} else sys.stdout
    print(_format_console_event(event), file=stream, flush=True)


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

    _print_console_event(event)
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
