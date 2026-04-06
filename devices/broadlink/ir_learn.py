# devices/broadlink/ir_learn.py
# -*- coding: utf-8 -*-

import sys
import json
import time
import argparse
from pathlib import Path

import broadlink

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
IR_DIR = DATA_DIR / "ir_packets"
RM4_PRO_DEVTYPES = {0x520B, 0x5213, 0x5218, 0x6026, 0x6184, 0x61A2, 0x649B, 0x653C}


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default=None):
    if default is None:
        default = {}
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: Path, data):
    ensure_dir(path.parent)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def normalize_mac(mac: str) -> bytes:
    mac = mac.replace(":", "").replace("-", "").strip().lower()
    return bytes.fromhex(mac)


def force_remote_class(dev):
    """
    Sửa lỗi broadlink cũ nhận RM4 Pro 0x520b thành Device generic.
    """
    devtype = getattr(dev, "devtype", None)

    if hasattr(dev, "enter_learning") and hasattr(dev, "check_data"):
        return dev

    if devtype in RM4_PRO_DEVTYPES:
        print(f"[IR] Patch devtype {hex(devtype)} -> rm4pro")
        try:
            # broadlink 0.18.x
            from broadlink.remote import rm4pro
        except Exception:
            try:
                # fallback nếu package export khác kiểu
                from broadlink import rm4pro
            except Exception as e:
                raise RuntimeError(f"Không import được rm4pro từ broadlink: {e}")

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
        print("[IR] Đã ép class sang rm4pro và auth lại thành công.")
        return patched

    return dev


def discover_device(timeout=5):
    print("[IR] Đang tìm Broadlink trong mạng...")
    devices = broadlink.discover(timeout=timeout)

    if not devices:
        raise RuntimeError("Không tìm thấy thiết bị Broadlink nào.")

    dev = devices[0]
    print(f"[IR] Đã tìm thấy thiết bị: {getattr(dev, 'host', None)}")
    return dev


def connect_device(host=None, mac=None, devtype=None, timeout=5):
    if host and mac and devtype is not None:
        print(f"[IR] Kết nối trực tiếp: host={host}, devtype={hex(devtype)}")

        dev = broadlink.gendevice(devtype, (host, 80), normalize_mac(mac), name="SmartHome")
    else:
        dev = discover_device(timeout=timeout)

    dev.auth()
    print("[IR] Auth Broadlink thành công.")

    dev = force_remote_class(dev)
    return dev


def assert_learning_supported(dev):
    if hasattr(dev, "enter_learning") and hasattr(dev, "check_data"):
        return

    cls_name = dev.__class__.__name__
    devtype = getattr(dev, "devtype", None)
    model = getattr(dev, "model", "")

    raise RuntimeError(
        "Thiết bị chưa có enter_learning/check_data.\n"
        f"- class hiện tại: {cls_name}\n"
        f"- devtype: {hex(devtype) if devtype is not None else 'unknown'}\n"
        f"- model: {model}\n"
        "Bản broadlink đang dùng chưa map đúng loại remote."
    )


def learn_ir_packet(dev, timeout=30, interval=1.0):
    assert_learning_supported(dev)

    print("[IR] Bắt đầu chế độ học lệnh...")
    dev.enter_learning()
    time.sleep(1.0)

    print(f"[IR] Hãy chĩa remote vào Broadlink và BẤM GIỮ nút trong {timeout} giây...")

    start = time.time()
    last_print = 0

    while time.time() - start < timeout:
        try:
            packet = dev.check_data()
            if packet:
                print("[IR] Đã nhận được tín hiệu IR.")
                return packet
        except Exception:
            pass

        now = time.time()
        if now - last_print >= 2:
            print("[IR] Đang chờ tín hiệu... tiếp tục giữ nút remote")
            last_print = now

        time.sleep(interval)

    raise TimeoutError("Hết thời gian chờ, chưa học được lệnh IR.")


def save_packet(packet: bytes, filename: str) -> Path:
    ensure_dir(IR_DIR)
    if not filename.endswith(".bin"):
        filename += ".bin"

    save_path = IR_DIR / filename
    with open(save_path, "wb") as f:
        f.write(packet)

    print(f"[IR] Đã lưu file: {save_path}")
    return save_path


def auto_filename(device_id=None, action=None):
    if device_id and action:
        return f"{device_id}_{action}.bin"
    ts = int(time.time())
    if device_id:
        return f"{device_id}_{ts}.bin"
    return f"ir_{ts}.bin"


def build_parser():
    parser = argparse.ArgumentParser(description="Học lệnh IR Broadlink")
    parser.add_argument("--device-id", help="VD: den_san")
    parser.add_argument("--device-name", help='VD: "Đèn sân"')
    parser.add_argument("--action", help="VD: on / off")
    parser.add_argument("--aliases", help='VD: "ds_ac,den_ngoai"')
    parser.add_argument("--filename", help="Tên file bin muốn lưu")
    parser.add_argument("--timeout", type=int, default=30, help="Thời gian chờ học lệnh")
    parser.add_argument("--discover-timeout", type=int, default=5, help="Thời gian tìm Broadlink")
    parser.add_argument("--host", help="IP Broadlink")
    parser.add_argument("--mac", help="MAC Broadlink")
    parser.add_argument("--devtype", type=lambda x: int(x, 0), help="VD: 0x520b")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        dev = connect_device(
            host=args.host,
            mac=args.mac,
            devtype=args.devtype,
            timeout=args.discover_timeout
        )

        packet = learn_ir_packet(dev, timeout=args.timeout, interval=1.0)

        filename = args.filename or auto_filename(args.device_id, args.action)
        save_packet(packet, filename)

        print("[IR] Học lệnh thành công.")

    except KeyboardInterrupt:
        print("\n[IR] Đã huỷ.")
        sys.exit(1)
    except Exception:
        print("[IR] Học lệnh thất bại.")
        sys.exit(1)


if __name__ == "__main__":
    main()
