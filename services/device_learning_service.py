from __future__ import annotations

import json
import os
import re
import shutil
import unicodedata
from copy import deepcopy
from typing import Any, Dict, List, Tuple

from config import DEVICE_MAP_FILE, ENABLE_DEVICE_MAP_BACKUP, IR_PACKET_DIR, RF_PACKET_DIR
from services.device_template_service import get_device_template


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_key(value: Any) -> str:
    return _normalize_text(value).lower()


def _normalize_control_type(value: Any, fallback: str = "ir") -> str:
    normalized = _normalize_key(value) or _normalize_key(fallback) or "ir"
    if normalized not in {"ir", "rf", "relay", "gpio", "wifi"}:
        raise ValueError("Kiểu tín hiệu không hợp lệ. Chỉ hỗ trợ IR hoặc RF.")
    return normalized


def _normalize_rf_frequency(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    try:
        normalized = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError("Tần số RF phải là 315 hoặc 433.")
    if normalized not in {315, 433}:
        raise ValueError("Tần số RF phải là 315 hoặc 433.")
    return normalized


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


def _normalize_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = _normalize_key(value)
    if normalized in {"1", "true", "on", "enable", "enabled", "yes"}:
        return True
    if normalized in {"0", "false", "off", "disable", "disabled", "no"}:
        return False
    return None


def _normalize_choice_value(value: Any, choices: Dict[str, List[str]], field_label: str) -> str:
    normalized = _normalize_key(value)
    for canonical, aliases in choices.items():
        if normalized == canonical or normalized in aliases:
            return canonical
    raise ValueError(f"{field_label} không hợp lệ: {value}")


def _normalize_semantic_payload(raw_semantic: Any) -> Dict[str, Any]:
    if not isinstance(raw_semantic, dict) or not raw_semantic:
        return {}

    semantic = {str(key): value for key, value in raw_semantic.items() if value not in {None, ""}}
    operation = _normalize_key(semantic.get("operation"))
    domain = _normalize_key(semantic.get("domain"))

    if operation in {"on", "off"}:
        return {
            "domain": domain or "power",
            "operation": operation,
        }

    if operation == "off_after":
        try:
            duration_seconds = int(semantic.get("duration_seconds"))
        except (TypeError, ValueError):
            raise ValueError("duration_seconds phải là số nguyên dương.")
        if duration_seconds <= 0:
            raise ValueError("duration_seconds phải lớn hơn 0.")
        return {
            "domain": domain or "timer",
            "operation": operation,
            "duration_seconds": duration_seconds,
        }

    if operation == "set_temperature":
        try:
            temperature_c = int(semantic.get("temperature_c"))
        except (TypeError, ValueError):
            raise ValueError("temperature_c phải là số nguyên hợp lệ.")
        if temperature_c <= 0:
            raise ValueError("temperature_c phải lớn hơn 0.")
        return {
            "domain": domain or "climate",
            "operation": operation,
            "temperature_c": temperature_c,
        }

    if operation == "set_mode":
        mode = _normalize_choice_value(
            semantic.get("mode"),
            {
                "cool": ["mat", "lam mat"],
                "dry": ["kho", "hut am"],
                "heat": ["nong", "suoi"],
                "fan": ["quat", "gio"],
                "auto": ["tu dong"],
            },
            "mode",
        )
        return {
            "domain": domain or "climate",
            "operation": operation,
            "mode": mode,
        }

    if operation == "set_fan_speed":
        fan_speed = _normalize_choice_value(
            semantic.get("fan_speed"),
            {
                "low": ["thap", "nhe", "yeu", "muc1", "muc_1"],
                "medium": ["trung_binh", "trung binh", "vua", "muc2", "muc_2"],
                "high": ["cao", "manh", "muc3", "muc_3"],
                "auto": ["tu dong"],
                "quiet": ["im", "silent"],
                "turbo": ["manh nhat", "boost"],
            },
            "fan_speed",
        )
        return {
            "domain": domain or "climate",
            "operation": operation,
            "fan_speed": fan_speed,
        }

    if operation == "set_swing":
        swing = _normalize_choice_value(
            semantic.get("swing"),
            {
                "on": ["bat"],
                "off": ["tat"],
                "auto": ["tu dong"],
                "vertical": ["doc"],
                "horizontal": ["ngang"],
            },
            "swing",
        )
        return {
            "domain": domain or "climate",
            "operation": operation,
            "swing": swing,
        }

    if operation == "set_sleep":
        enabled = _normalize_bool(semantic.get("enabled"))
        if enabled is None:
            enabled = _normalize_bool(semantic.get("sleep"))
        if enabled is None:
            raise ValueError("enabled phải là on/off hoặc true/false cho set_sleep.")
        return {
            "domain": domain or "climate",
            "operation": operation,
            "enabled": enabled,
        }

    return semantic


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

    mode_match = re.fullmatch(r"(?:climate[._])?mode[._]([a-z0-9_]+)", normalized_key)
    if mode_match:
        return _normalize_semantic_payload({"operation": "set_mode", "mode": mode_match.group(1)})

    fan_match = re.fullmatch(r"(?:climate[._])?(?:fan|fan_speed)[._]([a-z0-9_]+)", normalized_key)
    if fan_match:
        return _normalize_semantic_payload({"operation": "set_fan_speed", "fan_speed": fan_match.group(1)})

    swing_match = re.fullmatch(r"(?:climate[._])?swing[._]([a-z0-9_]+)", normalized_key)
    if swing_match:
        return _normalize_semantic_payload({"operation": "set_swing", "swing": swing_match.group(1)})

    sleep_match = re.fullmatch(r"(?:climate[._])?sleep[._]([a-z0-9_]+)", normalized_key)
    if sleep_match:
        return _normalize_semantic_payload({"operation": "set_sleep", "enabled": sleep_match.group(1)})

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
    command_type = _normalize_control_type(default_type, fallback="ir")
    payload: Dict[str, Any] = {}

    if isinstance(raw_entry, str):
        payload["file"] = _normalize_text(raw_entry)
    elif isinstance(raw_entry, dict):
        payload = {str(key): value for key, value in raw_entry.items()}
        command_type = _normalize_control_type(payload.get("type") or default_type, fallback=default_type)
    else:
        raise ValueError(f"Mục '{entry_key}' không đúng định dạng.")

    command_type = _normalize_control_type(command_type, fallback=default_type)
    normalized: Dict[str, Any] = {"type": command_type}

    if command_type in {"ir", "rf"}:
        filename = _normalize_text(payload.get("file") or payload.get("filename"))
        expected_extension = ".json" if command_type == "rf" else ".bin"
        if not filename:
            raise ValueError(f"Mục '{entry_key}' cần file {expected_extension} cho điều khiển {command_type.upper()}.")
        if not filename.endswith(expected_extension):
            raise ValueError(f"Mục '{entry_key}' phải dùng file có đuôi {expected_extension}.")
        normalized["file"] = os.path.basename(filename)
        if command_type == "rf":
            rf_frequency = _normalize_rf_frequency(payload.get("rf_frequency") or payload.get("frequency"))
            if rf_frequency is None:
                raise ValueError(f"Mục '{entry_key}' cần chọn tần số RF 315 hoặc 433.")
            normalized["rf_frequency"] = rf_frequency
        phrases = []
        for phrase in _split_phrases(payload.get("phrases")):
            if phrase and phrase not in phrases:
                phrases.append(phrase)
        if phrases:
            normalized["phrases"] = phrases
        label = _normalize_text(payload.get("label"))
        if label:
            normalized["label"] = label
        semantic = _normalize_semantic_payload(payload.get("semantic"))
        if semantic:
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

    control_type = _normalize_control_type(device_payload.get("control_type") or template["control_type"], fallback=template["control_type"])
    rf_frequency = _normalize_rf_frequency(device_payload.get("rf_frequency"))
    if control_type == "rf" and rf_frequency is None and not allow_empty_entries:
        raise ValueError("Thiết bị RF cần chọn tần số 315 hoặc 433.")
    if control_type != "rf":
        rf_frequency = None
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
        "rf_frequency": rf_frequency,
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
        if device_config.get("control_type") != "rf":
            device_config.pop("rf_frequency", None)

    store["devices"][device_config["id"]] = device_config
    save_device_map_store(store, device_map_file=device_map_file)

    return {
        "ok": True,
        "message": "Cập nhật thiết bị thành công" if existing_config else "Lưu thiết bị thành công",
        "device_id": device_config["id"],
        "device": device_config,
        "warnings": warnings,
    }


def _collect_declared_packet_files(device_config: Dict[str, Any]) -> List[Tuple[str, str]]:
    packet_refs: List[Tuple[str, str]] = []
    for section_name in ("actions", "presets"):
        entries = dict((device_config or {}).get(section_name) or {})
        for entry in entries.values():
            if not isinstance(entry, dict):
                continue
            entry_type = _normalize_key(entry.get("type") or device_config.get("control_type"))
            packet_file = os.path.basename(str(entry.get("file") or "").strip())
            if entry_type in {"ir", "rf"} and packet_file:
                packet_refs.append((entry_type, packet_file))
    return packet_refs


def delete_device(
    device_id: str,
    device_map_file: str = DEVICE_MAP_FILE,
    ir_packet_dir: str = IR_PACKET_DIR,
    rf_packet_dir: str = RF_PACKET_DIR,
) -> Dict[str, Any]:
    normalized_device_id = slugify_device_id(device_id)
    if not normalized_device_id:
        raise ValueError("Thiếu device_id hợp lệ để xóa.")

    store, warnings = load_device_map_store(device_map_file)
    devices = dict(store.get("devices") or {})
    device_config = dict(devices.get(normalized_device_id) or {})
    if not device_config:
        raise ValueError(f"Không tìm thấy thiết bị '{normalized_device_id}'.")

    candidate_refs = set(_collect_declared_packet_files(device_config))
    devices.pop(normalized_device_id, None)
    store["devices"] = devices
    save_device_map_store(store, device_map_file=device_map_file)

    referenced_by_others = set()
    for remaining_config in devices.values():
        referenced_by_others.update(_collect_declared_packet_files(dict(remaining_config or {})))

    deleted_files: List[str] = []
    skipped_files: List[str] = []
    missing_files: List[str] = []
    packet_dirs = {"ir": ir_packet_dir, "rf": rf_packet_dir}

    for packet_type, packet_file in sorted(candidate_refs):
        if (packet_type, packet_file) in referenced_by_others:
            skipped_files.append(packet_file)
            continue

        packet_dir = packet_dirs.get(packet_type)
        packet_path = os.path.join(packet_dir, packet_file) if packet_dir else ""
        if not packet_path or not os.path.isfile(packet_path):
            missing_files.append(packet_file)
            continue

        os.remove(packet_path)
        deleted_files.append(packet_file)

    return {
        "ok": True,
        "message": f"Đã xóa thiết bị '{device_config.get('name') or normalized_device_id}'.",
        "device_id": normalized_device_id,
        "device_name": device_config.get("name") or normalized_device_id,
        "deleted_files": deleted_files,
        "skipped_files": skipped_files,
        "missing_files": missing_files,
        "warnings": warnings,
    }


def _resolve_action_alias_for_delete(actions: Dict[str, Any], action_key: str) -> str:
    normalized = _normalize_text(action_key)
    if normalized in actions:
        return normalized

    alias_pairs = {
        "on": "power.on",
        "off": "power.off",
        "turn_on": "power.on",
        "turn_off": "power.off",
        "power.on": "on",
        "power.off": "off",
    }
    mapped = alias_pairs.get(normalized)
    if mapped and mapped in actions:
        return mapped
    return normalized


def delete_device_action(
    device_id: str,
    action_key: str,
    device_map_file: str = DEVICE_MAP_FILE,
    ir_packet_dir: str = IR_PACKET_DIR,
    rf_packet_dir: str = RF_PACKET_DIR,
) -> Dict[str, Any]:
    normalized_device_id = slugify_device_id(device_id)
    if not normalized_device_id:
        raise ValueError("Thiếu device_id hợp lệ để xóa action.")

    store, warnings = load_device_map_store(device_map_file)
    devices = dict(store.get("devices") or {})
    device_config = dict(devices.get(normalized_device_id) or {})
    if not device_config:
        raise ValueError(f"Không tìm thấy thiết bị '{normalized_device_id}'.")

    actions = dict(device_config.get("actions") or {})
    resolved_action_key = _resolve_action_alias_for_delete(actions, action_key)
    if not resolved_action_key or resolved_action_key not in actions:
        raise ValueError(f"Không tìm thấy action '{action_key}' trong thiết bị '{normalized_device_id}'.")

    removed_action = dict(actions.pop(resolved_action_key) or {})
    device_config["actions"] = actions
    devices[normalized_device_id] = device_config
    store["devices"] = devices
    save_device_map_store(store, device_map_file=device_map_file)

    candidate_refs = set()
    removed_type = _normalize_key(removed_action.get("type") or device_config.get("control_type"))
    removed_file = os.path.basename(str(removed_action.get("file") or "").strip())
    if removed_type in {"ir", "rf"} and removed_file:
        candidate_refs.add((removed_type, removed_file))

    referenced_by_others = set()
    for remaining_config in devices.values():
        referenced_by_others.update(_collect_declared_packet_files(dict(remaining_config or {})))

    deleted_files: List[str] = []
    skipped_files: List[str] = []
    missing_files: List[str] = []
    packet_dirs = {"ir": ir_packet_dir, "rf": rf_packet_dir}

    for packet_type, packet_file in sorted(candidate_refs):
        if (packet_type, packet_file) in referenced_by_others:
            skipped_files.append(packet_file)
            continue

        packet_dir = packet_dirs.get(packet_type)
        packet_path = os.path.join(packet_dir, packet_file) if packet_dir else ""
        if not packet_path or not os.path.isfile(packet_path):
            missing_files.append(packet_file)
            continue

        os.remove(packet_path)
        deleted_files.append(packet_file)

    return {
        "ok": True,
        "message": f"Đã xóa action '{resolved_action_key}' khỏi thiết bị '{device_config.get('name') or normalized_device_id}'.",
        "device_id": normalized_device_id,
        "device_name": device_config.get("name") or normalized_device_id,
        "action_key": resolved_action_key,
        "deleted_files": deleted_files,
        "skipped_files": skipped_files,
        "missing_files": missing_files,
        "warnings": warnings,
    }


def update_device_action(
    device_id: str,
    action_key: str,
    action_payload: Dict[str, Any],
    device_map_file: str = DEVICE_MAP_FILE,
) -> Dict[str, Any]:
    normalized_device_id = slugify_device_id(device_id)
    if not normalized_device_id:
        raise ValueError("Thiếu device_id hợp lệ để cập nhật action.")

    store, warnings = load_device_map_store(device_map_file)
    devices = dict(store.get("devices") or {})
    device_config = dict(devices.get(normalized_device_id) or {})
    if not device_config:
        raise ValueError(f"Không tìm thấy thiết bị '{normalized_device_id}'.")

    actions = dict(device_config.get("actions") or {})
    resolved_action_key = _resolve_action_alias_for_delete(actions, action_key)
    if not resolved_action_key or resolved_action_key not in actions:
        raise ValueError(f"Không tìm thấy action '{action_key}' trong thiết bị '{normalized_device_id}'.")

    existing_action = dict(actions.get(resolved_action_key) or {})
    merged_action = {
        **existing_action,
        **dict(action_payload or {}),
        "type": action_payload.get("type") or existing_action.get("type") or device_config.get("control_type"),
        "file": action_payload.get("file") or existing_action.get("file"),
        "rf_frequency": action_payload.get("rf_frequency", existing_action.get("rf_frequency")),
        "phrases": action_payload.get("phrases", existing_action.get("phrases")),
        "semantic": action_payload.get("semantic", existing_action.get("semantic")),
        "label": action_payload.get("label", existing_action.get("label")),
    }

    actions[resolved_action_key] = _normalize_action_record(
        resolved_action_key,
        merged_action,
        default_type=_normalize_control_type(device_config.get("control_type") or "ir", fallback="ir"),
    )
    device_config["actions"] = actions
    devices[normalized_device_id] = device_config
    store["devices"] = devices
    save_device_map_store(store, device_map_file=device_map_file)

    return {
        "ok": True,
        "message": f"Đã cập nhật action '{resolved_action_key}' cho thiết bị '{device_config.get('name') or normalized_device_id}'.",
        "device_id": normalized_device_id,
        "device_name": device_config.get("name") or normalized_device_id,
        "action_key": resolved_action_key,
        "action": actions[resolved_action_key],
        "warnings": warnings,
    }
