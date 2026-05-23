import json
import os
from typing import Any, Dict, List, Optional

from ai.intent_parser import normalize_text
from api.device_api import control_device
from config import SCENE_KEYWORD_FILE
from controller.device_registry import get_registry
from core.event_bus import log_event


DEFAULT_SCENE_CONFIG: Dict[str, Any] = {
    "scenes": {
        "all_off": {
            "action": "off",
            "description": "Tat toan bo thiet bi khi cau noi co chua mot trong cac cum tu khoa ben duoi.",
            "keywords": ["tat het", "di ve", "di ngu", "di lam"],
            "exclude_device_ids": [],
        },
        "all_on_except_cooling": {
            "action": "on",
            "description": "Bat cac thiet bi sinh hoat, bo qua dieu hoa va quat.",
            "keywords": ["bat het", "den nha roi", "day thoi"],
            "exclude_device_ids": [],
            "exclude_device_kinds": ["air_conditioner", "fan"],
        },
    }
}

_CACHE: Dict[str, Any] = {"mtime": None, "data": None}


def _load_scene_config() -> Dict[str, Any]:
    current_mtime: Optional[float] = None
    try:
        current_mtime = os.path.getmtime(SCENE_KEYWORD_FILE)
    except OSError:
        current_mtime = None

    if _CACHE.get("data") is not None and _CACHE.get("mtime") == current_mtime:
        return dict(_CACHE.get("data") or {})

    payload: Dict[str, Any] = DEFAULT_SCENE_CONFIG
    try:
        with open(SCENE_KEYWORD_FILE, "r", encoding="utf-8") as file_obj:
            raw_payload = json.load(file_obj)
            if isinstance(raw_payload, dict):
                payload = raw_payload
    except Exception as exc:
        log_event(
            source="scene-keyword",
            level="warning",
            message="Khong doc duoc file scene keyword, dung cau hinh mac dinh",
            payload={"file": SCENE_KEYWORD_FILE, "error": repr(exc)},
        )

    _CACHE["mtime"] = current_mtime
    _CACHE["data"] = payload
    return dict(payload)


def _write_scene_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    os.makedirs(os.path.dirname(SCENE_KEYWORD_FILE), exist_ok=True)
    with open(SCENE_KEYWORD_FILE, "w", encoding="utf-8") as file_obj:
        json.dump(payload, file_obj, ensure_ascii=False, indent=2)
        file_obj.write("\n")

    try:
        current_mtime = os.path.getmtime(SCENE_KEYWORD_FILE)
    except OSError:
        current_mtime = None
    _CACHE["mtime"] = current_mtime
    _CACHE["data"] = payload
    return dict(payload)


def _clean_keyword_entries(values: Any) -> List[str]:
    items: List[str] = []
    for raw_item in list(values or []):
        item = str(raw_item or "").strip()
        if item:
            items.append(item)
    return items


def _dedupe_keywords_preserve_original(values: Any) -> List[str]:
    deduped: List[str] = []
    seen_normalized = set()
    for item in _clean_keyword_entries(values):
        normalized_item = normalize_text(item)
        if not normalized_item or normalized_item in seen_normalized:
            continue
        seen_normalized.add(normalized_item)
        deduped.append(item)
    return deduped


def _normalize_scene(scene_name: str, scene_payload: Any) -> Dict[str, Any]:
    config = dict(scene_payload or {})
    keywords = _dedupe_keywords_preserve_original(config.get("keywords") or [])
    normalized_keywords = [normalize_text(item) for item in keywords if normalize_text(item)]
    exclude_device_ids = [
        str(item or "").strip().lower()
        for item in list(config.get("exclude_device_ids") or [])
        if str(item or "").strip()
    ]
    exclude_device_kinds = [
        str(item or "").strip().lower()
        for item in list(config.get("exclude_device_kinds") or [])
        if str(item or "").strip()
    ]
    return {
        "name": scene_name,
        "action": str(config.get("action") or "").strip().lower(),
        "description": str(config.get("description") or "").strip(),
        "keywords": keywords,
        "normalized_keywords": normalized_keywords,
        "exclude_device_ids": exclude_device_ids,
        "exclude_device_kinds": exclude_device_kinds,
    }


def _validate_scene_config(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Cấu hình ngữ cảnh phải là object JSON.")

    raw_scenes = payload.get("scenes")
    if not isinstance(raw_scenes, dict) or not raw_scenes:
        raise ValueError("Cấu hình ngữ cảnh phải có trường 'scenes' dạng object và không được rỗng.")

    normalized_scenes: Dict[str, Any] = {}
    for raw_scene_name, raw_scene_payload in raw_scenes.items():
        scene_name = str(raw_scene_name or "").strip()
        if not scene_name:
            raise ValueError("Tên ngữ cảnh không được để trống.")

        scene = _normalize_scene(scene_name, raw_scene_payload)
        if scene["action"] not in {"on", "off"}:
            raise ValueError(f"Ngữ cảnh '{scene_name}' chỉ hỗ trợ action 'on' hoặc 'off'.")
        if not scene["keywords"]:
            raise ValueError(f"Ngữ cảnh '{scene_name}' phải có ít nhất 1 từ khóa.")

        normalized_scenes[scene_name] = {
            "action": scene["action"],
            "description": scene["description"],
            "keywords": list(scene["keywords"]),
            "exclude_device_ids": list(dict.fromkeys(scene["exclude_device_ids"])),
            "exclude_device_kinds": list(dict.fromkeys(scene["exclude_device_kinds"])),
        }

    return {"scenes": normalized_scenes}


def get_scene_keyword_config() -> Dict[str, Any]:
    return _validate_scene_config(_load_scene_config())


def save_scene_keyword_config(payload: Any) -> Dict[str, Any]:
    normalized_payload = _validate_scene_config(payload)
    return _write_scene_config(normalized_payload)


def _find_matching_scene(text: str) -> Optional[Dict[str, Any]]:
    text_n = normalize_text(text)
    if not text_n:
        return None

    config = _load_scene_config()
    scenes = dict(config.get("scenes") or {})
    for scene_name, scene_payload in scenes.items():
        scene = _normalize_scene(scene_name, scene_payload)
        if scene["action"] not in {"on", "off"}:
            continue
        if any(keyword and keyword in text_n for keyword in scene["normalized_keywords"]):
            return scene
    return None


def _resolve_power_action(device_config: Dict[str, Any], target_action: str) -> str:
    actions_map = dict(device_config.get("actions") or {})
    semantic_target = "on" if target_action == "on" else "off"

    for action_key, action_config in actions_map.items():
        semantic = dict((action_config or {}).get("semantic") or {})
        if str(semantic.get("operation") or "").strip().lower() == semantic_target:
            return str(action_key or "").strip()

    fallback_candidates = (
        ["power.on", "on", "bat"] if target_action == "on" else ["power.off", "off", "tat"]
    )
    for candidate in fallback_candidates:
        if candidate in actions_map:
            return candidate
    return ""


def _build_scene_targets(scene: Dict[str, Any]) -> List[Dict[str, Any]]:
    registry = get_registry()
    device_map = registry.reload()
    exclude_ids = set(scene.get("exclude_device_ids") or [])
    exclude_kinds = set(scene.get("exclude_device_kinds") or [])
    targets: List[Dict[str, Any]] = []

    for device_id, device_config in device_map.items():
        if not bool(device_config.get("enabled", True)):
            continue
        if str(device_id or "").strip().lower() in exclude_ids:
            continue
        if str(device_config.get("device_kind") or "").strip().lower() in exclude_kinds:
            continue

        action = _resolve_power_action(device_config, str(scene.get("action") or ""))
        if not action:
            continue

        targets.append(
            {
                "device_id": device_id,
                "device_name": device_config.get("name") or device_id,
                "device_kind": device_config.get("device_kind") or "",
                "action": action,
            }
        )
    return targets


def execute_scene_from_text(text: str) -> Optional[Dict[str, Any]]:
    scene = _find_matching_scene(text)
    if not scene:
        return None

    targets = _build_scene_targets(scene)
    if not targets:
        return {
            "ok": False,
            "message": "Khong co thiet bi phu hop de thuc thi scene.",
            "text": text,
            "intent": {
                "scene": scene.get("name"),
                "scene_action": scene.get("action"),
                "matched_keyword": next((
                    raw_keyword
                    for raw_keyword, normalized_keyword in zip(
                        scene.get("keywords") or [],
                        scene.get("normalized_keywords") or [],
                    )
                    if normalized_keyword and normalized_keyword in normalize_text(text)
                ), ""),
                "targets": [],
            },
            "mode": "scene-keyword",
            "role": "assistant",
            "steps": [],
        }

    steps: List[Dict[str, Any]] = []
    success_count = 0
    failure_count = 0

    for target in targets:
        step_result = control_device(device=target["device_id"], action=target["action"])
        step_ok = bool(step_result.get("ok"))
        if step_ok:
            success_count += 1
        else:
            failure_count += 1
        steps.append(
            {
                "device": target["device_id"],
                "device_name": target["device_name"],
                "device_kind": target["device_kind"],
                "action": target["action"],
                "ok": step_ok,
                "message": step_result.get("message") or "",
            }
        )

    action = str(scene.get("action") or "").strip().lower()
    action_text = "bật" if action == "on" else "tắt"
    if success_count and not failure_count:
        message = f"Dạ,Em đã {action_text} {success_count} thiết bị ạ"
    elif success_count and failure_count:
        message = f"Em đã {action_text} {success_count} thiết bị, còn {failure_count} thiết bị chưa xử lý được."
    else:
        message = f"Em chưa {action_text} được thiết bị nào trong scene này."

    matched_keyword = next((
        raw_keyword
        for raw_keyword, normalized_keyword in zip(
            scene.get("keywords") or [],
            scene.get("normalized_keywords") or [],
        )
        if normalized_keyword and normalized_keyword in normalize_text(text)
    ), "")
    result = {
        "ok": success_count > 0,
        "message": message,
        "text": text,
        "intent": {
            "scene": scene.get("name"),
            "scene_action": action,
            "matched_keyword": matched_keyword,
            "targets": [
                {"device": item["device"], "action": item["action"]}
                for item in steps
            ],
        },
        "should_exit": False,
        "mode": "scene-keyword",
        "reply_text": message,
        "role": "assistant",
        "steps": steps,
        "success_count": success_count,
        "failure_count": failure_count,
    }
    log_event(
        source="scene-keyword",
        level="success" if result["ok"] else "warning",
        message=message,
        payload=result,
    )
    return result
