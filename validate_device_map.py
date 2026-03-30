import json

from controller.device_registry import get_registry


def main() -> int:
    registry = get_registry()
    registry.reload()
    report = registry.validate_configuration()

    print("=" * 80)
    print("DEVICE MAP VALIDATION REPORT")
    print("=" * 80)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print("-" * 80)

    issues = report.get("issues") or []
    if issues:
        print("Issues:")
        for idx, issue in enumerate(issues, start=1):
            print(f"{idx}. [{issue.get('level', 'error').upper()}] {issue.get('code')}: {issue.get('message')}")
    else:
        print("Không phát hiện lỗi cấu hình trong device_map.json")

    packet_audit = report.get("packet_audit") or {}
    print("-" * 80)
    print("Packet audit:")
    print(json.dumps(packet_audit, ensure_ascii=False, indent=2))
    print("=" * 80)

    return 0 if report.get("valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
