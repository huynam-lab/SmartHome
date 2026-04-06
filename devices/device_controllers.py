from __future__ import annotations

from typing import Any, Dict, Optional, Protocol

from core.event_bus import log_event
from devices.broadlink.discover import get_first_device
from devices.broadlink.ir_sender import load_ir_packet, send_ir_packet
from devices.broadlink.rf_sender import load_rf_packet, send_rf_packet


class DeviceController(Protocol):
    """Interface chung cho các bộ điều khiển thiết bị."""

    def execute(self, device: Dict[str, Any], action: str, packet_info: Dict[str, Any]) -> Dict[str, Any]:
        ...


class IRDeviceController:
    """Điều khiển thiết bị IR qua Broadlink."""

    controller_type = "ir"

    def execute(self, device: Dict[str, Any], action: str, packet_info: Dict[str, Any]) -> Dict[str, Any]:
        packet_path = packet_info.get("packet_path")
        packet_file = packet_info.get("packet_file")

        if not packet_path:
            message = "Không xác định được packet path để gửi IR"
            log_event(
                source="ir-controller",
                level="error",
                message=message,
                payload={"device": device.get("id"), "action": action, "packet_info": packet_info},
            )
            return {
                "success": False,
                "message": message,
                "device": device.get("id"),
                "action": action,
                "packet_file": packet_file,
                "packet_path": packet_path,
                "details": {"reason": "missing_packet_path"},
            }

        packet_bytes = load_ir_packet(packet_path)
        if not packet_bytes:
            message = "Không đọc được packet IR từ file .bin"
            log_event(
                source="ir-controller",
                level="error",
                message=message,
                payload={
                    "device": device.get("id"),
                    "action": action,
                    "packet_file": packet_file,
                    "packet_path": packet_path,
                },
            )
            return {
                "success": False,
                "message": message,
                "device": device.get("id"),
                "action": action,
                "packet_file": packet_file,
                "packet_path": packet_path,
                "details": {"reason": "packet_load_failed"},
            }

        broadlink_device = get_first_device()
        if broadlink_device is None:
            message = "Không tìm thấy Broadlink device khả dụng"
            log_event(
                source="ir-controller",
                level="error",
                message=message,
                payload={"device": device.get("id"), "action": action},
            )
            return {
                "success": False,
                "message": message,
                "device": device.get("id"),
                "action": action,
                "packet_file": packet_file,
                "packet_path": packet_path,
                "details": {"reason": "broadlink_not_found"},
            }

        broadlink_host = getattr(broadlink_device, "host", None) or ()
        broadlink_mac = getattr(broadlink_device, "mac", b"") or b""
        send_result = send_ir_packet(broadlink_device, packet_bytes)
        retried_after_refresh = False

        if not send_result.get("success"):
            refreshed_device = get_first_device(force_refresh=True)
            if refreshed_device is not None:
                retried_after_refresh = True
                broadlink_device = refreshed_device
                broadlink_host = getattr(broadlink_device, "host", None) or ()
                broadlink_mac = getattr(broadlink_device, "mac", b"") or b""
                send_result = send_ir_packet(broadlink_device, packet_bytes)

        if send_result.get("success"):
            message = "Đã gọi broadlink.send_data() thành công ở mức code; chưa xác thực trạng thái thực tế của thiết bị"
            level = "success"
        else:
            message = send_result.get("message") or "Gửi packet IR thất bại"
            level = "error"

        details = {
            "broadlink_host": broadlink_host,
            "broadlink_mac": broadlink_mac.hex() if hasattr(broadlink_mac, "hex") else str(broadlink_mac),
            "packet_size": len(packet_bytes),
            "code_level_delivery": bool(send_result.get("success")),
            "physical_device_state_confirmed": False,
            "warning": "Broadlink gửi packet thành công không đồng nghĩa thiết bị ngoài đời đã bật/tắt thật",
            "retried_after_refresh": retried_after_refresh,
            "send_result": send_result,
        }

        log_event(
            source="ir-controller",
            level=level,
            message=message,
            payload={
                "device": device.get("id"),
                "action": action,
                "packet_file": packet_file,
                "packet_path": packet_path,
                **details,
            },
        )

        return {
            "success": bool(send_result.get("success")),
            "message": message,
            "device": device.get("id"),
            "action": action,
            "packet_file": packet_file,
            "packet_path": packet_path,
            "details": details,
        }


class WifiDeviceController:
    """Stub cho thiết bị WiFi mở rộng về sau."""

    controller_type = "wifi"

    def execute(self, device: Dict[str, Any], action: str, packet_info: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "success": False,
            "message": "WifiDeviceController chưa được triển khai",
            "device": device.get("id"),
            "action": action,
            "packet_file": packet_info.get("packet_file"),
            "packet_path": packet_info.get("packet_path"),
            "details": {"reason": "not_implemented"},
        }


class RFDeviceController:
    """Điều khiển thiết bị RF qua Broadlink."""

    controller_type = "rf"

    def execute(self, device: Dict[str, Any], action: str, packet_info: Dict[str, Any]) -> Dict[str, Any]:
        packet_path = packet_info.get("packet_path")
        packet_file = packet_info.get("packet_file")

        if not packet_path:
            message = "Không xác định được packet path để gửi RF"
            log_event(
                source="rf-controller",
                level="error",
                message=message,
                payload={"device": device.get("id"), "action": action, "packet_info": packet_info},
            )
            return {
                "success": False,
                "message": message,
                "device": device.get("id"),
                "action": action,
                "packet_file": packet_file,
                "packet_path": packet_path,
                "details": {"reason": "missing_packet_path"},
            }

        packet_bytes = load_rf_packet(packet_path)
        if not packet_bytes:
            message = "Không đọc được packet RF từ file"
            log_event(
                source="rf-controller",
                level="error",
                message=message,
                payload={
                    "device": device.get("id"),
                    "action": action,
                    "packet_file": packet_file,
                    "packet_path": packet_path,
                },
            )
            return {
                "success": False,
                "message": message,
                "device": device.get("id"),
                "action": action,
                "packet_file": packet_file,
                "packet_path": packet_path,
                "details": {"reason": "packet_load_failed"},
            }

        broadlink_device = get_first_device()
        if broadlink_device is None:
            message = "Không tìm thấy Broadlink device khả dụng"
            log_event(
                source="rf-controller",
                level="error",
                message=message,
                payload={"device": device.get("id"), "action": action},
            )
            return {
                "success": False,
                "message": message,
                "device": device.get("id"),
                "action": action,
                "packet_file": packet_file,
                "packet_path": packet_path,
                "details": {"reason": "broadlink_not_found"},
            }

        broadlink_host = getattr(broadlink_device, "host", None) or ()
        broadlink_mac = getattr(broadlink_device, "mac", b"") or b""
        send_result = send_rf_packet(broadlink_device, packet_bytes)
        retried_after_refresh = False

        if not send_result.get("success"):
            refreshed_device = get_first_device(force_refresh=True)
            if refreshed_device is not None:
                retried_after_refresh = True
                broadlink_device = refreshed_device
                broadlink_host = getattr(broadlink_device, "host", None) or ()
                broadlink_mac = getattr(broadlink_device, "mac", b"") or b""
                send_result = send_rf_packet(broadlink_device, packet_bytes)

        message = send_result.get("message") or "Gửi packet RF thất bại"
        level = "success" if send_result.get("success") else "error"
        details = {
            "broadlink_host": broadlink_host,
            "broadlink_mac": broadlink_mac.hex() if hasattr(broadlink_mac, "hex") else str(broadlink_mac),
            "packet_size": len(packet_bytes),
            "rf_frequency": (packet_info.get("action_config") or {}).get("rf_frequency") or device.get("rf_frequency"),
            "code_level_delivery": bool(send_result.get("success")),
            "physical_device_state_confirmed": False,
            "retried_after_refresh": retried_after_refresh,
            "send_result": send_result,
        }

        log_event(
            source="rf-controller",
            level=level,
            message=message,
            payload={
                "device": device.get("id"),
                "action": action,
                "packet_file": packet_file,
                "packet_path": packet_path,
                **details,
            },
        )

        return {
            "success": bool(send_result.get("success")),
            "message": message,
            "device": device.get("id"),
            "action": action,
            "packet_file": packet_file,
            "packet_path": packet_path,
            "details": details,
        }


class RelayDeviceController:
    """Stub cho thiết bị relay mở rộng về sau."""

    controller_type = "relay"

    def execute(self, device: Dict[str, Any], action: str, packet_info: Dict[str, Any]) -> Dict[str, Any]:
        action_config = packet_info.get("action_config") or {}
        return {
            "success": False,
            "message": "RelayDeviceController chưa được triển khai",
            "device": device.get("id"),
            "action": action,
            "packet_file": packet_info.get("packet_file"),
            "packet_path": packet_info.get("packet_path"),
            "details": {
                "reason": "not_implemented",
                "action_config": action_config,
            },
        }


def get_device_controller(device_type: str) -> Optional[DeviceController]:
    controllers: Dict[str, DeviceController] = {
        "ir": IRDeviceController(),
        "rf": RFDeviceController(),
        "wifi": WifiDeviceController(),
        "relay": RelayDeviceController(),
        "gpio": RelayDeviceController(),
    }
    return controllers.get((device_type or "").strip().lower())
