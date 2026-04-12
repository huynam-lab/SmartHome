from controller.device_controller import execute_command, execute_intent, load_device_map, resolve_packet_debug_info
from controller.device_registry import get_registry
from core.device_state_store import get_state, set_command_status, set_state, sync_from_device_map


ACTION_LABELS = {
    "power.on": "Bật",
    "power.off": "Tắt",
    "timer.off_after_1_min": "Hẹn tắt 1 phút",
    "on": "Bật",
    "off": "Tắt",
}


TYPE_LABELS = {
    "light": "Đèn",
    "air_conditioner": "Điều hòa",
    "smart_switch": "Công tắc",
    "ir": "Thiết bị hồng ngoại",
    "relay": "Relay / GPIO",
}


def _derive_power_state(action: str, action_config: dict | None = None) -> str:
    normalized_action = str(action or "").strip().lower()
    semantic = dict((action_config or {}).get("semantic") or {})
    semantic_operation = str(semantic.get("operation") or "").strip().lower()

    if semantic_operation == "on":
        return "on"
    if semantic_operation == "off":
        return "off"

    if normalized_action in {"on", "turn_on", "power.on", "bat"}:
        return "on"
    if normalized_action in {"off", "turn_off", "power.off", "tat"}:
        return "off"
    return "unknown"


def _format_semantic_choice(value: str) -> str:
    labels = {
        "cool": "mát",
        "dry": "khô",
        "heat": "sưởi",
        "fan": "quạt",
        "auto": "tự động",
        "low": "thấp",
        "medium": "trung bình",
        "high": "cao",
        "quiet": "yên lặng",
        "turbo": "turbo",
        "on": "bật",
        "off": "tắt",
        "vertical": "dọc",
        "horizontal": "ngang",
    }
    normalized = str(value or "").strip().lower()
    return labels.get(normalized, normalized.replace("_", " "))


def _build_action_label(action: str, action_config: dict | None = None) -> str:
    config = dict(action_config or {})
    custom_label = str(config.get("label") or "").strip()
    if custom_label:
        return custom_label

    if action in ACTION_LABELS:
        return ACTION_LABELS[action]

    semantic = dict(config.get("semantic") or {})
    operation = str(semantic.get("operation") or "").strip().lower()

    if operation == "set_temperature":
        temperature_c = semantic.get("temperature_c")
        return f"Đặt {temperature_c} độ" if temperature_c not in {None, ""} else "Đặt nhiệt độ"
    if operation == "off_after":
        duration_seconds = semantic.get("duration_seconds")
        try:
            minutes = max(1, int(duration_seconds) // 60)
        except (TypeError, ValueError):
            return "Hẹn tắt"
        return f"Hẹn tắt {minutes} phút"
    if operation == "set_mode":
        return f"Chế độ {_format_semantic_choice(semantic.get('mode'))}".strip()
    if operation == "set_fan_speed":
        return f"Quạt {_format_semantic_choice(semantic.get('fan_speed'))}".strip()
    if operation == "set_swing":
        return f"Đảo gió {_format_semantic_choice(semantic.get('swing'))}".strip()
    if operation == "set_sleep":
        enabled = semantic.get("enabled")
        return "Chế độ ngủ" if enabled else "Tắt chế độ ngủ"

    return action.replace("_", " ").title()


def _build_device_response(device_id: str, config: dict):
    actions_map = dict((config or {}).get("actions") or {})
    actions = list(actions_map.keys())
    display_name = config.get("name") or device_id.replace("_", " ").title()
    device_kind = config.get("device_kind", "unknown")
    control_type = config.get("control_type", "unknown")

    state_entry = get_state(device_id)
    state_entry = state_entry or {}
    device_state = state_entry.get("state", config.get("state", "unknown"))

    return {
        "id": device_id,
        "template_id": config.get("template_id"),
        "name": display_name,
        "type": device_kind,
        "device_kind": device_kind,
        "control_type": control_type,
        "rf_frequency": config.get("rf_frequency"),
        "capabilities": list(config.get("capabilities") or []),
        "type_label": TYPE_LABELS.get(device_kind, device_kind.replace("_", " ").title()),
        "brand": config.get("brand", "unknown"),
        "model": config.get("model", ""),
        "room": config.get("room", ""),
        "state": device_state,
        "state_verified": state_entry.get("state_verified", control_type != "ir"),
        "last_command": state_entry.get("last_command"),
        "last_command_at": state_entry.get("last_command_at"),
        "last_command_status": state_entry.get("last_command_status"),
        "last_command_message": state_entry.get("last_command_message"),
        "active_action": state_entry.get("active_action"),
        "actions": actions,
        "aliases": list(config.get("aliases") or []),
        "presets": dict(config.get("presets") or {}),
        "action_details": {
            action: {
                "type": action_config.get("type"),
                "file": action_config.get("file"),
                "rf_frequency": action_config.get("rf_frequency"),
                "label": action_config.get("label"),
                "phrases": list(action_config.get("phrases") or []),
                "semantic": dict(action_config.get("semantic") or {}),
            }
            for action, action_config in actions_map.items()
        },
        "action_labels": {
            action: _build_action_label(action, actions_map.get(action))
            for action in actions
        },
    }


def _build_control_reply_text(device_name: str, action: str, action_config: dict | None = None) -> str:
    semantic = dict((action_config or {}).get("semantic") or {})
    semantic_operation = str(semantic.get("operation") or "").strip().lower()
    target_name = (device_name or "thiết bị").strip()

    if semantic_operation == "on" or action in {"on", "power.on"}:
        action_text = "bật"
    elif semantic_operation == "off" or action in {"off", "power.off"}:
        action_text = "tắt"
    elif action == "timer.off_after_1_min":
        action_text = "hẹn tắt sau 1 phút cho"
    elif semantic_operation == "set_temperature":
        temperature_c = semantic.get("temperature_c")
        if temperature_c not in {None, ""}:
            return f"Vâng, em đã đặt {target_name} {temperature_c} độ."
        action_text = "đặt nhiệt độ cho"
    elif semantic_operation == "off_after":
        duration_seconds = semantic.get("duration_seconds")
        if duration_seconds == 60:
            return f"Vâng, em đã hẹn tắt {target_name} sau 1 phút."
        action_text = "hẹn tắt cho"
    elif semantic_operation == "set_mode":
        mode = semantic.get("mode")
        return f"Vâng, em đã chuyển {target_name} sang chế độ {_format_semantic_choice(mode)}."
    elif semantic_operation == "set_fan_speed":
        fan_speed = semantic.get("fan_speed")
        return f"Vâng, em đã chỉnh quạt {target_name} sang mức {_format_semantic_choice(fan_speed)}."
    elif semantic_operation == "set_swing":
        swing = semantic.get("swing")
        return f"Vâng, em đã đặt đảo gió {target_name} thành {_format_semantic_choice(swing)}."
    elif semantic_operation == "set_sleep":
        enabled = semantic.get("enabled")
        if enabled in {True, "true", "on", 1}:
            return f"Vâng, em đã bật chế độ ngủ cho {target_name}."
        return f"Vâng, em đã tắt chế độ ngủ cho {target_name}."
    else:
        action_text = f"thực thi lệnh {action}"

    return f"Vâng, em đã {action_text} {target_name}."


def list_devices():
    """Tra ve danh sach thiet bi va action co the dieu khien."""
    device_map = load_device_map()
    sync_from_device_map(device_map)
    devices = []

    for device_id, config in device_map.items():
        devices.append(_build_device_response(device_id=device_id, config=config))

    return devices


def control_device(device: str, action: str, include_debug: bool = False):
    """Thuc thi lenh dieu khien thiet bi."""
    if not device or not action:
        return {
            "ok": False,
            "message": "Thieu device hoac action",
        }

    registry = get_registry()
    device_map = registry.reload()
    normalized_device = registry.normalize_device_id(device)
    device_config = device_map.get(normalized_device)

    if not device_config:
        return {
            "ok": False,
            "message": f"Khong tim thay thiet bi: {device}",
        }

    normalized_action = str(action or "").strip().lower()
    resolved_action_info = registry.resolve_action_config(normalized_device, normalized_action)
    normalized_action = str(resolved_action_info.get("action") or normalized_action).strip().lower()
    action_config = dict(resolved_action_info.get("action_config") or {})

    if normalized_action not in (device_config.get("actions") or {}):
        return {
            "ok": False,
            "message": f"Action khong hop le cho {normalized_device}: {normalized_action}",
        }

    execution_result = execute_command({"device": device, "action": normalized_action})
    if execution_result.get("success"):
        canonical_device = normalized_device
        power_state = _derive_power_state(normalized_action, action_config)
        if device_config.get("control_type") == "ir":
            state_payload = set_command_status(
                device_id=normalized_device,
                command=normalized_action,
                command_status="sent",
                message=f"Da gui lenh {normalized_action} nhung chua xac thuc trang thai thuc te",
                source="api",
                state=power_state,
                state_verified=False,
            )
        else:
            state_payload = set_state(device_id=normalized_device, state=power_state, source="api")
        response_payload = {
            "ok": True,
            "message": execution_result.get("message") or f"Da gui lenh {normalized_action} cho {normalized_device}",
            "device": device,
            "resolved_device": canonical_device,
            "resolved_name": device_config.get("name") or canonical_device,
            "device_name": device_config.get("name") or canonical_device,
            "action": normalized_action,
            "state": state_payload.get("state"),
            "state_verified": state_payload.get("state_verified"),
            "last_command": state_payload.get("last_command"),
            "last_command_at": state_payload.get("last_command_at"),
            "last_command_status": state_payload.get("last_command_status"),
            "last_command_message": state_payload.get("last_command_message"),
            "active_action": state_payload.get("active_action"),
            "intent": {
                "device": device,
                "action": normalized_action,
            },
            "reply_text": (
                _build_control_reply_text(
                    device_name=device_config.get("name") or normalized_device,
                    action=normalized_action,
                    action_config=action_config,
                )
            ),
        }
        if include_debug:
            response_payload["debug"] = execution_result.get("details") or resolve_packet_debug_info(device, normalized_action)
            response_payload["result"] = execution_result
        return response_payload

    action_record = dict((device_config.get("actions") or {}).get(normalized_action) or {})
    packet_filename = action_record.get("file")
    if action_record.get("type") == "ir" and not packet_filename:
        return {
            "ok": False,
            "message": f"Chua cau hinh packet cho {normalized_device}:{normalized_action}",
            "device": normalized_device,
            "action": normalized_action,
        }

    response_payload = {
        "ok": False,
        "message": execution_result.get("message") or f"Gui lenh that bai cho {normalized_device}:{normalized_action}. Kiem tra Broadlink, packet IR va cau hinh IP/MAC neu co.",
        "device": normalized_device,
        "resolved_name": device_config.get("name") or normalized_device,
        "action": normalized_action,
    }
    if include_debug:
        response_payload["debug"] = resolve_packet_debug_info(device, normalized_action)
        response_payload["result"] = execution_result
    return response_payload
