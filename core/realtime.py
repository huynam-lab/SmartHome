import time

from config import DEBUG_VOICE
from core.event_bus import log_event


socketio = None


def init_socketio(instance):
    global socketio
    socketio = instance


def emit_event(event_name: str, payload: dict):
    if socketio is None:
        log_event(
            source="realtime",
            level="warning",
            message="SocketIO chua duoc khoi tao",
            payload={"event_name": event_name, "payload": payload},
        )
        return False

    try:
        socketio.emit(event_name, payload)
        if DEBUG_VOICE:
            log_event(
                source="realtime",
                level="info",
                message="Emit event thanh cong",
                payload={"event_name": event_name, "payload": payload},
            )
        return True
    except Exception as exc:
        log_event(
            source="realtime",
            level="error",
            message="Emit event that bai",
            payload={"event_name": event_name, "payload": payload, "error": repr(exc)},
        )
        return False


def emit_system_log(message: str, level: str = "info", payload: dict = None):
    return emit_event(
        "system_log",
        {
            "message": message,
            "level": level,
            "payload": payload or {},
            "ts": int(time.time() * 1000),
        },
    )
