import os
import json
import re
import subprocess
import sys
from functools import wraps
from pathlib import Path

from flask import Blueprint, jsonify, request, session

from api.auth_service import change_user_password, register_user_account, verify_user_credentials
from api.device_api import control_device, list_devices
from config import CURRENT_JETSON_ID
from controller.command_service import process_text_command
from core.device_state_store import build_devices_snapshot
from core.event_bus import list_events, log_event
from services.device_learning_service import save_empty_device, save_learned_device
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
                "message": "Vui long dang nhap de su dung he thong dieu khien.",
                "authenticated": False,
            }), 401
        if not _session_matches_current_jetson():
            return _reject_wrong_jetson("Tai khoan nay khong duoc phep dieu khien Jetson hien tai.")
        return view_func(*args, **kwargs)

    return wrapped


def _validate_ir_filename(filename: str) -> str:
    safe_filename = os.path.basename((filename or "").strip().replace(" ", ""))
    if not safe_filename:
        raise ValueError("Thiếu tên file để lưu lệnh IR")

    if not safe_filename.endswith(".bin"):
        raise ValueError("Tên file phải có đuôi .bin")

    if not re.fullmatch(r"^[A-Za-z0-9]+_[A-Za-z0-9]+_[A-Za-z0-9]+\.bin$", safe_filename, flags=re.IGNORECASE):
        raise ValueError("Tên file chưa đúng định dạng. Hãy dùng dạng <phòng>_<thiết bị>_<hành động>.bin, ví dụ: Ds_ac_on.bin hoặc san_den_on.bin")

    return safe_filename


def _normalize_signal_type(signal_type: str) -> str:
    normalized = str(signal_type or "auto").strip().lower()
    if normalized not in {"auto", "ir", "rf"}:
        raise ValueError("signal_type phải là 'auto', 'ir' hoặc 'rf'")
    return normalized


def run_ir_learn_script(filename: str = "ir_learned.bin", device_name: str = "", signal_type: str = "ir", press_mode: str = "tap"):
    safe_filename = _validate_ir_filename(filename)
    safe_signal_type = _normalize_signal_type(signal_type)
    safe_device_name = str(device_name or "").strip()

    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "devices.broadlink.ir_learn",
                "--filename",
                safe_filename,
            ],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            timeout=IR_LEARN_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        output = (error.stdout or "").strip()
        error_output = (error.stderr or "").strip()
        message = "Hết thời gian chờ khi học lệnh IR. Hãy thử lại và bấm remote sớm hơn."
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
            "message": f"Không thể khởi chạy chế độ học lệnh IR: {error}",
        }

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    combined_output = "\n".join(part for part in [stdout, stderr] if part).strip()
    log_event(
        source="api-ir-learn",
        level="info" if result.returncode == 0 else "error",
        message="IR learn subprocess finished",
        payload={
            "filename": safe_filename,
            "device_name": safe_device_name,
            "signal_type_requested": safe_signal_type,
            "returncode": result.returncode,
            "stdout": stdout,
            "stderr": stderr,
        },
    )

    if result.returncode != 0:
        return {
            "ok": False,
            "message": stderr or stdout or "Học lệnh IR thất bại.",
            "output": combined_output,
        }

    return {
        "ok": True,
        "message": f"Học lệnh thành công. Đã lưu vào JetSon {safe_filename}",
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


@api_bp.get("/auth/status")
def get_auth_status():
    if not session.get("authenticated"):
        return jsonify({
            "ok": True,
            "authenticated": False,
            "current_jetson_id": CURRENT_JETSON_ID,
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
            "message": (
                f"Mã jetson không hợp lệ"  
            ),
            "current_jetson_id": CURRENT_JETSON_ID,
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
    requested_jetson_id = _normalize_jetson_id(payload.get("jetson_id"))
    if requested_jetson_id != _normalize_jetson_id(CURRENT_JETSON_ID):
        return jsonify({
            "ok": False,
            "message": f"Chi duoc dang ky tai khoan cho Jetson {CURRENT_JETSON_ID} tren thiet bi nay.",
            "current_jetson_id": CURRENT_JETSON_ID,
        }), 403

    result = register_user_account(
        email=payload.get("email"),
        password=payload.get("password"),
        jetson_id=requested_jetson_id,
    )

    if not result.get("ok"):
        return jsonify({
            "ok": False,
            "message": result.get("message") or "Dang ky that bai.",
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

    result = control_device(device=device, action=action)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@api_bp.post("/control")
@require_auth
def post_control():
    payload = request.get_json(silent=True) or {}
    device = payload.get("device") or payload.get("device_id")
    action = payload.get("action")

    result = control_device(device=device, action=action)
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

    try:
        result = run_ir_learn_script(filename, device_name=device_name, signal_type=signal_type)
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
