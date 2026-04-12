import json
import os
import threading
import time

from config import DEVICE_MAP_FILE
from core.event_bus import log_event
from core.realtime import emit_event, emit_system_log


_LOCK = threading.Lock()
_STATE = {}


def _extract_devices(payload):
    if not isinstance(payload, dict):
        return {}
    if isinstance(payload.get("devices"), dict):
        return dict(payload.get("devices") or {})
    return payload


def _normalize_state_value(value):
    if isinstance(value, dict):
        power = value.get("power")
        if power in {"on", "off", "unknown"}:
            return power
        return "unknown"
    if value in {"on", "off", "unknown"}:
        return value
    return "unknown"


def _build_state_entry(device_id: str, state: str = "unknown", source: str = "system", updated_at: int | None = None, metadata: dict | None = None):
    ts = updated_at or int(time.time() * 1000)
    entry = {
        "id": device_id,
        "state": state,
        "updated_at": ts,
        "source": source,
        "state_verified": False,
        "last_command": None,
        "last_command_at": None,
        "last_command_status": None,
        "last_command_message": None,
        "active_action": None,
    }
    if metadata:
        entry.update(metadata)
    return entry


def _load_raw_device_map():
    if not os.path.exists(DEVICE_MAP_FILE):
        return {}

    try:
        with open(DEVICE_MAP_FILE, "r", encoding="utf-8") as file_obj:
            payload = json.load(file_obj)
            return _extract_devices(payload)
    except Exception:
        return {}


def initialize_state(device_map: dict):
    with _LOCK:
        _STATE.clear()
        for device_id, config in (device_map or {}).items():
            _STATE[device_id] = _build_state_entry(
                device_id=device_id,
                state=_normalize_state_value(config.get("state", "unknown")),
                source="bootstrap",
                metadata={
                    "state_verified": config.get("control_type") != "ir",
                    "active_action": None,
                },
            )


def sync_from_device_map(device_map: dict):
    with _LOCK:
        for device_id, config in (device_map or {}).items():
            existing = _STATE.get(device_id, {})
            _STATE[device_id] = _build_state_entry(
                device_id=device_id,
                state=existing.get("state", _normalize_state_value(config.get("state", "unknown"))),
                source=existing.get("source", "bootstrap"),
                updated_at=existing.get("updated_at", int(time.time() * 1000)),
                metadata={
                    "state_verified": existing.get("state_verified", config.get("control_type") != "ir"),
                    "last_command": existing.get("last_command"),
                    "last_command_at": existing.get("last_command_at"),
                    "last_command_status": existing.get("last_command_status"),
                    "last_command_message": existing.get("last_command_message"),
                    "active_action": existing.get("active_action"),
                },
            )


def get_state(device_id: str):
    with _LOCK:
        return dict(_STATE.get(device_id, {})) if device_id in _STATE else None


def get_all_states():
    with _LOCK:
        return {device_id: dict(state) for device_id, state in _STATE.items()}


def set_state(device_id: str, state: str, source: str = "system"):
    payload = {
        "id": device_id,
        "state": state,
        "source": source,
        "ts": int(time.time() * 1000),
        "state_verified": True,
    }

    with _LOCK:
        existing = _STATE.get(device_id, {})
        _STATE[device_id] = _build_state_entry(
            device_id=device_id,
            state=state,
            source=source,
            updated_at=payload["ts"],
            metadata={
                "state_verified": True,
                "last_command": existing.get("last_command"),
                "last_command_at": existing.get("last_command_at"),
                "last_command_status": existing.get("last_command_status"),
                "last_command_message": existing.get("last_command_message"),
                "active_action": existing.get("active_action"),
            },
        )

    log_event(source="device-state", level="info", message="Cap nhat trang thai thiet bi", payload=payload)
    emit_event("device_state_changed", payload)
    return payload


def set_command_status(
    device_id: str,
    command: str,
    command_status: str,
    message: str,
    source: str = "system",
    state: str = "unknown",
    state_verified: bool = False,
):
    ts = int(time.time() * 1000)
    payload = {
        "id": device_id,
        "state": state,
        "source": source,
        "ts": ts,
        "state_verified": state_verified,
        "last_command": command,
        "last_command_at": ts,
        "last_command_status": command_status,
        "last_command_message": message,
        "active_action": command,
    }

    with _LOCK:
        _STATE[device_id] = _build_state_entry(
            device_id=device_id,
            state=state,
            source=source,
            updated_at=ts,
            metadata={
                "state_verified": state_verified,
                "last_command": command,
                "last_command_at": ts,
                "last_command_status": command_status,
                "last_command_message": message,
                "active_action": command,
            },
        )

    log_event(source="device-state", level="info", message="Cap nhat trang thai lenh thiet bi", payload=payload)
    emit_event("device_state_changed", payload)
    return payload


def remove_device_state(device_id: str):
    removed = None
    with _LOCK:
        removed = _STATE.pop(device_id, None)

    if not removed:
        return None

    payload = {
        "id": device_id,
        "removed": True,
        "ts": int(time.time() * 1000),
    }
    log_event(source="device-state", level="info", message="Da xoa trang thai thiet bi", payload=payload)
    emit_event("device_state_changed", payload)
    return payload


def build_devices_snapshot(devices: list):
    snapshot = {
        "devices": devices,
        "ts": int(time.time() * 1000),
    }
    emit_event("devices_snapshot", snapshot)
    emit_system_log(message="Da gui snapshot thiet bi", level="info", payload={"count": len(devices)})
    return snapshot


initialize_state(_load_raw_device_map())
