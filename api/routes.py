import os
import json
import secrets
import subprocess
import sys
from functools import wraps
from pathlib import Path

from flask import Blueprint, jsonify, request, session

from api.auth_service import change_user_password, register_user_account, verify_user_credentials
from api.device_api import control_device, list_devices
from config import ALLOW_PUBLIC_REGISTER, CURRENT_JETSON_ID
from controller.command_service import process_text_command
from controller.device_registry import get_registry
from core.device_state_store import build_devices_snapshot, remove_device_state
from core.event_bus import list_events, log_event
from services.device_learning_service import delete_device, delete_device_action, save_empty_device, save_learned_device, update_device_action
from services.device_schedule_service import create_device_schedule, delete_device_schedule, list_device_schedules
from services.device_template_service import get_device_template, list_device_templates

api_bp = Blueprint("api", __name__, url_prefix="/api")
ROOT_DIR = Path(__file__).resolve().parents[1]
IR_LEARN_TIMEOUT_SECONDS = 60
DEVICE_MAP_PATH = ROOT_DIR / "data" / "device_map.json"


def _build_chat_http_response(result):
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


def _extract_request_context(payload):
    safe_payload = payload or {}
    location = safe_payload.get("location") or {}
    try:
        latitude = location.get("latitude")
        longitude = location.get("longitude")
        if latitude is None or longitude is None:
            return {}
        return {
            "location": {
                "name": str(location.get("name") or "").strip(),
                "latitude": float(latitude),
                "longitude": float(longitude),
                "source": str(location.get("source") or "browser").strip().lower() or "browser",
            }
        }
    except Exception:
        return {}


def _build_auth_session_payload():
    return {
        "authenticated": True,
        "email": session.get("auth_email", ""),
        "jetson_id": session.get("jetson_id", ""),
        "current_jetson_id": CURRENT_JETSON_ID,
    }


def _normalize_jetson_id(jetson_id):
    return str(jetson_id or "").strip()


def _is_valid_registration_jetson_id(jetson_id: str) -> bool:
    normalized = _normalize_jetson_id(jetson_id)
    return normalized.upper().startswith("JETSON_") and len(normalized) > len("JETSON_")


def _session_matches_current_jetson() -> bool:
    return _normalize_jetson_id(session.get("jetson_id")) == _normalize_jetson_id(CURRENT_JETSON_ID)


def _reject_wrong_jetson(message: str, status_code: int = 403):
    session.clear()
    return jsonify({
        "ok": False,
        "authenticated": False,
        "message": message,
        "jetson_id": CURRENT_JETSON_ID,
    }), status_code


def require_auth(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("authenticated"):
            return jsonify({
                "ok": False,
                "message": "",
                "authenticated": False,
            }), 401
        if not _session_matches_current_jetson():
            return _reject_wrong_jetson("Mã jetson của bạn không khớp với thiết bị này. Vui lòng đăng nhập lại.")
        return view_func(*args, **kwargs)

    return wrapped


def _validate_command_filename(filename: str, signal_type: str) -> str:
    safe_filename = os.path.basename((filename or "").strip())
    if not safe_filename:
        raise ValueError("Thiếu tên file để lưu lệnh")

    extension = ".json" if signal_type == "rf" else ".bin"
    if not safe_filename.lower().endswith(extension):
        raise ValueError(f"Tên file phải có đuôi {extension}")

    base_name = safe_filename[:-len(extension)].strip()
    if not base_name:
        raise ValueError("Tên file không hợp lệ")

    packet_dir = ROOT_DIR / "data" / ("rf_packets" if signal_type == "rf" else "ir_packets")
    target_path = packet_dir / safe_filename
    if target_path.exists():
        raise ValueError(f"Tên file đã tồn tại: {safe_filename}")

    return safe_filename


def _generate_unique_command_filename(signal_type: str) -> str:
    safe_signal_type = _normalize_signal_type(signal_type)
    if safe_signal_type == "auto":
        safe_signal_type = "ir"

    extension = ".json" if safe_signal_type == "rf" else ".bin"
    packet_dirs = [
        ROOT_DIR / "data" / "ir_packets",
        ROOT_DIR / "data" / "rf_packets",
    ]
    for packet_dir in packet_dirs:
        packet_dir.mkdir(parents=True, exist_ok=True)

    for _ in range(64):
        candidate = f"{safe_signal_type}_{secrets.token_hex(8)}{extension}"
        if not any((packet_dir / candidate).exists() for packet_dir in packet_dirs):
            return candidate

    raise ValueError("Không thể tạo tên file lệnh duy nhất. Hãy thử lại.")


def _normalize_signal_type(signal_type: str) -> str:
    normalized = str(signal_type or "auto").strip().lower()
    if normalized not in {"auto", "ir", "rf"}:
        raise ValueError("signal_type phải là 'auto', 'ir' hoặc 'rf'")
    return normalized


def _normalize_rf_frequency(rf_frequency):
    if rf_frequency in {None, ""}:
        return None
    try:
        value = int(str(rf_frequency).strip())
    except (TypeError, ValueError):
        raise ValueError("rf_frequency phải là 315 hoặc 433")
    if value not in {315, 433}:
        raise ValueError("rf_frequency phải là 315 hoặc 433")
    return value


def run_ir_learn_script(
    filename: str = "",
    device_name: str = "",
    signal_type: str = "ir",
    press_mode: str = "tap",
    rf_frequency=None,
):
    safe_signal_type = _normalize_signal_type(signal_type)
    if safe_signal_type == "auto":
        safe_signal_type = "ir"
    safe_filename = _validate_command_filename(filename, safe_signal_type) if str(filename or "").strip() else _generate_unique_command_filename(safe_signal_type)
    safe_device_name = str(device_name or "").strip()
    safe_rf_frequency = _normalize_rf_frequency(rf_frequency) if safe_signal_type == "rf" else None
    module_name = "devices.broadlink.rf_learn" if safe_signal_type == "rf" else "devices.broadlink.ir_learn"
    mode_label = safe_signal_type.upper()
    command = [
        sys.executable,
        "-m",
        module_name,
        "--filename",
        safe_filename,
    ]
    if safe_signal_type == "rf" and safe_rf_frequency is not None:
        command.extend(["--frequency", str(safe_rf_frequency)])

    try:
        result = subprocess.run(
            command,
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            timeout=IR_LEARN_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        output = (error.stdout or "").strip()
        error_output = (error.stderr or "").strip()
        message = f"Hết thời gian chờ khi học lệnh {mode_label}. Hãy thử lại và bấm remote sớm hơn."
        if error_output:
            message = f"{message} {error_output}"
        return {
            "ok": False,
            "message": message,
            "output": output,
        }
    except Exception as error:
        return {
            "ok": False,
            "message": f"Không thể khởi chạy chế độ học lệnh {mode_label}: {error}",
        }

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    combined_output = "\n".join(part for part in [stdout, stderr] if part).strip()
    log_event(
        source="api-ir-learn",
        level="info" if result.returncode == 0 else "error",
        message=f"{mode_label} learn subprocess finished",
        payload={
            "filename": safe_filename,
            "device_name": safe_device_name,
            "signal_type_requested": safe_signal_type,
            "rf_frequency_requested": safe_rf_frequency,
            "returncode": result.returncode,
            "stdout": stdout,
            "stderr": stderr,
        },
    )

    if result.returncode != 0:
        return {
            "ok": False,
            "message": stderr or stdout or f"Học lệnh {mode_label} thất bại.",
            "output": combined_output,
        }

    return {
        "ok": True,
        "message": f"Học lệnh {mode_label} thành công. Đã lưu vào JetSon {safe_filename}",
        "output": combined_output,
        "filename": safe_filename,
        "device_name": safe_device_name,
        "signal_type": safe_signal_type,
    }


@api_bp.get("/device-templates")
@require_auth
def get_device_templates():
    templates, warnings = list_device_templates()
    if warnings and any(item.get("level") == "error" for item in warnings):
        return jsonify({
            "ok": False,
            "message": warnings[0].get("message") or "Không đọc được device template.",
            "warnings": warnings,
        }), 500

    return jsonify({
        "ok": True,
        "templates": templates,
        "warnings": warnings,
    })


@api_bp.get("/device-templates/<template_id>")
@require_auth
def get_device_template_detail(template_id: str):
    template, warnings = get_device_template(template_id)
    if not template:
        return jsonify({
            "ok": False,
            "message": f"Không tìm thấy template '{template_id}'.",
            "warnings": warnings,
        }), 404

    return jsonify({
        "ok": True,
        "template": template,
        "warnings": warnings,
    })


@api_bp.get("/devices")
@require_auth
def get_devices():
    devices = list_devices()
    build_devices_snapshot(devices)
    return jsonify({"ok": True, "devices": devices})


@api_bp.post("/devices")
@require_auth
def post_devices():
    payload = request.get_json(silent=True) or {}
    template_id = payload.get("template_id")
    device_payload = payload.get("device") or {}

    try:
        result = save_empty_device(
            template_id=str(template_id or "").strip(),
            device_payload=device_payload,
            device_map_file=str(DEVICE_MAP_PATH),
        )
    except ValueError as error:
        return jsonify({
            "ok": False,
            "message": str(error),
        }), 400
    except Exception as error:
        return jsonify({
            "ok": False,
            "message": f"Không thêm được thiết bị: {error}",
        }), 500

    return jsonify(result), 201


@api_bp.delete("/devices/<device_id>")
@require_auth
def delete_device_by_id(device_id: str):
    try:
        result = delete_device(
            device_id=device_id,
            device_map_file=str(DEVICE_MAP_PATH),
        )
    except ValueError as error:
        return jsonify({
            "ok": False,
            "message": str(error),
        }), 404
    except Exception as error:
        return jsonify({
            "ok": False,
            "message": f"Không xóa được thiết bị: {error}",
        }), 500

    remove_device_state(result.get("device_id") or device_id)
    build_devices_snapshot(list_devices())
    return jsonify(result), 200


@api_bp.delete("/devices/<device_id>/actions/<path:action_key>")
@require_auth
def delete_device_action_by_key(device_id: str, action_key: str):
    try:
        result = delete_device_action(
            device_id=device_id,
            action_key=action_key,
            device_map_file=str(DEVICE_MAP_PATH),
        )
    except ValueError as error:
        return jsonify({
            "ok": False,
            "message": str(error),
        }), 404
    except Exception as error:
        return jsonify({
            "ok": False,
            "message": f"Không xóa được action thiết bị: {error}",
        }), 500

    build_devices_snapshot(list_devices())
    return jsonify(result), 200


@api_bp.patch("/devices/<device_id>/actions/<path:action_key>")
@require_auth
def patch_device_action_by_key(device_id: str, action_key: str):
    payload = request.get_json(silent=True) or {}
    action_payload = payload.get("action") or {}

    try:
        result = update_device_action(
            device_id=device_id,
            action_key=action_key,
            action_payload=action_payload,
            device_map_file=str(DEVICE_MAP_PATH),
        )
    except ValueError as error:
        return jsonify({
            "ok": False,
            "message": str(error),
        }), 400
    except Exception as error:
        return jsonify({
            "ok": False,
            "message": f"Không cập nhật được action thiết bị: {error}",
        }), 500

    build_devices_snapshot(list_devices())
    return jsonify(result), 200


@api_bp.get("/devices/<device_id>/schedules")
@require_auth
def get_device_schedules(device_id: str):
    registry = get_registry()
    normalized_device = registry.normalize_device_id(device_id)
    if not registry.get_device(normalized_device):
        return jsonify({
            "ok": False,
            "message": f"Không tìm thấy thiết bị '{device_id}'.",
        }), 404

    schedules = list_device_schedules(normalized_device)
    return jsonify({
        "ok": True,
        "device_id": normalized_device,
        "schedules": schedules,
    }), 200


@api_bp.post("/devices/<device_id>/schedules")
@require_auth
def post_device_schedule(device_id: str):
    payload = request.get_json(silent=True) or {}
    registry = get_registry()
    normalized_device = registry.normalize_device_id(device_id)
    device_config = registry.get_device(normalized_device)
    if not device_config:
        return jsonify({
            "ok": False,
            "message": f"Không tìm thấy thiết bị '{device_id}'.",
        }), 404

    action = str(payload.get("action") or "").strip().lower()
    resolved_action = registry.resolve_action_config(normalized_device, action)
    resolved_action_key = str(resolved_action.get("action") or action).strip().lower()
    if resolved_action_key not in {"on", "off", "power.on", "power.off", "turn_on", "turn_off", "bat", "tat"}:
        return jsonify({
            "ok": False,
            "message": "Lịch hẹn hiện chỉ hỗ trợ bật hoặc tắt thiết bị.",
        }), 400

    if resolved_action_key not in (device_config.get("actions") or {}):
        return jsonify({
            "ok": False,
            "message": f"Thiết bị '{device_config.get('name') or normalized_device}' chưa có action '{resolved_action_key}'.",
        }), 400

    try:
        schedule = create_device_schedule(
            device_id=normalized_device,
            action=resolved_action_key,
            hour=payload.get("hour"),
            minute=payload.get("minute"),
            repeat=payload.get("repeat"),
        )
    except ValueError as error:
        return jsonify({
            "ok": False,
            "message": str(error),
        }), 400

    return jsonify({
        "ok": True,
        "message": "Đã tạo lịch hẹn thiết bị.",
        "schedule": schedule,
    }), 201


@api_bp.delete("/devices/<device_id>/schedules/<schedule_id>")
@require_auth
def delete_device_schedule_by_id(device_id: str, schedule_id: str):
    registry = get_registry()
    normalized_device = registry.normalize_device_id(device_id)
    if not registry.get_device(normalized_device):
        return jsonify({
            "ok": False,
            "message": f"Không tìm thấy thiết bị '{device_id}'.",
        }), 404

    try:
        removed = delete_device_schedule(normalized_device, schedule_id)
    except ValueError as error:
        return jsonify({
            "ok": False,
            "message": str(error),
        }), 404

    return jsonify({
        "ok": True,
        "message": "Đã xóa lịch hẹn thiết bị.",
        "schedule": removed,
    }), 200


@api_bp.get("/auth/status")
def get_auth_status():
    if not session.get("authenticated"):
        return jsonify({
            "ok": True,
            "authenticated": False,
        })

    if not _session_matches_current_jetson():
        return _reject_wrong_jetson("Tai khoan nay khong thuoc Jetson hien tai.")

    return jsonify({
        "ok": True,
        **_build_auth_session_payload(),
    })


@api_bp.post("/auth/login")
def post_auth_login():
    payload = request.get_json(silent=True) or {}
    result = verify_user_credentials(
        email=payload.get("email"),
        password=payload.get("password"),
    )

    if not result.get("ok"):
        return jsonify({
            "ok": False,
            "message": result.get("message") or "Dang nhap that bai.",
        }), int(result.get("status") or 401)

    account_jetson_id = _normalize_jetson_id(result.get("jetson_id"))
    if account_jetson_id != _normalize_jetson_id(CURRENT_JETSON_ID):
        return jsonify({
            "ok": False,
            "message": "Tai khoan nay khong duoc phep truy cap thiet bi nay.",
        }), 403

    session.clear()
    session.permanent = True
    session["authenticated"] = True
    session["auth_email"] = result.get("email", "")
    session["jetson_id"] = result.get("jetson_id", "")

    return jsonify({
        "ok": True,
        "message": "Dang nhap thanh cong.",
        **_build_auth_session_payload(),
    })


@api_bp.post("/auth/register")
def post_auth_register():
    payload = request.get_json(silent=True) or {}
    if not ALLOW_PUBLIC_REGISTER:
        return jsonify({
            "ok": False,
            "message": "",
        }), 403

    requested_jetson_id = _normalize_jetson_id(payload.get("jetson_id"))
    if not _is_valid_registration_jetson_id(requested_jetson_id):
        return jsonify({
            "ok": False,
            "message": "Mã jetson không hợp lệ !",
        }), 400

    result = register_user_account(
        email=payload.get("email"),
        password=payload.get("password"),
        jetson_id=requested_jetson_id,
    )

    if not result.get("ok"):
        return jsonify({
            "ok": False,
            "message": result.get("message") or "Đang ký thất bại.",
        }), int(result.get("status") or 400)

    session.clear()
    session.permanent = True
    session["authenticated"] = True
    session["auth_email"] = result.get("email", "")
    session["jetson_id"] = result.get("jetson_id", "")

    return jsonify({
        "ok": True,
        "message": "Dang ky thanh cong.",
        **_build_auth_session_payload(),
    }), 201


@api_bp.post("/auth/logout")
def post_auth_logout():
    session.clear()
    return jsonify({"ok": True, "authenticated": False})


@api_bp.post("/auth/change-password")
@require_auth
def post_auth_change_password():
    payload = request.get_json(silent=True) or {}
    result = change_user_password(
        email=session.get("auth_email"),
        current_password=payload.get("current_password"),
        new_password=payload.get("new_password"),
    )

    if not result.get("ok"):
        return jsonify({
            "ok": False,
            "message": result.get("message") or "Doi mat khau that bai.",
        }), int(result.get("status") or 400)

    return jsonify({
        "ok": True,
        "message": result.get("message") or "Doi mat khau thanh cong.",
    })


@api_bp.post("/device/control")
@require_auth
def post_device_control():
    payload = request.get_json(silent=True) or {}
    device = payload.get("device") or payload.get("device_id")
    action = payload.get("action")

    result = control_device(device=device, action=action, include_debug=False)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@api_bp.post("/control")
@require_auth
def post_control():
    payload = request.get_json(silent=True) or {}
    device = payload.get("device") or payload.get("device_id")
    action = payload.get("action")

    result = control_device(device=device, action=action, include_debug=False)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@api_bp.post("/voice-command")
@require_auth
def post_voice_command():
    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()

    if not text:
        return jsonify({"ok": False, "message": "Thiếu nội dung giọng nói"}), 400

    result = process_text_command(text, source="web-voice", context=_extract_request_context(payload))
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@api_bp.post("/text-command")
@require_auth
def post_text_command():
    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()

    if not text:
        return jsonify({"ok": False, "message": "Thiếu nội dung lệnh"}), 400

    result = process_text_command(text, source="web-text", context=_extract_request_context(payload))
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@api_bp.post("/chat/send")
@require_auth
def post_chat_send():
    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()

    if not text:
        return jsonify({
            "ok": False,
            "message": "Thiếu nội dung chat",
            "reply_text": "Bạn chưa nhập nội dung để gửi lên Jetson.",
        }), 400

    result = process_text_command(text, source="web-chat", context=_extract_request_context(payload))
    return _build_chat_http_response(result)


@api_bp.get("/events")
@require_auth
def get_events():
    since_id_raw = request.args.get("since_id", "0")
    limit_raw = request.args.get("limit", "100")

    try:
        since_id = int(since_id_raw)
    except Exception:
        since_id = 0

    try:
        limit = int(limit_raw)
    except Exception:
        limit = 100

    events = list_events(since_id=since_id, limit=limit)
    last_id = events[-1]["id"] if events else since_id
    return jsonify({"ok": True, "events": events, "last_id": last_id})


@api_bp.post("/ir/learn")
@require_auth
def post_ir_learn():
    payload = request.get_json(silent=True) or {}
    filename = payload.get("filename") or ""
    device_name = payload.get("device_name") or ""
    signal_type = payload.get("signal_type") or "auto"
    rf_frequency = payload.get("rf_frequency")

    try:
        result = run_ir_learn_script(
            filename,
            device_name=device_name,
            signal_type=signal_type,
            rf_frequency=rf_frequency,
        )
    except ValueError as error:
        result = {
            "ok": False,
            "message": str(error),
        }

    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@api_bp.post("/device-learn/save")
@require_auth
def post_device_learn_save():
    payload = request.get_json(silent=True) or {}
    template_id = payload.get("template_id")
    device_payload = payload.get("device") or {}
    actions_payload = payload.get("actions") or {}
    presets_payload = payload.get("presets") or {}

    try:
        result = save_learned_device(
            template_id=str(template_id or "").strip(),
            device_payload=device_payload,
            actions_payload=actions_payload,
            presets_payload=presets_payload,
            device_map_file=str(DEVICE_MAP_PATH),
        )
    except ValueError as error:
        return jsonify({
            "ok": False,
            "message": str(error),
        }), 400
    except Exception as error:
        return jsonify({
            "ok": False,
            "message": f"Không lưu được thiết bị: {error}",
        }), 500

    return jsonify(result), 200
