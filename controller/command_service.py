import re

from ai.ai_intent import (
    build_chat_reply_with_ai,
    build_wake_reply_with_ai,
)
from ai.intent_parser import normalize_text
from ai.music_intent import parse_music_intent
from ai.semantic_resolver import resolve_device_command
from api.device_api import control_device
from config import EXIT_WORDS, WAKE_WORDS
from core.device_state_store import set_state
from core.event_bus import log_event
from services.music_player import get_music_player
from services.scene_keyword_service import execute_scene_from_text
from speech.tts import speak_text_async

SAFE_AMBIGUOUS_REPLY = "Anh/chị nói rõ giúp em là bật hay tắt thiết bị ạ."


def _dedupe_action_sequence(actions) -> list[str]:
    normalized_actions: list[str] = []
    for raw_action in list(actions or []):
        action = str(raw_action or "").strip().lower()
        if action and action not in normalized_actions:
            normalized_actions.append(action)
    return normalized_actions


def _execute_action_sequence(device: str, actions) -> dict:
    sequence = _dedupe_action_sequence(actions)
    if not device or not sequence:
        return {
            "ok": False,
            "message": "Thiếu device hoặc action để thực thi.",
            "steps": [],
        }

    executed_steps = []
    last_result = None
    for action in sequence:
        step_result = control_device(device=device, action=action)
        executed_steps.append(
            {
                "action": action,
                "ok": bool(step_result.get("ok")),
                "message": step_result.get("message") or "",
                "reply_text": step_result.get("reply_text") or "",
            }
        )
        last_result = step_result
        if not step_result.get("ok"):
            response = dict(step_result)
            response["steps"] = executed_steps
            if len(executed_steps) > 1:
                response["message"] = (
                    step_result.get("message")
                    or f"Thực thi chuỗi lệnh bị lỗi ở bước {action}."
                )
            return response

    response = dict(last_result or {})
    response["steps"] = executed_steps
    return response


def _extract_device_from_user_text(user_text: str, action: str) -> str:
    """Tách cụm thiết bị từ chính câu người dùng để trả lời tự nhiên."""
    if not user_text:
        return ""

    text = " ".join(user_text.strip().split()).lower()
    if not text:
        return ""

    action_words = {
        "on": ["bật", "mo", "mở", "khoi dong", "khởi động"],
        "off": ["tắt", "tat", "dong", "đóng", "ngung", "ngừng"],
    }

    prefix_words = action_words.get(action, [])
    for word in prefix_words:
        if text.startswith(word + " "):
            return text[len(word):].strip(" ,.!?;")

    # Fallback: loại các từ hành động phổ biến rồi ghép lại phần còn lại.
    ignore_words = {
        "bật",
        "tắt",
        "mở",
        "đóng",
        "mo",
        "tat",
        "dong",
        "ngừng",
        "ngung",
        "khởi",
        "động",
        "khoi",
        "dong",
        "giúp",
        "giup",
        "em",
        "với",
        "voi",
        "nhé",
        "nhe",
        "ạ",
        "a",
    }
    parts = [p for p in text.replace(",", " ").split() if p not in ignore_words]
    return " ".join(parts).strip(" ,.!?;")


def build_response(user_text: str, intent: dict, device_name: str = "") -> str:
    """Tạo câu trả lời tự nhiên dựa trên text gốc và intent."""
    action = (intent or {}).get("action")
    action_semantic = str((intent or {}).get("action_semantic") or "").strip().lower()
    if action_semantic in {"on", "off"}:
        action = action_semantic

    if action not in {"on", "off", "power.on", "power.off"}:
        return ""

    action_text = "bật" if action in {"on", "power.on"} else "tắt"

    if device_name:
        return f"Kích hoạt thành công"

    device_from_text = _extract_device_from_user_text(user_text, "on" if action in {"on", "power.on"} else "off")
    if not device_from_text:
        return ""

    return f"Kích hoạt thành công"


def contains_phrase(text: str, phrases) -> bool:
    if not text:
        return False

    text_n = normalize_text(text)
    for phrase in phrases:
        if normalize_text(phrase) in text_n:
            return True
    return False


def is_wake_command(text: str) -> bool:
    return contains_phrase(text, WAKE_WORDS)


def is_exit_command(text: str) -> bool:
    return contains_phrase(text, EXIT_WORDS)


def _strip_wake_words(text: str) -> str:
    if not text:
        return ""

    output = text
    for phrase in WAKE_WORDS:
        pattern = re.compile(rf"\b{re.escape(phrase)}\b", re.IGNORECASE)
        output = pattern.sub(" ", output)

    return " ".join(output.split())


def _build_control_parse_failed_reply(text: str) -> str:
    resolved = resolve_device_command(text)
    if resolved.get("status") == "clarify":
        return resolved.get("message") or SAFE_AMBIGUOUS_REPLY
    return resolved.get("message") or "Em chưa xác định được thiết bị cần điều khiển."


def _build_reply_text(result: dict) -> str:
    intent = result.get("intent") or {}
    device = intent.get("device")
    action = intent.get("action")
    action_semantic = str(intent.get("action_semantic") or "").strip().lower()
    user_text = result.get("text") or ""

    if result.get("should_exit"):
        return "Dạ"

    if result.get("mode") == "scene-keyword":
        return result.get("reply_text") or result.get("message") or "Em đã xử lý scene."

    if result.get("ok") and device and action:
        natural_reply = build_response(
            user_text=user_text,
            intent=intent,
            device_name=result.get("resolved_name") or result.get("device_name") or "",
        )
        if natural_reply:
            return natural_reply
        return result.get("reply_text") or result.get("message") or "Em đã xử lý xong lệnh."

    if result.get("mode") == "control-parse-failed":
        return result.get("message") or "Em chưa xác định được thiết bị cần điều khiển."

    if result.get("mode") == "command-local" and device and action:
        if result.get("ok"):
            normalized_action = action_semantic or action
            action_text = "bật" if normalized_action in {"on", "power.on"} else "tắt" if normalized_action in {"off", "power.off"} else "thực thi"
            device_name = result.get("resolved_name") or device
            return f"Vâng, em đã {action_text} {device_name}." if action_text != "thực thi" else f"Vâng, em đã thực thi lệnh cho {device_name}."
        device_name = result.get("resolved_name") or device
        normalized_action = action_semantic or action
        action_text = "bật" if normalized_action in {"on", "power.on"} else "tắt" if normalized_action in {"off", "power.off"} else "thực thi"
        return f"Em chưa {action_text} được {device_name}. Lý do: {result.get('message') or 'không rõ lỗi'}"

    if result.get("mode") == "music":
        return result.get("reply_text") or result.get("message") or "Em đang xử lý nhạc."

    return result.get("message") or "Em chưa hiểu rõ lệnh, anh/chị nói lại giúp em nhé"


def _handle_music_command(text: str, music_intent: dict, source: str) -> dict:
    player = get_music_player()
    action = (music_intent or {}).get("action")
    value = music_intent.get("value")
    query = music_intent.get("query")

    if action == "play":
        service_result = player.play(query or "")
    elif action == "pause":
        service_result = player.pause()
    elif action == "resume":
        service_result = player.resume()
    elif action == "stop":
        service_result = player.stop()
    elif action == "volume_up":
        service_result = player.volume_up(step=int(value or 10))
    elif action == "volume_down":
        service_result = player.volume_down(step=int(value or 10))
    elif action == "set_volume":
        service_result = player.set_volume(value=int(value or 50))
    elif action == "status":
        status = player.status()
        if status.get("is_running"):
            if status.get("is_playing"):
                reply_text = (
                    f"Hiện đang phát {status.get('title') or status.get('query') or 'nhạc'}. "
                    f"Âm lượng {status.get('volume')} phần trăm."
                )
            elif status.get("paused"):
                reply_text = (
                    f"Nhạc đang tạm dừng ở {status.get('title') or status.get('query') or 'bài hiện tại'}. "
                    f"Âm lượng {status.get('volume')} phần trăm."
                )
            else:
                reply_text = "Hiện player nhạc đang mở nhưng chưa phát."
        else:
            reply_text = "Hiện chưa có nhạc đang phát."
        service_result = {"ok": True, "message": reply_text, "data": status}
    else:
        service_result = {"ok": False, "message": "Em chưa hiểu lệnh nhạc này.", "data": {}}

    output = {
        "ok": bool(service_result.get("ok")),
        "type": "music",
        "action": action,
        "text": text,
        "intent": music_intent,
        "should_exit": False,
        "mode": "music",
        "data": service_result.get("data") or {},
        "message": service_result.get("message") or "Em đang xử lý nhạc.",
        "reply_text": service_result.get("message") or "Em đang xử lý nhạc.",
        "role": "assistant",
    }
    speak_text_async(output["reply_text"])
    _print_conversation_log(text=text, reply_text=output["reply_text"], source=source)
    log_event(
        source=source,
        level="success" if output.get("ok") else "warning",
        message=output["reply_text"],
        payload=output,
    )
    return output


def _print_conversation_log(text: str, reply_text: str, source: str):
    """Giữ lại hook ghi hội thoại nhưng không in ra terminal."""
    return None


def process_text_command(text: str, source: str = "unknown", context: dict | None = None):
    """Xu ly cau lenh text chung cho web/micro Jetson."""
    log_event(source=source, level="info", message="Nhận lệnh", payload={"text": text})

    if not text:
        result = {
            "ok": False,
            "message": "Khong co noi dung lenh",
            "text": text,
            "intent": None,
            "role": "assistant",
        }
        result["reply_text"] = _build_reply_text(result)
        _print_conversation_log(text=text or "(rong)", reply_text=result["reply_text"], source=source)
        log_event(source=source, level="warning", message=result["message"], payload=result)
        return result

    if is_exit_command(text):
        result = {
            "ok": True,
            "message": "Nhan lenh dung chuong trinh",
            "text": text,
            "intent": None,
            "should_exit": True,
            "mode": "exit",
            "role": "assistant",
        }
        result["reply_text"] = _build_reply_text(result)
        speak_text_async(result["reply_text"])
        _print_conversation_log(text=text, reply_text=result["reply_text"], source=source)
        log_event(source=source, level="success", message=result["reply_text"], payload=result)
        return result

    wake_detected = is_wake_command(text)
    if wake_detected:
        cleaned_text = _strip_wake_words(text)
        # Nếu chỉ là wake word, trả lời wake và kết thúc.
        if not cleaned_text:
            wake_reply = build_wake_reply_with_ai()
            result = {
                "ok": True,
                "message": "Đã nhận wake word",
                "text": text,
                "intent": None,
                "should_exit": False,
                "mode": "wake",
                "reply_text": wake_reply,
                "role": "assistant",
            }
            speak_text_async(result["reply_text"])
            _print_conversation_log(text=text, reply_text=result["reply_text"], source=source)
            log_event(source=source, level="info", message=result["reply_text"], payload=result)
            return result
        text = cleaned_text

    music_intent = parse_music_intent(text)
    if music_intent:
        return _handle_music_command(text=text, music_intent=music_intent, source=source)

    scene_result = execute_scene_from_text(text)
    if scene_result:
        scene_result["reply_text"] = _build_reply_text(scene_result)
        speak_text_async(scene_result["reply_text"])
        _print_conversation_log(text=text, reply_text=scene_result["reply_text"], source=source)
        log_event(
            source=source,
            level="success" if scene_result.get("ok") else "warning",
            message=scene_result["reply_text"],
            payload=scene_result,
        )
        return scene_result

    resolution = resolve_device_command(text)
    resolution_status = str(resolution.get("status") or "").strip().lower()
    if resolution_status == "resolved":
        intent = dict(resolution.get("intent") or {})
        action_config = dict((resolution.get("action_config") or {}))
        action_semantic = str((action_config.get("semantic") or {}).get("operation") or "").strip().lower()
        if action_semantic:
            intent["action_semantic"] = action_semantic
        action_sequence = _dedupe_action_sequence(intent.get("action_sequence") or [intent.get("action")])
        intent["action_sequence"] = action_sequence
        result = _execute_action_sequence(device=intent["device"], actions=action_sequence)
        output = {
            "text": text,
            "intent": intent,
            "should_exit": False,
            "mode": "command-local",
            "resolver": resolution,
            "role": "assistant",
            **result,
        }
        if output.get("ok") and output.get("resolved_device") and output.get("state"):
            set_state(device_id=output.get("resolved_device"), state=output.get("state"), source=source)
        output["resolved_name"] = output.get("resolved_name") or output.get("device_name") or output.get("resolved_device") or intent.get("device")
        output["reply_text"] = _build_reply_text(output)
        speak_text_async(output["reply_text"])
        _print_conversation_log(text=text, reply_text=output["reply_text"], source=source)
        log_event(
            source=source,
            level="success" if output.get("ok") else "error",
            message=output["reply_text"],
            payload=output,
        )
        return output

    if resolution_status in {"clarify", "unresolved"}:
        message = resolution.get("message") or _build_control_parse_failed_reply(text)
        output = {
            "ok": False,
            "message": message,
            "text": text,
            "intent": None,
            "should_exit": False,
            "mode": "control-parse-failed",
            "reply_text": message,
            "resolver": resolution,
            "role": "assistant",
        }
        speak_text_async(output["reply_text"])
        _print_conversation_log(text=text, reply_text=output["reply_text"], source=source)
        log_event(source=source, level="warning", message=output["reply_text"], payload=output)
        return output

    chat_reply = build_chat_reply_with_ai(text, context=context)
    output = {
        "ok": True,
        "message": "Xu ly o che do hoi dap",
        "text": text,
        "intent": None,
        "should_exit": False,
        "mode": "chat",
        "reply_text": chat_reply,
        "resolver": resolution,
        "role": "assistant",
    }
    speak_text_async(output["reply_text"])
    _print_conversation_log(text=text, reply_text=output["reply_text"], source=source)
    log_event(source=source, level="info", message=output["reply_text"], payload=output)
    return output
