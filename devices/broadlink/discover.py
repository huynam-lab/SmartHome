import broadlink
import time
from config import BROADLINK_CACHE_TTL_SECONDS, BROADLINK_DEVICE_IP, BROADLINK_DEVICE_MAC, DISCOVER_TIMEOUT
from core.event_bus import log_event


_CACHED_DEVICE = None
_CACHED_AT = 0.0
RM4_PRO_DEVTYPES = {0x520B, 0x5213, 0x5218, 0x6026, 0x6184, 0x61A2, 0x649B, 0x653C}


def _upgrade_remote_device(device):
    if device is None:
        return None

    if hasattr(device, "send_data"):
        return device

    devtype = getattr(device, "devtype", None)
    host = getattr(device, "host", None) or ()
    mac = getattr(device, "mac", b"") or b""

    try:
        if devtype is not None and host and mac:
            upgraded = broadlink.gendevice(devtype, host, mac, name=getattr(device, "name", "SmartHome"))
            upgraded.auth()
            if hasattr(upgraded, "send_data"):
                log_event(
                    source="broadlink-discover",
                    level="info",
                    message="Đã nâng Broadlink generic device bằng gendevice",
                    payload={"devtype": hex(devtype), "host": host},
                )
                return upgraded
    except Exception as exc:
        log_event(
            source="broadlink-discover",
            level="warning",
            message="Không nâng được Broadlink generic device bằng gendevice",
            payload={"error": repr(exc), "devtype": hex(devtype) if devtype is not None else None, "host": host},
        )

    if devtype in RM4_PRO_DEVTYPES:
        try:
            try:
                from broadlink.remote import rm4pro
            except Exception:
                from broadlink import rm4pro

            upgraded = rm4pro(
                host,
                mac,
                devtype,
                name=getattr(device, "name", ""),
                model=getattr(device, "model", "RM4 pro"),
                manufacturer="Broadlink",
                is_locked=getattr(device, "is_locked", False),
            )
            upgraded.auth()
            if hasattr(upgraded, "send_data"):
                log_event(
                    source="broadlink-discover",
                    level="info",
                    message="Đã ép Broadlink generic device sang rm4pro",
                    payload={"devtype": hex(devtype), "host": host},
                )
                return upgraded
        except Exception as exc:
            log_event(
                source="broadlink-discover",
                level="warning",
                message="Không ép được Broadlink generic device sang rm4pro",
                payload={"error": repr(exc), "devtype": hex(devtype), "host": host},
            )

    return device

def discover_devices():
    try:
        devices = broadlink.discover(timeout=DISCOVER_TIMEOUT)
        log_event(source="broadlink-discover", level="info", message="Broadlink discover hoàn tất", payload={"device_count": len(devices or [])})
        return devices if devices else []
    except Exception as exc:
        log_event(source="broadlink-discover", level="error", message="Broadlink discover lỗi", payload={"error": repr(exc)})
        return []

def get_first_device(force_refresh: bool = False):
    global _CACHED_DEVICE, _CACHED_AT

    now = time.time()
    cache_age = now - _CACHED_AT
    if _CACHED_DEVICE is not None and not force_refresh:
        log_event(
            source="broadlink-discover",
            level="info",
            message="Sử dụng Broadlink device từ cache",
            payload={
                "cache_age_seconds": cache_age,
                "cache_stale": cache_age >= BROADLINK_CACHE_TTL_SECONDS,
            },
        )
        return _CACHED_DEVICE

    devices = discover_devices()

    if not devices:
        log_event(source="broadlink-discover", level="error", message="Không tìm thấy Broadlink device nào", payload={})
        return None

    preferred_device = None
    for item in devices:
        host = getattr(item, "host", None) or ()
        ip_address = host[0] if len(host) > 0 else ""
        mac_bytes = getattr(item, "mac", b"") or b""
        mac_text = mac_bytes.hex().lower() if hasattr(mac_bytes, "hex") else ""

        if BROADLINK_DEVICE_IP and ip_address == BROADLINK_DEVICE_IP:
            preferred_device = item
            break

        if BROADLINK_DEVICE_MAC and mac_text == BROADLINK_DEVICE_MAC.replace(":", ""):
            preferred_device = item
            break

    device = preferred_device or devices[0]

    try:
        device.auth()
        device = _upgrade_remote_device(device)
        _CACHED_DEVICE = device
        _CACHED_AT = time.time()
        log_event(
            source="broadlink-discover",
            level="success",
            message="Broadlink auth thành công",
            payload={
                "host": getattr(device, "host", None),
                "class_name": device.__class__.__name__ if device else None,
                "has_send_data": hasattr(device, "send_data") if device else False,
            },
        )
        return device
    except Exception as exc:
        _CACHED_DEVICE = None
        _CACHED_AT = 0.0
        log_event(source="broadlink-discover", level="error", message="Broadlink auth lỗi", payload={"error": repr(exc)})
        return None


def prewarm_device_cache() -> None:
    try:
        device = get_first_device(force_refresh=False)
        log_event(
            source="broadlink-discover",
            level="info" if device is not None else "warning",
            message="Prewarm Broadlink cache hoàn tất",
            payload={"has_device": device is not None},
        )
    except Exception as exc:
        log_event(
            source="broadlink-discover",
            level="warning",
            message="Prewarm Broadlink cache thất bại",
            payload={"error": repr(exc)},
        )
