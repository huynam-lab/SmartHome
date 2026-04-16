from __future__ import annotations

import json
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from config import DEVICE_SCHEDULE_FILE
from core.event_bus import log_event


_LOCK = threading.Lock()
_MAX_SCHEDULES_PER_DEVICE = 2
_TZ = timezone(timedelta(hours=7))


def _now() -> datetime:
    return datetime.now(_TZ)


def _normalize_action_kind(action: Any) -> str:
    normalized = str(action or "").strip().lower()
    if normalized in {"on", "power.on", "turn_on", "bat"}:
        return "power.on"
    if normalized in {"off", "power.off", "turn_off", "tat"}:
        return "power.off"
    raise ValueError("Action lịch hẹn chỉ hỗ trợ bật hoặc tắt.")


def _normalize_hour(value: Any) -> int:
    try:
        normalized = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError("Giờ phải là số từ 0 đến 23.")
    if normalized < 0 or normalized > 23:
        raise ValueError("Giờ phải từ 0 đến 23.")
    return normalized


def _normalize_minute(value: Any) -> int:
    try:
        normalized = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError("Phút phải là số từ 0 đến 59.")
    if normalized < 0 or normalized > 59:
        raise ValueError("Phút phải từ 0 đến 59.")
    return normalized


def _load_store() -> Dict[str, Any]:
    if not os.path.exists(DEVICE_SCHEDULE_FILE):
        return {"schedules": []}

    try:
        with open(DEVICE_SCHEDULE_FILE, "r", encoding="utf-8") as file_obj:
            payload = json.load(file_obj)
    except Exception:
        return {"schedules": []}

    if not isinstance(payload, dict):
        return {"schedules": []}

    schedules = payload.get("schedules")
    return {"schedules": list(schedules) if isinstance(schedules, list) else []}


def _save_store(store: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(DEVICE_SCHEDULE_FILE), exist_ok=True)
    with open(DEVICE_SCHEDULE_FILE, "w", encoding="utf-8") as file_obj:
        json.dump(store, file_obj, ensure_ascii=False, indent=2)
        file_obj.write("\n")


def _build_next_run_at(hour: int, minute: int, now: datetime | None = None) -> str:
    base = now or _now()
    candidate = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= base:
        candidate += timedelta(days=1)
    return candidate.isoformat()


def _serialize_schedule(schedule: Dict[str, Any], now: datetime | None = None) -> Dict[str, Any]:
    current = now or _now()
    payload = dict(schedule)
    action_kind = str(payload.get("action_kind") or "").strip().lower()
    if not action_kind:
        action_kind = _normalize_action_kind(payload.get("action"))
        payload["action_kind"] = action_kind
    payload["time_label"] = f"{int(payload.get('hour', 0)):02d}:{int(payload.get('minute', 0)):02d}"
    payload["action_label"] = "Bật" if action_kind == "power.on" else "Tắt"
    payload["repeat_label"] = "Lặp lại hằng ngày" if payload.get("repeat") else "Một lần"
    next_run_at = str(payload.get("next_run_at") or "").strip()
    if payload.get("repeat"):
        candidate = current.replace(
            hour=int(payload.get("hour", 0)),
            minute=int(payload.get("minute", 0)),
            second=0,
            microsecond=0,
        )
        last_run_key = str(payload.get("last_run_key") or "").strip()
        current_key = current.strftime("%Y-%m-%dT%H:%M")
        if candidate <= current and last_run_key == current_key:
            candidate += timedelta(days=1)
        elif candidate <= current:
            candidate += timedelta(days=1)
        payload["next_run_at"] = candidate.isoformat()
    elif next_run_at:
        payload["next_run_at"] = next_run_at
    return payload


def list_device_schedules(device_id: str) -> List[Dict[str, Any]]:
    normalized_device_id = str(device_id or "").strip().lower()
    if not normalized_device_id:
        return []
    with _LOCK:
        store = _load_store()
        schedules = [
            _serialize_schedule(schedule)
            for schedule in store.get("schedules") or []
            if str(schedule.get("device_id") or "").strip().lower() == normalized_device_id
        ]
    schedules.sort(key=lambda item: (int(item.get("hour", 0)), int(item.get("minute", 0)), str(item.get("id") or "")))
    return schedules


def create_device_schedule(device_id: str, action: Any, hour: Any, minute: Any, repeat: Any = False) -> Dict[str, Any]:
    normalized_device_id = str(device_id or "").strip().lower()
    if not normalized_device_id:
        raise ValueError("Thiếu device_id để tạo lịch hẹn.")

    resolved_action = str(action or "").strip().lower()
    if not resolved_action:
        raise ValueError("Thiếu action để tạo lịch hẹn.")
    normalized_action_kind = _normalize_action_kind(resolved_action)
    normalized_hour = _normalize_hour(hour)
    normalized_minute = _normalize_minute(minute)
    normalized_repeat = bool(repeat)
    current = _now()

    schedule = {
        "id": f"sch_{secrets.token_hex(6)}",
        "device_id": normalized_device_id,
        "action": resolved_action,
        "action_kind": normalized_action_kind,
        "hour": normalized_hour,
        "minute": normalized_minute,
        "repeat": normalized_repeat,
        "created_at": current.isoformat(),
        "last_run_key": "",
        "next_run_at": "" if normalized_repeat else _build_next_run_at(normalized_hour, normalized_minute, now=current),
    }

    with _LOCK:
        store = _load_store()
        store.setdefault("schedules", [])
        current_schedules = [
            item
            for item in store["schedules"]
            if str(item.get("device_id") or "").strip().lower() == normalized_device_id
        ]
        if len(current_schedules) >= _MAX_SCHEDULES_PER_DEVICE:
            raise ValueError("Mỗi thiết bị chỉ được hẹn giờ tối đa 2 lần.")
        store["schedules"].append(schedule)
        _save_store(store)

    payload = _serialize_schedule(schedule, now=current)
    log_event(source="device-schedule", level="info", message="Đã tạo lịch hẹn thiết bị", payload=payload)
    return payload


def delete_device_schedule(device_id: str, schedule_id: str) -> Dict[str, Any]:
    normalized_device_id = str(device_id or "").strip().lower()
    normalized_schedule_id = str(schedule_id or "").strip()
    if not normalized_device_id or not normalized_schedule_id:
        raise ValueError("Thiếu thông tin lịch hẹn cần xóa.")

    with _LOCK:
        store = _load_store()
        schedules = list(store.get("schedules") or [])
        removed = None
        remaining = []
        for schedule in schedules:
            if (
                str(schedule.get("id") or "").strip() == normalized_schedule_id
                and str(schedule.get("device_id") or "").strip().lower() == normalized_device_id
            ):
                removed = dict(schedule)
                continue
            remaining.append(schedule)

        if not removed:
            raise ValueError("Không tìm thấy lịch hẹn cần xóa.")

        store["schedules"] = remaining
        _save_store(store)

    payload = _serialize_schedule(removed)
    log_event(source="device-schedule", level="info", message="Đã xóa lịch hẹn thiết bị", payload=payload)
    return payload


def run_due_device_schedules() -> None:
    current = _now()
    current_key = current.strftime("%Y-%m-%dT%H:%M")

    with _LOCK:
        store = _load_store()
        schedules = list(store.get("schedules") or [])
        remaining: List[Dict[str, Any]] = []
        due_schedules: List[Dict[str, Any]] = []

        for schedule in schedules:
            schedule_device_id = str(schedule.get("device_id") or "").strip().lower()
            if not schedule_device_id:
                continue

            repeat = bool(schedule.get("repeat"))
            schedule_hour = int(schedule.get("hour", -1))
            schedule_minute = int(schedule.get("minute", -1))
            last_run_key = str(schedule.get("last_run_key") or "").strip()

            is_due = False
            if repeat:
                is_due = schedule_hour == current.hour and schedule_minute == current.minute and last_run_key != current_key
            else:
                next_run_at_raw = str(schedule.get("next_run_at") or "").strip()
                try:
                    next_run_at = datetime.fromisoformat(next_run_at_raw) if next_run_at_raw else None
                except Exception:
                    next_run_at = None
                is_due = bool(next_run_at and next_run_at <= current and last_run_key != current_key)

            if is_due:
                due_schedules.append(dict(schedule))
                continue

            remaining.append(schedule)

        store["schedules"] = remaining
        _save_store(store)

    if not due_schedules:
        return

    from api.device_api import control_device

    completed_repeat_schedules: List[Dict[str, Any]] = []
    for schedule in due_schedules:
        result = control_device(device=schedule.get("device_id"), action=schedule.get("action"), include_debug=False)
        schedule_payload = _serialize_schedule(schedule, now=current)
        schedule_payload["result_ok"] = bool(result.get("ok"))
        schedule_payload["result_message"] = result.get("message") or result.get("reply_text") or ""
        log_event(
            source="device-schedule",
            level="success" if result.get("ok") else "error",
            message="Đã chạy lịch hẹn thiết bị" if result.get("ok") else "Lịch hẹn thiết bị chạy thất bại",
            payload=schedule_payload,
        )

        if schedule.get("repeat"):
            schedule["last_run_key"] = current_key
            completed_repeat_schedules.append(schedule)

    if not completed_repeat_schedules:
        return

    with _LOCK:
        store = _load_store()
        store.setdefault("schedules", [])
        for schedule in completed_repeat_schedules:
            store["schedules"].append(schedule)
        _save_store(store)


def start_device_schedule_worker(stop_event: threading.Event, poll_interval_seconds: float = 10.0) -> None:
    log_event(source="device-schedule", level="info", message="Khởi động worker lịch hẹn thiết bị")
    while not stop_event.is_set():
        try:
            run_due_device_schedules()
        except Exception as exc:
            log_event(
                source="device-schedule",
                level="error",
                message="Worker lịch hẹn thiết bị gặp lỗi",
                payload={"error": repr(exc)},
            )
        stop_event.wait(max(2.0, float(poll_interval_seconds or 10.0)))
