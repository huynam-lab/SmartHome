from core.event_bus import log_event
from core.device_command_dispatcher import dispatch_device_command
from controller.device_registry import build_alias_index, get_registry, normalize_device_id
from devices.device_controllers import get_device_controller


def load_device_map() -> dict:
    """Load device map chuẩn hóa từ registry."""
    return get_registry().reload()


def get_packet_file_from_intent(intent: dict):
    packet_info = get_registry().resolve_action_file(intent.get("device"), intent.get("action"))
    return packet_info.get("packet_path") if packet_info.get("packet_exists") else None


def resolve_packet_debug_info(device_id: str, action: str):
    return get_registry().resolve_packet_debug_info(device_id, action)


def list_available_packets():
    return get_registry().list_available_packets()


def get_packet_audit_report():
    return get_registry().build_packet_audit_report()


def _build_controller_queue_key(device: dict, packet_info: dict) -> str:
    action_type = str(packet_info.get("action_type") or device.get("control_type") or "").strip().lower()
    if action_type in {"ir", "rf"}:
        return "broadlink:default"
    if action_type in {"relay", "gpio"}:
        return f"gpio:{str(device.get('id') or '').strip().lower()}"
    if action_type == "wifi":
        return f"wifi:{str(device.get('id') or '').strip().lower()}"
    return f"device:{str(device.get('id') or '').strip().lower()}"


def _build_command_dedupe_key(device_id: str, action: str) -> str:
    return f"{str(device_id or '').strip().lower()}:{str(action or '').strip().lower()}"


def execute_command(command: dict):
    registry = get_registry()
    registry.reload()

    if not command or not isinstance(command, dict):
        result = {
            "success": False,
            "message": "Lenh dieu khien rong hoac khong hop le",
            "device": None,
            "action": None,
            "packet_file": None,
            "packet_path": None,
            "details": {"command": command, "errors": ["invalid_command"]},
        }
        log_event(source="device-control", level="error", message=result["message"], payload=result)
        return result

    requested_device = command.get("device")
    requested_action = str(command.get("action") or "").strip().lower()
    validation = registry.validate_device_action(requested_device, requested_action)
    packet_info = validation.get("packet_info") or {}
    normalized_device = validation.get("normalized_device")
    device = registry.get_device(normalized_device)

    log_event(
        source="device-control",
        level="info",
        message="Nhan lenh dieu khien chuan hoa",
        payload={
            "requested_device": requested_device,
            "normalized_device": normalized_device,
            "action": requested_action,
            "packet_file": packet_info.get("packet_file"),
            "packet_path": packet_info.get("packet_path"),
            "packet_exists": packet_info.get("packet_exists"),
            "packet_size": packet_info.get("packet_size"),
            "errors": validation.get("errors"),
        },
    )

    if not validation.get("valid") or not device:
        result = {
            "success": False,
            "message": "; ".join(validation.get("errors") or ["Lenh dieu khien khong hop le"]),
            "device": normalized_device,
            "action": requested_action,
            "packet_file": packet_info.get("packet_file"),
            "packet_path": packet_info.get("packet_path"),
            "details": {
                "requested_device": requested_device,
                "normalized_device": normalized_device,
                "device_config": validation.get("device_config"),
                "errors": validation.get("errors"),
                "alias_index": build_alias_index(registry.get_device_map()),
            },
        }
        log_event(source="device-control", level="error", message=result["message"], payload=result)
        return result

    if not packet_info.get("packet_exists"):
        result = {
            "success": False,
            "message": "Không tìm thấy file packet được khai báo trong cấu hình thiết bị",
            "device": normalized_device,
            "action": requested_action,
            "packet_file": packet_info.get("packet_file"),
            "packet_path": packet_info.get("packet_path"),
            "details": {
                "requested_device": requested_device,
                "normalized_device": normalized_device,
                "packet_exists": False,
                "packet_size": packet_info.get("packet_size"),
                "device_config": device,
                "errors": validation.get("errors") + ["packet_file_missing_on_disk"],
            },
        }
        log_event(source="device-control", level="error", message=result["message"], payload=result)
        return result

    controller = get_device_controller(packet_info.get("action_type") or device.get("control_type"))
    if controller is None:
        result = {
            "success": False,
            "message": f"Chưa có controller cho loại điều khiển '{packet_info.get('action_type') or device.get('control_type')}'",
            "device": normalized_device,
            "action": requested_action,
            "packet_file": packet_info.get("packet_file"),
            "packet_path": packet_info.get("packet_path"),
            "details": {"device_config": device, "reason": "missing_device_controller"},
        }
        log_event(source="device-control", level="error", message=result["message"], payload=result)
        return result

    execution_result = dispatch_device_command(
        controller_key=_build_controller_queue_key(device=device, packet_info=packet_info),
        dedupe_key=_build_command_dedupe_key(normalized_device, requested_action),
        execute_fn=lambda: controller.execute(device=device, action=requested_action, packet_info=packet_info),
    )
    result = {
        "success": bool(execution_result.get("success")),
        "message": execution_result.get("message") or "Không có message trả về",
        "device": normalized_device,
        "action": requested_action,
        "packet_file": packet_info.get("packet_file"),
        "packet_path": packet_info.get("packet_path"),
        "details": {
            "requested_device": requested_device,
            "normalized_device": normalized_device,
            "device_config": device,
            "packet_exists": packet_info.get("packet_exists"),
            "packet_size": packet_info.get("packet_size"),
            "execution": execution_result.get("details") or {},
        },
    }
    log_event(
        source="device-control",
        level="success" if result["success"] else "error",
        message=result["message"],
        payload=result,
    )
    return result


def execute_intent(intent: dict):
    return execute_command(intent)


__all__ = [
    "build_alias_index",
    "normalize_device_id",
    "load_device_map",
    "get_packet_file_from_intent",
    "resolve_packet_debug_info",
    "list_available_packets",
    "get_packet_audit_report",
    "execute_command",
    "execute_intent",
]
