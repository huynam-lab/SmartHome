from __future__ import annotations

from services.realtime.base import BaseRealtimeHandler
from services.realtime.types import RealtimeIntent


class GoldRealtimeHandler(BaseRealtimeHandler):
    domain = "gold"
    cache_ttl_seconds = 30.0

    def _handle(self, intent: RealtimeIntent):
        brand = str(intent.entities.get("brand") or "").strip().upper()
        product = str(intent.entities.get("product") or "").strip()
        try:
            payload = self._cached_provider_value(
                "gold:xau",
                lambda: self._http_get_json("https://api.gold-api.com/price/XAU"),
                ttl=30.0,
            )
            usd_per_ounce = float(payload["price"])
            updated_at = self._format_timestamp(payload.get("updatedAt") or payload.get("updatedAtReadable"))
            usd_vnd = self._fetch_usd_vnd_rate()
        except Exception as exc:
            return self._unavailable(
                "Em chưa lấy được giá vàng realtime lúc này.",
                data={"error": repr(exc), "brand": brand, "product": product},
            )

        vnd_per_ounce = usd_per_ounce * usd_vnd
        vnd_per_gram = vnd_per_ounce / 31.1034768
        message = (
            f"Giá vàng quốc tế mới nhất là khoảng {usd_per_ounce:,.2f} USD mỗi ounce, "
            f"quy đổi ra khoảng {vnd_per_gram:,.0f} VND mỗi gram, cập nhật lúc {updated_at}."
        )
        if brand or product:
            label = " ".join(part for part in [brand, product] if part).strip()
            message += f" Với {label}, hiện em chưa có nguồn niêm yết trong nước đủ ổn định, nên đang dùng giá vàng quốc tế quy đổi để anh/chị tham khảo."
        return self._success(
            message=message,
            data={
                "brand": brand,
                "product": product,
                "usd_per_ounce": usd_per_ounce,
                "vnd_per_gram": vnd_per_gram,
                "updated_at": updated_at,
            },
            source="api.gold-api.com + open.er-api.com",
        )

    def _fetch_usd_vnd_rate(self) -> float:
        payload = self._cached_provider_value(
            "fx:usd",
            lambda: self._http_get_json("https://open.er-api.com/v6/latest/USD"),
            ttl=45.0,
        )
        if str(payload.get("result") or "").lower() != "success":
            raise RuntimeError("fx provider returned non-success result")
        rates = payload.get("rates") or {}
        value = rates.get("VND")
        if value is None:
            raise RuntimeError("VND rate missing from fx provider")
        return float(value)
