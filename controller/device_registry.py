import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from config import DEVICE_MAP_FILE, IR_PACKET_DIR
from core.event_bus import log_event


DeviceConfig = Dict[str, Any]
DeviceMap = Dict[str, DeviceConfig]


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    level: str = "error"
    device_id: Optional[str] = None
    action: Optional[str] = None
    alias: Optional[str] = None
    packet_file: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "level": self.level,
            "device_id": self.device_id,
            "action": self.action,
            "alias": self.alias,
            "packet_file": self.packet_file,
        }


def _normalize_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _extract_effective_power(state: Any) -> str:
    if isinstance(state, str):
        normalized = _normalize_key(state)
        return normalized if normalized in {"on", "off"} else "unknown"

    if isinstance(state, dict):
        normalized = _normalize_key(state.get("power"))
        return normalized if normalized in {"on", "off"} else "unknown"

    return "unknown"


def _normalize_command_entries(raw_entries: Any, default_type: str) -> Dict[str, Dict[str, Any]]:
    normalized_entries: Dict[str, Dict[str, Any]] = {}
    for raw_key, raw_value in dict(raw_entries or {}).items():
        entry_key = str(raw_key or "").strip()
        if not entry_key:
            continue

        if isinstance(raw_value, str):
            entry_payload = {
                "type": default_type,
                "file": raw_value,
            }
        elif isinstance(raw_value, dict):
            entry_payload = dict(raw_value)
            entry_payload["type"] = _normalize_key(entry_payload.get("type") or default_type) or default_type
            if entry_payload["type"] == "ir" and entry_payload.get("filename") and not entry_payload.get("file"):
                entry_payload["file"] = entry_payload.get("filename")
        else:
            continue

        if entry_payload.get("type") == "ir" and entry_payload.get("file"):
            entry_payload["file"] = str(entry_payload.get("file") or "").strip()
        if isinstance(entry_payload.get("phrases"), list):
            entry_payload["phrases"] = [
                str(item or "").strip()
                for item in entry_payload.get("phrases") or []
                if str(item or "").strip()
            ]
        elif entry_payload.get("phrases"):
            entry_payload["phrases"] = [str(entry_payload.get("phrases") or "").strip()]

        semantic = entry_payload.get("semantic")
        if isinstance(semantic, dict):
            entry_payload["semantic"] = {
                str(key): value
                for key, value in semantic.items()
                if value not in {None, ""}
            }

        normalized_entries[entry_key] = entry_payload
    return normalized_entries


def _resolve_action_alias(action: str, actions_map: Dict[str, Any]) -> str:
    action_key = str(action or "").strip()
    if not action_key:
        return ""

    if action_key in (actions_map or {}):
        return action_key

    alias_pairs = {
        "on": "power.on",
        "off": "power.off",
        "power.on": "on",
        "power.off": "off",
    }
    mapped_key = alias_pairs.get(action_key)
    if mapped_key and mapped_key in (actions_map or {}):
        return mapped_key

    return action_key


def build_alias_index(device_map: DeviceMap) -> Dict[str, str]:
    alias_index: Dict[str, str] = {}
    for device_id, config in (device_map or {}).items():
        canonical_id = _normalize_key(device_id)
        if not canonical_id:
            continue

        alias_index[canonical_id] = canonical_id
        for alias in list((config or {}).get("aliases") or []):
            alias_key = _normalize_key(alias)
            if alias_key:
                alias_index[alias_key] = canonical_id
    return alias_index


def normalize_device_id(device_id: str, device_map: DeviceMap) -> str:
    alias_index = build_alias_index(device_map)
    return alias_index.get(_normalize_key(device_id), _normalize_key(device_id))


class DeviceRegistry:
    def __init__(self, device_map_file: str = DEVICE_MAP_FILE, packet_dir: str = IR_PACKET_DIR):
        self.device_map_file = device_map_file
        self.packet_dir = packet_dir
        self._device_map: DeviceMap = {}
        self._alias_index: Dict[str, str] = {}
        self._load_errors: List[Dict[str, Any]] = []
        self._last_loaded_mtime: Optional[float] = None
        self.reload()

    def reload(self, force: bool = False) -> DeviceMap:
        current_mtime: Optional[float] = None
        try:
            current_mtime = os.path.getmtime(self.device_map_file)
        except OSError:
            current_mtime = None

        if not force and self._device_map and self._last_loaded_mtime == current_mtime:
            return self._device_map

        self._device_map, self._load_errors = self._safe_load_device_map()
        self._alias_index = build_alias_index(self._device_map)
        self._last_loaded_mtime = current_mtime
        return self._device_map

    def get_device_map(self) -> DeviceMap:
        return {device_id: dict(config) for device_id, config in self._device_map.items()}

    def get_alias_index(self) -> Dict[str, str]:
        return dict(self._alias_index)

    def get_load_errors(self) -> List[Dict[str, Any]]:
        return list(self._load_errors)

    def list_devices(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for device_id, config in self._device_map.items():
            items.append(
                {
                    "id": device_id,
                    "template_id": config.get("template_id"),
                    "name": config.get("name") or device_id,
                    "device_kind": config.get("device_kind", "unknown"),
                "control_type": config.get("control_type", "unknown"),
                "capabilities": list(config.get("capabilities") or []),
                "brand": config.get("brand", "unknown"),
                    "model": config.get("model", ""),
                    "room": config.get("room", ""),
                    "enabled": bool(config.get("enabled", True)),
                    "state_mode": config.get("state_mode", "managed"),
                    "state": config.get("state"),
                    "aliases": list(config.get("aliases") or []),
                    "actions": dict(config.get("actions") or {}),
                    "presets": dict(config.get("presets") or {}),
                }
            )
        return items

    def get_device(self, device_id_or_alias: str) -> Optional[Dict[str, Any]]:
        normalized = self.normalize_device_id(device_id_or_alias)
        config = self._device_map.get(normalized)
        if not config:
            return None
        return {"id": normalized, **dict(config)}

    def normalize_device_id(self, device_id_or_alias: str) -> str:
        key = _normalize_key(device_id_or_alias)
        return self._alias_index.get(key, key)

    def resolve_action_config(self, device_id_or_alias: str, action: str) -> Dict[str, Any]:
        normalized_device = self.normalize_device_id(device_id_or_alias)
        device_config = self._device_map.get(normalized_device) or {}
        action_key = _resolve_action_alias(action, device_config.get("actions") or {})
        action_config = dict((device_config.get("actions") or {}).get(action_key) or {})

        return {
            "requested_device": device_id_or_alias,
            "normalized_device": normalized_device,
            "action": action_key,
            "action_config": action_config,
            "control_type": device_config.get("control_type", "unknown"),
            "device_config": dict(device_config),
        }

    def validate_device_action(self, device_id_or_alias: str, action: str) -> Dict[str, Any]:
        errors: List[str] = []
        requested_device = device_id_or_alias
        normalized_device = self.normalize_device_id(device_id_or_alias)
        device_config = self._device_map.get(normalized_device)
        action_key = str(action or "").strip()
        if device_config:
            action_key = _resolve_action_alias(action, device_config.get("actions") or {})

        if not requested_device:
            errors.append("Thiếu device trong intent")
        if not action_key:
            errors.append("Thiếu action trong intent")
        if not device_config:
            errors.append(f"Không tìm thấy cấu hình cho thiết bị '{requested_device}'")
        elif action_key not in (device_config.get("actions") or {}):
            errors.append(f"Action '{action_key}' chưa được cấu hình cho thiết bị '{normalized_device}'")

        packet_info = self.resolve_action_file(device_id_or_alias, action_key)
        action_config = packet_info.get("action_config") or {}
        action_type = _normalize_key(action_config.get("type") or device_config.get("control_type") or "unknown")

        if device_config and action_type == "ir" and not packet_info.get("packet_file"):
            errors.append(f"Thiếu file .bin cho action '{action_key}' của thiết bị '{normalized_device}'")

        return {
            "valid": not errors,
            "requested_device": requested_device,
            "normalized_device": normalized_device,
            "action": action_key,
            "device_config": dict(device_config or {}),
            "packet_info": packet_info,
            "errors": errors,
        }

    def resolve_action_file(self, device_id_or_alias: str, action: str) -> Dict[str, Any]:
        action_info = self.resolve_action_config(device_id_or_alias, action)
        action_config = action_info.get("action_config") or {}
        action_type = _normalize_key(action_config.get("type") or action_info.get("control_type") or "unknown")
        packet_file = str(action_config.get("file") or "").strip() if action_type == "ir" else None
        packet_path = os.path.join(self.packet_dir, packet_file) if packet_file else None
        packet_exists = bool(packet_path and os.path.exists(packet_path))
        packet_size = os.path.getsize(packet_path) if packet_exists and packet_path else 0

        return {
            **action_info,
            "action_type": action_type,
            "packet_file": packet_file,
            "packet_path": packet_path,
            "packet_exists": packet_exists,
            "packet_size": packet_size,
        }

    def resolve_packet_debug_info(self, device_id_or_alias: str, action: str) -> Dict[str, Any]:
        validation = self.validate_device_action(device_id_or_alias, action)
        packet_info = dict(validation.get("packet_info") or {})
        packet_info["requested_device"] = device_id_or_alias
        packet_info["errors"] = list(validation.get("errors") or [])
        return packet_info

    def list_available_packets(self) -> List[Dict[str, Any]]:
        packets: List[Dict[str, Any]] = []
        if not os.path.isdir(self.packet_dir):
            return packets

        for file_name in sorted(os.listdir(self.packet_dir)):
            packet_path = os.path.join(self.packet_dir, file_name)
            if not os.path.isfile(packet_path):
                continue
            packets.append(
                {
                    "file": file_name,
                    "path": packet_path,
                    "size": os.path.getsize(packet_path),
                }
            )
        return packets

    def build_packet_audit_report(self) -> Dict[str, Any]:
        declared_packets: Set[str] = set()
        missing_packets: List[Dict[str, Any]] = []

        for device_id, config in self._device_map.items():
            for action, action_config in dict(config.get("actions") or {}).items():
                if _normalize_key((action_config or {}).get("type")) != "ir":
                    continue

                packet_file = str((action_config or {}).get("file") or "").strip()
                if packet_file:
                    declared_packets.add(packet_file)

                packet_path = os.path.join(self.packet_dir, packet_file) if packet_file else None
                if not packet_file or not packet_path or not os.path.exists(packet_path):
                    missing_packets.append(
                        {
                            "device_id": device_id,
                            "action": action,
                            "packet_file": packet_file,
                            "packet_path": packet_path,
                            "exists": False,
                        }
                    )

        available_packets = self.list_available_packets()
        available_names = {item["file"] for item in available_packets}
        unused_packets = [item for item in available_packets if item["file"] not in declared_packets]

        return {
            "device_map_file": self.device_map_file,
            "packet_dir": self.packet_dir,
            "declared_packet_count": len(declared_packets),
            "available_packet_count": len(available_packets),
            "missing_packets": missing_packets,
            "unused_packets": unused_packets,
            "unknown_declared_packets": sorted(declared_packets - available_names),
            "load_errors": self.get_load_errors(),
        }

    def validate_configuration(self) -> Dict[str, Any]:
        issues: List[ValidationIssue] = []
        seen_aliases: Dict[str, str] = {}
        seen_ids: Set[str] = set()

        if self._load_errors:
            issues.extend(
                ValidationIssue(
                    code="device_map_load_error",
                    message=error.get("message", "Không thể đọc device map"),
                    level=error.get("level", "error"),
                )
                for error in self._load_errors
            )

        for device_id, config in self._device_map.items():
            normalized_id = _normalize_key(device_id)
            if normalized_id in seen_ids:
                issues.append(
                    ValidationIssue(
                        code="duplicate_device_id",
                        message=f"Device id bị trùng: {device_id}",
                        device_id=device_id,
                    )
                )
            seen_ids.add(normalized_id)

            actions = dict(config.get("actions") or {})
            presets = dict(config.get("presets") or {})
            if not actions and not presets:
                issues.append(
                    ValidationIssue(
                        code="missing_commands",
                        message=f"Thiết bị '{device_id}' chưa có actions hoặc presets hợp lệ",
                        device_id=device_id,
                    )
                )

            for action, action_config in actions.items():
                action_type = _normalize_key((action_config or {}).get("type") or config.get("control_type"))
                if action_type == "ir":
                    packet_file = str((action_config or {}).get("file") or "").strip()
                    if not packet_file:
                        issues.append(
                            ValidationIssue(
                                code="missing_packet_file",
                                message=f"Thiết bị '{device_id}' action '{action}' chưa khai báo file .bin",
                                device_id=device_id,
                                action=action,
                            )
                        )
                    else:
                        packet_path = os.path.join(self.packet_dir, packet_file)
                        if not os.path.exists(packet_path):
                            issues.append(
                                ValidationIssue(
                                    code="packet_not_found",
                                    message=f"Không tìm thấy file packet '{packet_file}' cho thiết bị '{device_id}' action '{action}'",
                                    device_id=device_id,
                                    action=action,
                                    packet_file=packet_file,
                                )
                            )

            aliases = list(config.get("aliases") or [])
            for alias in aliases:
                alias_key = _normalize_key(alias)
                if not alias_key:
                    continue
                if alias_key in seen_aliases and seen_aliases[alias_key] != device_id:
                    issues.append(
                        ValidationIssue(
                            code="duplicate_alias",
                            message=f"Alias '{alias}' bị trùng giữa '{seen_aliases[alias_key]}' và '{device_id}'",
                            device_id=device_id,
                            alias=alias,
                        )
                    )
                else:
                    seen_aliases[alias_key] = device_id

        audit = self.build_packet_audit_report()
        return {
            "valid": not any(issue.level == "error" for issue in issues),
            "issues": [issue.to_dict() for issue in issues],
            "summary": {
                "device_count": len(self._device_map),
                "alias_count": len(self._alias_index),
                "error_count": len([issue for issue in issues if issue.level == "error"]),
                "warning_count": len([issue for issue in issues if issue.level == "warning"]),
            },
            "packet_audit": audit,
        }

    def _safe_load_device_map(self) -> Tuple[DeviceMap, List[Dict[str, Any]]]:
        if not os.path.exists(self.device_map_file):
            error = {
                "level": "warning",
                "message": f"Không tìm thấy file device map: {self.device_map_file}",
            }
            return {}, [error]

        try:
            with open(self.device_map_file, "r", encoding="utf-8") as file_obj:
                payload = json.load(file_obj)
        except Exception as exc:
            error = {
                "level": "error",
                "message": f"Không thể parse device map JSON: {exc}",
            }
            log_event(source="device-registry", level="error", message=error["message"], payload=error)
            return {}, [error]

        if not isinstance(payload, dict):
            error = {
                "level": "error",
                "message": "Device map JSON phải là object ở cấp cao nhất",
            }
            log_event(source="device-registry", level="error", message=error["message"], payload=error)
            return {}, [error]

        raw_devices = payload.get("devices") if isinstance(payload.get("devices"), dict) else payload
        normalized_map: DeviceMap = {}
        errors: List[Dict[str, Any]] = []

        for raw_device_id, raw_config in dict(raw_devices or {}).items():
            normalized_id = _normalize_key(raw_device_id)
            if not normalized_id:
                errors.append({"level": "warning", "message": "Bỏ qua device id rỗng trong device map"})
                continue

            if not isinstance(raw_config, dict):
                errors.append({"level": "warning", "message": f"Bỏ qua device '{raw_device_id}' vì config không phải object"})
                continue

            aliases = []
            for alias in list(raw_config.get("aliases") or []):
                alias_key = _normalize_key(alias)
                if alias_key and alias_key != normalized_id and alias_key not in aliases:
                    aliases.append(alias_key)

            control_type = _normalize_key(raw_config.get("control_type") or raw_config.get("type")) or "unknown"
            state_payload = raw_config.get("state")
            if state_payload is None or state_payload == "":
                state_payload = {"power": "unknown"}
            elif isinstance(state_payload, str):
                state_payload = {"power": _normalize_key(state_payload) or "unknown"}

            normalized_map[normalized_id] = {
                "id": normalized_id,
                "template_id": str(raw_config.get("template_id") or "").strip(),
                "name": str(raw_config.get("name") or normalized_id),
                "device_kind": _normalize_key(raw_config.get("device_kind") or raw_config.get("type")) or "unknown",
                "control_type": control_type,
                "capabilities": [
                    _normalize_key(item)
                    for item in list(raw_config.get("capabilities") or [])
                    if _normalize_key(item)
                ],
                "brand": str(raw_config.get("brand") or "unknown").strip(),
                "model": str(raw_config.get("model") or "").strip(),
                "room": str(raw_config.get("room") or "").strip(),
                "enabled": bool(raw_config.get("enabled", True)),
                "aliases": aliases,
                "state_mode": str(raw_config.get("state_mode") or ("optimistic" if control_type == "ir" else "managed")).strip(),
                "state": state_payload,
                "actions": _normalize_command_entries(raw_config.get("actions") or {}, default_type=control_type),
                "presets": _normalize_command_entries(raw_config.get("presets") or {}, default_type=control_type),
                "effective_power": _extract_effective_power(state_payload),
            }

        return normalized_map, errors


_REGISTRY = DeviceRegistry()


def get_registry() -> DeviceRegistry:
    return _REGISTRY
