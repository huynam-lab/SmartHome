from __future__ import annotations

import json
import os
import re
import shutil
import unicodedata
from copy import deepcopy
from typing import Any, Dict, List, Tuple

from config import DEVICE_MAP_FILE, ENABLE_DEVICE_MAP_BACKUP
from services.device_template_service import get_device_template


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_key(value: Any) -> str:
    return _normalize_text(value).lower()


def _strip_accents(value: str) -> str:
    text = str(value or "").replace("đ", "d").replace("Đ", "D")
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def slugify_device_id(value: Any) -> str:
    text = _strip_accents(_normalize_text(value))
    text = re.sub(r"[^a-zA-Z0-9\s_-]", " ", text)
    text = re.sub(r"[_-]+", " ", text)
    text = re.sub(r"\s+", "_", text.strip().lower())
    return text.strip("_")


def _normalize_alias(alias: Any) -> str:
    text = _normalize_text(alias).lower()
    return re.sub(r"\s+", " ", text)


def _split_aliases(raw_aliases: Any) -> List[str]:
    if isinstance(raw_aliases, list):
        return [_normalize_alias(alias) for alias in raw_aliases if _normalize_alias(alias)]

    if isinstance(raw_aliases, str):
        parts = re.split(r"[,\n]+", raw_aliases)
        return [_normalize_alias(part) for part in parts if _normalize_alias(part)]

    return []


def _split_phrases(raw_phrases: Any) -> List[str]:
    if isinstance(raw_phrases, list):
        return [_normalize_text(item) for item in raw_phrases if _normalize_text(item)]

    if isinstance(raw_phrases, str):
        parts = re.split(r"[\n]+", raw_phrases)
        return [_normalize_text(part) for part in parts if _normalize_text(part)]

    return []


def _infer_action_semantic(entry_key: str) -> Dict[str, Any]:
    normalized_key = _normalize_key(entry_key)
    if normalized_key in {"on", "power.on"}:
        return {"domain": "power", "operation": "on"}
    if normalized_key in {"off", "power.off"}:
        return {"domain": "power", "operation": "off"}

    timer_match = re.fullmatch(r"(?:timer\.)?off_after_(\d+)_min", normalized_key)
    if timer_match:
        minutes = int(timer_match.group(1))
        return {"domain": "timer", "operation": "off_after", "duration_seconds": minutes * 60}

    temp_match = re.fullmatch(r"(?:cool|temp|temperature)[._](\d+)", normalized_key)
    if temp_match:
        return {"domain": "climate", "operation": "set_temperature", "temperature_c": int(temp_match.group(1))}

    return {}


def build_default_aliases(device_id: str, name: str = "", room: str = "") -> List[str]:
    aliases: List[str] = []
    candidates = [
        device_id,
        device_id.replace("_", " "),
        name,
        _strip_accents(name),
        room,
    ]
    for candidate in candidates:
        normalized = _normalize_alias(candidate)
        if normalized and normalized not in aliases:
            aliases.append(normalized)
    return aliases


def _collect_device_match_keys(device_config: Dict[str, Any]) -> List[str]:
    keys: List[str] = []
    candidates = [
        device_config.get("id"),
        device_config.get("name"),
        *(device_config.get("aliases") or []),
    ]
    for candidate in candidates:
        normalized = _normalize_alias(candidate)
        if normalized and normalized not in keys:
            keys.append(normalized)
    return keys


def _find_existing_device_id(
    devices: Dict[str, Any],
    template_id: str,
    device_payload: Dict[str, Any],
) -> str:
    provided_id = slugify_device_id(device_payload.get("id"))
    device_name = _normalize_text(device_payload.get("name"))
    candidate_keys = []
    for candidate in (
        provided_id,
        _normalize_alias(device_name),
        *(_split_aliases(device_payload.get("aliases"))),
    ):
        normalized = _normalize_alias(candidate)
        if normalized and normalized not in candidate_keys:
            candidate_keys.append(normalized)

    if not candidate_keys:
        return ""

    if provided_id and provided_id in devices:
        return provided_id

    for device_id, device_config in devices.items():
        if str((device_config or {}).get("template_id") or "").strip() != template_id:
            continue
        match_keys = _collect_device_match_keys(device_config or {})
        if any(candidate in match_keys for candidate in candidate_keys):
            return device_id

    for device_id, device_config in devices.items():
        match_keys = _collect_device_match_keys(device_config or {})
        if any(candidate in match_keys for candidate in candidate_keys):
            return device_id

    return ""


def _normalize_action_record(entry_key: str, raw_entry: Any, default_type: str) -> Dict[str, Any]:
    command_type = default_type
    payload: Dict[str, Any] = {}

    if isinstance(raw_entry, str):
        payload["file"] = _normalize_text(raw_entry)
    elif isinstance(raw_entry, dict):
        payload = {str(key): value for key, value in raw_entry.items()}
        command_type = _normalize_key(payload.get("type") or default_type) or default_type
    else:
        raise ValueError(f"Mục '{entry_key}' không đúng định dạng.")

    command_type = _normalize_key(command_type) or default_type
    normalized: Dict[str, Any] = {"type": command_type}

    if command_type == "ir":
        filename = _normalize_text(payload.get("file") or payload.get("filename"))
        if not filename:
            raise ValueError(f"Mục '{entry_key}' cần file .bin cho điều khiển IR.")
        if not filename.endswith(".bin"):
            raise ValueError(f"Mục '{entry_key}' phải dùng file có đuôi .bin.")
        normalized["file"] = os.path.basename(filename)
        phrases = []
        for phrase in _split_phrases(payload.get("phrases")):
            if phrase and phrase not in phrases:
                phrases.append(phrase)
        if phrases:
            normalized["phrases"] = phrases
        semantic = payload.get("semantic")
        if isinstance(semantic, dict) and semantic:
            normalized["semantic"] = deepcopy(semantic)
        else:
            inferred_semantic = _infer_action_semantic(entry_key)
            if inferred_semantic:
                normalized["semantic"] = inferred_semantic
    elif command_type in {"relay", "gpio"}:
        pin = payload.get("pin")
        value = payload.get("value")
        if pin in {None, ""}:
            raise ValueError(f"Mục '{entry_key}' cần cấu hình pin.")
        if value in {None, ""}:
            raise ValueError(f"Mục '{entry_key}' cần cấu hình value.")
        normalized["pin"] = pin
        normalized["value"] = value
    else:
        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            normalized["metadata"] = deepcopy(metadata)
        for key, value in payload.items():
            if key not in {"type", "metadata"} and value not in {None, ""}:
                normalized[key] = deepcopy(value)

    return normalized


def normalize_entry_map(raw_entries: Any, default_type: str) -> Dict[str, Dict[str, Any]]:
    entries: Dict[str, Dict[str, Any]] = {}
    for raw_key, raw_entry in dict(raw_entries or {}).items():
        entry_key = _normalize_text(raw_key)
        if not entry_key:
            continue
        entries[entry_key] = _normalize_action_record(entry_key, raw_entry, default_type=default_type)
    return entries


def load_device_map_store(device_map_file: str = DEVICE_MAP_FILE) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    warnings: List[Dict[str, Any]] = []

    if not os.path.exists(device_map_file):
        return {"devices": {}}, warnings

    try:
        with open(device_map_file, "r", encoding="utf-8") as file_obj:
            payload = json.load(file_obj)
    except json.JSONDecodeError as exc:
        return {"devices": {}}, [{
            "level": "error",
            "message": f"device_map.json không hợp lệ: {exc}",
        }]

    if not isinstance(payload, dict):
        return {"devices": {}}, [{
            "level": "error",
            "message": "device_map.json phải là object ở cấp cao nhất.",
        }]

    if "devices" in payload and isinstance(payload.get("devices"), dict):
        return {"devices": dict(payload.get("devices") or {})}, warnings

    # fallback legacy
    return {"devices": dict(payload)}, [{
        "level": "warning",
        "message": "device_map.json đang ở định dạng cũ, hệ thống sẽ tự chuẩn hóa sang key devices.",
    }]


def save_device_map_store(store: Dict[str, Any], device_map_file: str = DEVICE_MAP_FILE) -> None:
    os.makedirs(os.path.dirname(device_map_file), exist_ok=True)
    if ENABLE_DEVICE_MAP_BACKUP and os.path.exists(device_map_file):
        shutil.copyfile(device_map_file, f"{device_map_file}.bak")

    with open(device_map_file, "w", encoding="utf-8") as file_obj:
        json.dump(store, file_obj, ensure_ascii=False, indent=2)
        file_obj.write("\n")


def create_device_from_template(
    template_id: str,
    device_payload: Dict[str, Any],
    actions_payload: Dict[str, Any],
    presets_payload: Dict[str, Any],
    allow_empty_entries: bool = False,
) -> Dict[str, Any]:
    template, warnings = get_device_template(template_id)
    if not template:
        raise ValueError(f"Không tìm thấy template '{template_id}'.")
    if warnings:
        # warnings are non-blocking
        pass

    provided_id = _normalize_text(device_payload.get("id"))
    device_name = _normalize_text(device_payload.get("name"))
    if not device_name:
        raise ValueError("Thiếu tên thiết bị.")

    device_id = slugify_device_id(provided_id or device_name)
    if not device_id:
        raise ValueError("Không tạo được id thiết bị hợp lệ.")

    brand = _normalize_text(device_payload.get("brand"))
    model = _normalize_text(device_payload.get("model"))
    room = slugify_device_id(device_payload.get("room"))
    aliases = []
    for alias in build_default_aliases(device_id, device_name, room) + _split_aliases(device_payload.get("aliases")):
        if alias and alias not in aliases:
            aliases.append(alias)

    control_type = template["control_type"]
    actions = normalize_entry_map(actions_payload, default_type=control_type)
    presets = normalize_entry_map(presets_payload, default_type=control_type)

    structure = template["structure"]
    if structure.get("use_actions") and not actions and not allow_empty_entries:
        raise ValueError("Template này yêu cầu ít nhất một action.")
    if not structure.get("use_actions") and actions:
        raise ValueError("Template này không hỗ trợ actions.")
    if not structure.get("use_presets") and presets:
        raise ValueError("Template này không hỗ trợ presets.")

    return {
        "id": device_id,
        "template_id": template["id"],
        "name": device_name,
        "device_kind": template["device_kind"],
        "control_type": control_type,
        "capabilities": deepcopy(template.get("capabilities") or []),
        "brand": brand or "generic",
        "model": model,
        "room": room,
        "enabled": bool(device_payload.get("enabled", True)),
        "aliases": aliases,
        "state_mode": "optimistic" if control_type == "ir" else "managed",
        "state": deepcopy(template["default_state"]),
        "actions": actions,
        "presets": presets,
    }


def save_empty_device(
    template_id: str,
    device_payload: Dict[str, Any],
    device_map_file: str = DEVICE_MAP_FILE,
) -> Dict[str, Any]:
    store, warnings = load_device_map_store(device_map_file)
    store.setdefault("devices", {})

    existing_device_id = _find_existing_device_id(
        store.get("devices") or {},
        template_id=template_id,
        device_payload=device_payload,
    )
    if existing_device_id:
        raise ValueError(f"Thiết bị '{device_payload.get('name') or existing_device_id}' đã tồn tại.")

    device_config = create_device_from_template(
        template_id=template_id,
        device_payload=device_payload,
        actions_payload={},
        presets_payload={},
        allow_empty_entries=True,
    )
    store["devices"][device_config["id"]] = device_config
    save_device_map_store(store, device_map_file=device_map_file)

    return {
        "ok": True,
        "message": "Thêm thiết bị thành công",
        "device_id": device_config["id"],
        "device": device_config,
        "warnings": warnings,
    }


def save_learned_device(
    template_id: str,
    device_payload: Dict[str, Any],
    actions_payload: Dict[str, Any],
    presets_payload: Dict[str, Any],
    device_map_file: str = DEVICE_MAP_FILE,
) -> Dict[str, Any]:
    store, warnings = load_device_map_store(device_map_file)
    store.setdefault("devices", {})
    existing_device_id = _find_existing_device_id(
        store.get("devices") or {},
        template_id=template_id,
        device_payload=device_payload,
    )

    if existing_device_id:
        device_payload = dict(device_payload or {})
        device_payload["id"] = existing_device_id

    device_config = create_device_from_template(
        template_id=template_id,
        device_payload=device_payload,
        actions_payload=actions_payload,
        presets_payload=presets_payload,
        allow_empty_entries=False,
    )

    existing_config = dict((store.get("devices") or {}).get(device_config["id"]) or {})
    if existing_config:
        merged_aliases: List[str] = []
        for alias in list(existing_config.get("aliases") or []) + list(device_config.get("aliases") or []):
            normalized = _normalize_alias(alias)
            if normalized and normalized not in merged_aliases:
                merged_aliases.append(normalized)

        merged_state = deepcopy(existing_config.get("state") or {})
        merged_state.update(deepcopy(device_config.get("state") or {}))

        merged_actions = deepcopy(existing_config.get("actions") or {})
        merged_actions.update(deepcopy(device_config.get("actions") or {}))

        merged_presets = deepcopy(existing_config.get("presets") or {})
        merged_presets.update(deepcopy(device_config.get("presets") or {}))

        device_config = {
            **existing_config,
            **device_config,
            "id": existing_config.get("id") or device_config["id"],
            "aliases": merged_aliases,
            "state": merged_state,
            "actions": merged_actions,
            "presets": merged_presets,
        }

    store["devices"][device_config["id"]] = device_config
    save_device_map_store(store, device_map_file=device_map_file)

    return {
        "ok": True,
        "message": "Cập nhật thiết bị thành công" if existing_config else "Lưu thiết bị thành công",
        "device_id": device_config["id"],
        "device": device_config,
        "warnings": warnings,
    }
