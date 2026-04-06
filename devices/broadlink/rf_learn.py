#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import json
import time
import base64
import argparse
from pathlib import Path

import broadlink
from config import BROADLINK_DEVICE_IP, BROADLINK_DEVICE_MAC

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
RF_DIR = DATA_DIR / "rf_packets"
RM4_PRO_DEVTYPES = {0x520B, 0x5213, 0x5218, 0x6026, 0x6184, 0x61A2, 0x649B, 0x653C}
RF_SIMPLE_LEARN_DEVTYPES = {0x2712}


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def save_json(path: Path, data):
    ensure_dir(path.parent)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def normalize_mac(mac: str) -> bytes:
    mac = mac.replace(":", "").replace("-", "").strip().lower()
    return bytes.fromhex(mac)


def force_remote_class(dev):
    devtype = getattr(dev, "devtype", None)

    if all(hasattr(dev, name) for name in ("check_data", "enter_learning")) and (
        all(hasattr(dev, name) for name in ("sweep_frequency", "check_frequency", "find_rf_packet"))
        or devtype in RF_SIMPLE_LEARN_DEVTYPES
    ):
        return dev

    if devtype in RM4_PRO_DEVTYPES:
        print(f"[RF] Patch devtype {hex(devtype)} -> rm4pro")
        try:
            from broadlink.remote import rm4pro
        except Exception:
            try:
                from broadlink import rm4pro
            except Exception as e:
                raise RuntimeError(f"Khong import duoc rm4pro tu broadlink: {e}")

        patched = rm4pro(
            dev.host,
            dev.mac,
            dev.devtype,
            name=getattr(dev, "name", ""),
            model="RM4 pro",
            manufacturer="Broadlink",
            is_locked=getattr(dev, "is_locked", False),
        )
        patched.auth()
        print("[RF] Da ep class sang rm4pro va auth lai thanh cong.")
        return patched

    return dev


def discover_device(timeout=5):
    print("[RF] Dang tim Broadlink trong mang...")
    devices = broadlink.discover(timeout=timeout)
    if not devices:
        raise RuntimeError("Khong tim thay thiet bi Broadlink nao.")

    preferred_device = None
    preferred_ip = str(BROADLINK_DEVICE_IP or "").strip()
    preferred_mac = str(BROADLINK_DEVICE_MAC or "").strip().lower().replace(":", "").replace("-", "")
    for item in devices:
        host = getattr(item, "host", None) or ()
        ip_address = host[0] if len(host) > 0 else ""
        mac_bytes = getattr(item, "mac", b"") or b""
        mac_text = mac_bytes.hex().lower() if hasattr(mac_bytes, "hex") else ""
        if preferred_ip and ip_address == preferred_ip:
            preferred_device = item
            print(f"[RF] Chon Broadlink theo IP cau hinh: {preferred_ip}")
            break
        if preferred_mac and mac_text == preferred_mac:
            preferred_device = item
            print(f"[RF] Chon Broadlink theo MAC cau hinh: {preferred_mac}")
            break

    dev = preferred_device or devices[0]
    print(f"[RF] Da tim thay thiet bi: {getattr(dev, 'host', None)}")
    return dev


def connect_device(host=None, mac=None, devtype=None, timeout=5):
    if host and mac and devtype is not None:
        print(f"[RF] Ket noi truc tiep: host={host}, devtype={hex(devtype)}")
        dev = broadlink.gendevice(devtype, (host, 80), normalize_mac(mac), name="SmartHome")
    else:
        dev = discover_device(timeout=timeout)

    dev.auth()
    print("[RF] Auth Broadlink thanh cong.")

    dev = force_remote_class(dev)
    return dev


def assert_rf_learning_supported(dev):
    devtype = getattr(dev, "devtype", None)

    simple_ok = devtype in RF_SIMPLE_LEARN_DEVTYPES and all(
        hasattr(dev, name) for name in ("enter_learning", "check_data")
    )
    full_ok = all(
        hasattr(dev, name) for name in ("sweep_frequency", "check_frequency", "find_rf_packet", "check_data")
    )

    if simple_ok or full_ok:
        return

    cls_name = dev.__class__.__name__
    model = getattr(dev, "model", "")
    raise RuntimeError(
        "Thiet bi chua co day du ham hoc RF.\n"
        f"- class hien tai: {cls_name}\n"
        f"- devtype: {hex(devtype) if devtype is not None else 'unknown'}\n"
        f"- model: {model}\n"
        "Ban broadlink dang dung chua map dung loai remote hoac thiet bi khong ho tro RF."
    )


def wait_for_packet(dev, timeout=30, interval=1.0, label="RF"):
    start = time.time()
    last_print = 0

    while time.time() - start < timeout:
        try:
            packet = dev.check_data()
            if packet:
                print(f"[{label}] Da nhan duoc packet.")
                return packet
        except Exception:
            pass

        now = time.time()
        if now - last_print >= 2:
            print(f"[{label}] Dang cho tin hieu...")
            last_print = now

        time.sleep(interval)

    raise TimeoutError("Het thoi gian cho, chua nhan duoc packet RF.")


def learn_rf_packet(dev, timeout=30, interval=1.0, frequency=None):
    assert_rf_learning_supported(dev)
    devtype = getattr(dev, "devtype", None)

    if devtype in RF_SIMPLE_LEARN_DEVTYPES:
        print("[RF] Thiet bi dung che do hoc RF don gian (khong can sweep tan so).")
        dev.enter_learning()
        time.sleep(1.0)
        print(f"[RF] Bam nut remote RF va giu trong {timeout} giay...")
        packet = wait_for_packet(dev, timeout=timeout, interval=interval, label="RF")
        return {"packet": packet, "frequency": None}

    if frequency is None:
        print("[RF] Bat dau quet tan so RF...")
        dev.sweep_frequency()
        print("[RF] Hay dua remote gan Broadlink va GIU nut 2-5 giay...")

        start = time.time()
        last_print = 0
        locked = False
        found_frequency = None

        while time.time() - start < timeout:
            try:
                result = dev.check_frequency()
                if isinstance(result, tuple):
                    locked, found_frequency = result
                else:
                    locked = bool(result)
            except Exception:
                locked = False
                found_frequency = None

            if locked:
                break

            now = time.time()
            if now - last_print >= 2:
                print("[RF] Dang do tan so... tiep tuc giu nut remote")
                last_print = now

            time.sleep(interval)

        if not locked:
            try:
                if hasattr(dev, "cancel_sweep_frequency"):
                    dev.cancel_sweep_frequency()
            except Exception:
                pass
            raise TimeoutError("Het thoi gian quet tan so RF. Thu dua remote gan hon va giu nut lau hon.")

        frequency = found_frequency
        if frequency is None:
            print("[RF] Da khoa duoc tan so.")
        else:
            print(f"[RF] Da bat duoc tan so: {frequency} MHz")
    else:
        print(f"[RF] Bo qua quet tan so, dung tan so duoc chi dinh: {frequency} MHz")

    print("[RF] Nha nut ra, sau do bam nhanh lai 1 lan de hoc packet...")
    time.sleep(1.0)

    try:
        if frequency is None:
            dev.find_rf_packet()
        else:
            dev.find_rf_packet(frequency)
    except TypeError:
        dev.find_rf_packet()

    packet = wait_for_packet(dev, timeout=timeout, interval=interval, label="RF")
    return {"packet": packet, "frequency": frequency}


def auto_filename(device_id=None, action=None):
    if device_id and action:
        return f"{device_id}_{action}.json"
    ts = int(time.time())
    if device_id:
        return f"{device_id}_{ts}.json"
    return f"rf_{ts}.json"


def save_packet_json(packet: bytes, filename: str, meta=None) -> Path:
    ensure_dir(RF_DIR)
    if not filename.endswith(".json"):
        filename += ".json"

    save_path = RF_DIR / filename
    payload = {
        "packet_base64": base64.b64encode(packet).decode("ascii"),
        "packet_hex": packet.hex(),
        "length": len(packet),
        "saved_at": int(time.time()),
    }
    if meta:
        payload.update(meta)

    save_json(save_path, payload)
    print(f"[RF] Da luu file: {save_path}")
    return save_path


def build_parser():
    parser = argparse.ArgumentParser(description="Hoc lenh RF Broadlink")
    parser.add_argument("--device-id", help="VD: cong_tac_cua_cuon")
    parser.add_argument("--device-name", help='VD: "Cong tac cua cuon"')
    parser.add_argument("--action", help="VD: on / off / lock / unlock")
    parser.add_argument("--aliases", help='VD: "ctcc,cong_tac_rf"')
    parser.add_argument("--filename", help="Ten file json muon luu")
    parser.add_argument("--timeout", type=int, default=30, help="Thoi gian cho moi buoc hoc lenh")
    parser.add_argument("--interval", type=float, default=1.0, help="Chu ky poll check_data/check_frequency")
    parser.add_argument("--discover-timeout", type=int, default=5, help="Thoi gian tim Broadlink")
    parser.add_argument("--host", help="IP Broadlink")
    parser.add_argument("--mac", help="MAC Broadlink")
    parser.add_argument("--devtype", type=lambda x: int(x, 0), help="VD: 0x649b")
    parser.add_argument("--frequency", type=float, help="Chi dinh tan so RF neu da biet truoc")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        dev = connect_device(
            host=args.host,
            mac=args.mac,
            devtype=args.devtype,
            timeout=args.discover_timeout,
        )

        result = learn_rf_packet(dev, timeout=args.timeout, interval=args.interval, frequency=args.frequency)
        packet = result["packet"]
        frequency = result["frequency"]

        filename = args.filename or auto_filename(args.device_id, args.action)
        meta = {
            "device_id": args.device_id,
            "device_name": args.device_name,
            "action": args.action,
            "aliases": [x.strip() for x in args.aliases.split(",")] if args.aliases else [],
            "broadlink_host": dev.host[0] if getattr(dev, "host", None) else None,
            "broadlink_devtype": hex(getattr(dev, "devtype", 0)) if getattr(dev, "devtype", None) is not None else None,
            "rf_frequency_mhz": frequency,
        }
        save_path = save_packet_json(packet, filename, meta=meta)

        print("[RF] Hoc lenh thanh cong.")
        print(f"[RF] Base64: {base64.b64encode(packet).decode('ascii')}")
        print(f"[RF] JSON: {save_path}")

    except KeyboardInterrupt:
        print("\n[RF] Da huy.")
        sys.exit(1)
    except Exception:
        print("[RF] Hoc lenh that bai.")
        sys.exit(1)


if __name__ == "__main__":
    main()
