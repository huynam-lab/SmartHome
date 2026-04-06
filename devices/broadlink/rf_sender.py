import os
import json
import time
import base64
from typing import Optional

from core.event_bus import log_event

_PACKET_CACHE = {}


def _decode_packet_content(raw: bytes, packet_path: str) -> Optional[bytes]:
    if not raw:
        return None

    stripped = raw.lstrip()
    if stripped.startswith(b"{"):
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            log_event(
                source="broadlink-rf",
                level="error",
                message="Không parse được JSON RF packet",
                payload={"packet_path": packet_path, "error": repr(exc)},
            )
            return None

        if not isinstance(payload, dict):
            log_event(
                source="broadlink-rf",
                level="error",
                message="RF packet JSON không hợp lệ",
                payload={"packet_path": packet_path},
            )
            return None

        packet_b64 = payload.get("packet_base64")
        packet_hex = payload.get("packet_hex")

        if packet_b64:
            try:
                return base64.b64decode(packet_b64)
            except Exception as exc:
                log_event(
                    source="broadlink-rf",
                    level="error",
                    message="Giải mã packet_base64 thất bại",
                    payload={"packet_path": packet_path, "error": repr(exc)},
                )
                return None

        if packet_hex:
            try:
                return bytes.fromhex(packet_hex)
            except Exception as exc:
                log_event(
                    source="broadlink-rf",
                    level="error",
                    message="Giải mã packet_hex thất bại",
                    payload={"packet_path": packet_path, "error": repr(exc)},
                )
                return None

        log_event(
            source="broadlink-rf",
            level="error",
            message="JSON RF packet thiếu packet_base64 hoặc packet_hex",
            payload={"packet_path": packet_path, "keys": list(payload.keys())},
        )
        return None

    return raw



def load_rf_packet(packet_path: str):
    if not packet_path:
        log_event(source="broadlink-rf", level="error", message="Thiếu packet path khi load RF packet", payload={"packet_path": packet_path})
        return None

    if not os.path.exists(packet_path):
        log_event(
            source="broadlink-rf",
            level="error",
            message="Không tìm thấy file RF packet",
            payload={"packet_path": packet_path},
        )
        return None

    try:
        stat = os.stat(packet_path)
        cache_key = os.path.abspath(packet_path)
        cached = _PACKET_CACHE.get(cache_key)
        if cached and cached["mtime"] == stat.st_mtime and cached["size"] == stat.st_size:
            return cached["data"]

        with open(packet_path, "rb") as f:
            raw = f.read()

        data = _decode_packet_content(raw, packet_path)
        if not data:
            return None

        _PACKET_CACHE[cache_key] = {
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "data": data,
        }
        log_event(
            source="broadlink-rf",
            level="info",
            message="Đọc RF packet thành công",
            payload={"packet_path": packet_path, "packet_size": len(data)},
        )
        return data
    except Exception as exc:
        log_event(
            source="broadlink-rf",
            level="error",
            message="Lỗi khi đọc RF packet",
            payload={"packet_path": packet_path, "error": repr(exc)},
        )
        return None



def send_rf_packet(device, packet_bytes: bytes, repeat: int = 1, delay: float = 0.3):
    if device is None:
        return {"success": False, "message": "Broadlink device là None"}

    if not packet_bytes:
        return {"success": False, "message": "RF packet rỗng"}

    repeat = max(1, int(repeat or 1))
    delay = max(0.0, float(delay or 0.0))

    try:
        for i in range(repeat):
            device.send_data(packet_bytes)
            log_event(
                source="broadlink-rf",
                level="info",
                message="Đã gửi RF packet",
                payload={
                    "attempt": i + 1,
                    "repeat": repeat,
                    "packet_size": len(packet_bytes),
                },
            )
            if i < repeat - 1 and delay > 0:
                time.sleep(delay)

        return {
            "success": True,
            "message": "broadlink.send_data() đã được gọi thành công",
            "repeat": repeat,
            "delay": delay,
        }
    except Exception as exc:
        log_event(
            source="broadlink-rf",
            level="error",
            message="Broadlink send_data lỗi",
            payload={
                "error": repr(exc),
                "packet_size": len(packet_bytes) if packet_bytes else 0,
                "repeat": repeat,
                "delay": delay,
            },
        )
        return {
            "success": False,
            "message": f"Broadlink send_data lỗi: {exc}",
            "error": repr(exc),
        }



def send_rf_packet_from_path(device, packet_path: str, repeat: int = 1, delay: float = 0.3):
    packet_bytes = load_rf_packet(packet_path)
    if not packet_bytes:
        return {
            "success": False,
            "message": "Không load được RF packet từ file",
            "packet_path": packet_path,
        }
    return send_rf_packet(device, packet_bytes, repeat=repeat, delay=delay)
