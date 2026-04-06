import os

from core.event_bus import log_event

_PACKET_CACHE = {}


def load_ir_packet(packet_path: str):
    if not packet_path:
        log_event(source="broadlink-ir", level="error", message="Thiếu packet path khi load IR packet", payload={"packet_path": packet_path})
        return None

    if not os.path.exists(packet_path):
        log_event(
            source="broadlink-ir",
            level="error",
            message="Không tìm thấy file IR packet",
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
            data = f.read()

        _PACKET_CACHE[cache_key] = {
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "data": data,
        }
        log_event(
            source="broadlink-ir",
            level="info",
            message="Đọc IR packet thành công",
            payload={"packet_path": packet_path, "packet_size": len(data)},
        )
        return data
    except Exception as exc:
        log_event(
            source="broadlink-ir",
            level="error",
            message="Lỗi khi đọc IR packet",
            payload={"packet_path": packet_path, "error": repr(exc)},
        )
        return None


def send_ir_packet(device, packet_bytes: bytes):
    if device is None:
        return {"success": False, "message": "Broadlink device là None"}

    if not packet_bytes:
        return {"success": False, "message": "IR packet rỗng"}

    try:
        device.send_data(packet_bytes)
        return {
            "success": True,
            "message": "broadlink.send_data() đã được gọi thành công",
        }
    except Exception as exc:
        log_event(
            source="broadlink-ir",
            level="error",
            message="Broadlink send_data lỗi",
            payload={"error": repr(exc)},
        )
        return {
            "success": False,
            "message": f"Broadlink send_data lỗi: {exc}",
            "error": repr(exc),
        }

