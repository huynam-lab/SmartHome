from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Dict, List, Tuple

from config import DEVICE_TEMPLATE_FILE


TemplatePayload = Dict[str, Any]


def _normalize_capabilities(raw_capabilities: Any, device_kind: str) -> List[str]:
    capabilities: List[str] = []
    default_capability_map = {
        "light": ["power", "timer"],
        "air_conditioner": ["power", "temperature", "mode", "fan_speed", "timer"],
        "smart_switch": ["power", "timer"],
    }

    for capability in list(raw_capabilities or default_capability_map.get(device_kind, [])):
        normalized = str(capability or "").strip().lower()
        if normalized and normalized not in capabilities:
            capabilities.append(normalized)
    return capabilities


def _normalize_template_field(raw_field: Any) -> Dict[str, Any] | None:
    if isinstance(raw_field, str):
        field_id = str(raw_field).strip()
        if not field_id:
            return None
        return {
            "id": field_id,
            "label": field_id.replace("_", " ").title(),
            "type": "text",
            "required": field_id == "name",
            "placeholder": "",
        }

    if not isinstance(raw_field, dict):
        return None

    field_id = str(raw_field.get("id") or "").strip()
    if not field_id:
        return None

    return {
        "id": field_id,
        "label": str(raw_field.get("label") or field_id.replace("_", " ").title()).strip(),
        "type": str(raw_field.get("type") or "text").strip().lower() or "text",
        "required": bool(raw_field.get("required")),
        "placeholder": str(raw_field.get("placeholder") or "").strip(),
    }


def _normalize_template(template_key: str, raw_template: Any) -> TemplatePayload | None:
    if not isinstance(raw_template, dict):
        return None

    template_id = str(raw_template.get("id") or template_key).strip()
    template_name = str(raw_template.get("template_name") or template_id).strip()
    if not template_id or not template_name:
        return None

    learn_fields = []
    for raw_field in list(raw_template.get("learn_fields") or []):
        normalized_field = _normalize_template_field(raw_field)
        if normalized_field:
            learn_fields.append(normalized_field)

    structure = raw_template.get("structure") or {}
    default_state = raw_template.get("default_state") or {}
    device_kind = str(raw_template.get("device_kind") or "unknown").strip().lower() or "unknown"

    return {
        "id": template_id,
        "template_name": template_name,
        "template_description": str(raw_template.get("template_description") or "").strip(),
        "device_kind": device_kind,
        "control_type": str(raw_template.get("control_type") or "unknown").strip().lower() or "unknown",
        "capabilities": _normalize_capabilities(raw_template.get("capabilities"), device_kind),
        "learn_fields": learn_fields,
        "structure": {
          "use_actions": bool(structure.get("use_actions")),
          "use_presets": bool(structure.get("use_presets")),
          "allow_custom_actions": bool(structure.get("allow_custom_actions")),
          "allow_custom_presets": bool(structure.get("allow_custom_presets")),
        },
        "default_state": deepcopy(default_state),
    }


def load_template_store(template_file: str = DEVICE_TEMPLATE_FILE) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    warnings: List[Dict[str, Any]] = []

    try:
        with open(template_file, "r", encoding="utf-8") as file_obj:
            payload = json.load(file_obj)
    except FileNotFoundError:
        return {"template_version": "0", "templates": {}}, [{
            "level": "error",
            "message": f"Không tìm thấy file template: {template_file}",
        }]
    except json.JSONDecodeError as exc:
        return {"template_version": "0", "templates": {}}, [{
            "level": "error",
            "message": f"device_template.json không hợp lệ: {exc}",
        }]

    templates: Dict[str, TemplatePayload] = {}
    for template_key, raw_template in dict(payload.get("templates") or {}).items():
        normalized = _normalize_template(template_key, raw_template)
        if not normalized:
            warnings.append({
                "level": "warning",
                "message": f"Bỏ qua template không hợp lệ: {template_key}",
            })
            continue
        templates[normalized["id"]] = normalized

    return {
        "template_version": str(payload.get("template_version") or "0"),
        "templates": templates,
    }, warnings


def list_device_templates(template_file: str = DEVICE_TEMPLATE_FILE) -> Tuple[List[TemplatePayload], List[Dict[str, Any]]]:
    store, warnings = load_template_store(template_file)
    items = []
    for template in store["templates"].values():
        items.append({
            "id": template["id"],
            "template_name": template["template_name"],
            "template_description": template["template_description"],
            "device_kind": template["device_kind"],
            "control_type": template["control_type"],
            "capabilities": deepcopy(template["capabilities"]),
            "structure": deepcopy(template["structure"]),
        })
    return items, warnings


def get_device_template(template_id: str, template_file: str = DEVICE_TEMPLATE_FILE) -> Tuple[TemplatePayload | None, List[Dict[str, Any]]]:
    store, warnings = load_template_store(template_file)
    normalized_id = str(template_id or "").strip()
    template = store["templates"].get(normalized_id)
    return deepcopy(template) if template else None, warnings
