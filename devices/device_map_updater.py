from typing import Any, Dict, List

from config import DEVICE_MAP_FILE
from services.device_learning_service import save_learned_device, slugify_device_id


def update_device_map(
    device_id: str,
    action: str,
    file_name: str,
    device_name: str = "",
    signal_type: str = "",
    alias_hints: List[str] = None,
    device_map_file: str = DEVICE_MAP_FILE,
) -> Dict[str, Any]:
    """
    Wrapper tương thích ngược cho flow cũ.
    Từ một action IR đơn lẻ sẽ tạo/cập nhật thiết bị thật theo template đèn thông minh mở.
    """
    normalized_device_id = slugify_device_id(device_id or device_name)
    normalized_action = str(action or "").strip()
    if not normalized_device_id:
        return {"ok": False, "message": "device_id không hợp lệ"}
    if not normalized_action:
        return {"ok": False, "message": "action không hợp lệ"}
    if not file_name:
        return {"ok": False, "message": "file_name không hợp lệ"}

    result = save_learned_device(
        template_id="den_thong_minh",
        device_payload={
            "id": normalized_device_id,
            "name": device_name or normalized_device_id.replace("_", " "),
            "brand": "broadlink" if (signal_type or "ir").lower() == "ir" else "generic",
            "aliases": list(alias_hints or []),
        },
        actions_payload={
            normalized_action: {
                "type": signal_type or "ir",
                "file": file_name,
            }
        },
        presets_payload={},
        device_map_file=device_map_file,
    )

    return {
        "ok": True,
        "message": result.get("message") or "Đã cập nhật device_map.json",
        "device": result.get("device_id"),
        "action": normalized_action,
        "file_name": file_name,
        "device_config": result.get("device"),
        "load_warnings": result.get("warnings") or [],
    }
