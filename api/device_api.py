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
        "actions": actions,
        "aliases": list(config.get("aliases") or []),
        "presets": dict(config.get("presets") or {}),
        "action_labels": {
            action: ACTION_LABELS.get(action, action.replace("_", " ").title())
            for action in actions
        },
    }


def _build_control_reply_text(device_name: str, action: str) -> str:
    if action in {"on", "power.on"}:
        action_text = "bật"
    elif action in {"off", "power.off"}:
        action_text = "tắt"
    elif action == "timer.off_after_1_min":
        action_text = "hẹn tắt sau 1 phút cho"
    else:
        action_text = f"thực thi lệnh {action}"
    target_name = (device_name or "thiết bị").strip()
    return f"Vâng, em đã {action_text} {target_name}."


def list_devices():
    """Tra ve danh sach thiet bi va action co the dieu khien."""
    device_map = load_device_map()
    sync_from_device_map(device_map)
    devices = []

    for device_id, config in device_map.items():
        devices.append(_build_device_response(device_id=device_id, config=config))

    return devices


def control_device(device: str, action: str):
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

    if normalized_action not in (device_config.get("actions") or {}):
        return {
            "ok": False,
            "message": f"Action khong hop le cho {normalized_device}: {normalized_action}",
        }

    execution_result = execute_command({"device": device, "action": normalized_action})
    if execution_result.get("success"):
        canonical_device = normalized_device
        if device_config.get("control_type") == "ir":
            power_state = "on" if normalized_action in {"on", "power.on"} else "off" if normalized_action in {"off", "power.off"} else "unknown"
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
            state_payload = set_state(device_id=normalized_device, state=normalized_action, source="api")
        return {
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
            "intent": {
                "device": device,
                "action": normalized_action,
            },
            "reply_text": (
                _build_control_reply_text(
                    device_name=device_config.get("name") or normalized_device,
                    action=normalized_action,
                )
            ),
            "debug": execution_result.get("details") or resolve_packet_debug_info(device, normalized_action),
            "result": execution_result,
        }

    action_record = dict((device_config.get("actions") or {}).get(normalized_action) or {})
    packet_filename = action_record.get("file")
    if action_record.get("type") == "ir" and not packet_filename:
        return {
            "ok": False,
            "message": f"Chua cau hinh packet cho {normalized_device}:{normalized_action}",
            "device": normalized_device,
            "action": normalized_action,
        }

    return {
        "ok": False,
        "message": execution_result.get("message") or f"Gui lenh that bai cho {normalized_device}:{normalized_action}. Kiem tra Broadlink, packet IR va cau hinh IP/MAC neu co.",
        "device": normalized_device,
        "resolved_name": device_config.get("name") or normalized_device,
        "action": normalized_action,
        "debug": resolve_packet_debug_info(device, normalized_action),
        "result": execution_result,
    }
