from __future__ import annotations

import urllib.parse

from services.realtime.base import BaseRealtimeHandler
from services.realtime.types import RealtimeIntent


class FXRealtimeHandler(BaseRealtimeHandler):
    domain = "fx"
    cache_ttl_seconds = 30.0

    def _handle(self, intent: RealtimeIntent):
        base_currency = str(intent.entities.get("base_currency") or "").upper()
        quote_currency = str(intent.entities.get("quote_currency") or "").upper()
        amount = float(intent.entities.get("amount") or 1)

        if not base_currency:
            return self._clarify("Anh/chị muốn xem tỷ giá đồng nào ạ, ví dụ USD, EUR, JPY hay CNY?")
        if not quote_currency:
            return self._clarify(f"Anh/chị muốn quy đổi {base_currency} sang đồng nào ạ?")
        try:
            payload = self._fetch_rate(base_currency=base_currency, quote_currency=quote_currency)
        except Exception as exc:
            return self._unavailable(
                f"Em chưa lấy được tỷ giá realtime {base_currency}/{quote_currency} lúc này.",
                data={"error": repr(exc), "base_currency": base_currency, "quote_currency": quote_currency},
            )

        rate = float(payload["rate"])
        converted_amount = amount * rate
        updated_at = self._format_timestamp(payload.get("updated_at"))
        if amount == 1:
            message = (
                f"Tỷ giá mới nhất em lấy được là 1 {base_currency} khoảng {converted_amount:,.2f} {quote_currency}, "
                f"cập nhật lúc {updated_at}."
            )
        else:
            message = (
                f"{amount:,.2f} {base_currency} hiện đổi được khoảng {converted_amount:,.2f} {quote_currency}. "
                f"Theo tỷ giá mới nhất, 1 {base_currency} khoảng {rate:,.2f} {quote_currency}, cập nhật lúc {updated_at}."
            )
        return self._success(
            message=message,
            data={
                "base_currency": base_currency,
                "quote_currency": quote_currency,
                "amount": amount,
                "rate": rate,
                "converted_amount": converted_amount,
                "updated_at": updated_at,
            },
            source="open.er-api.com",
        )

    def _fetch_rate(self, base_currency: str, quote_currency: str):
        def fetch_payload():
            url = "https://open.er-api.com/v6/latest/" + urllib.parse.quote(base_currency)
            payload = self._http_get_json(url)
            if str(payload.get("result") or "").lower() != "success":
                raise RuntimeError("fx provider returned non-success result")
            return payload

        payload = self._cached_provider_value(f"fx:base:{base_currency}", fetch_payload, ttl=45.0)
        rates = payload.get("rates") or {}
        rate = rates.get(quote_currency)
        if rate is None:
            raise RuntimeError("target currency missing from fx provider")
        return {
            "rate": rate,
            "updated_at": payload.get("time_last_update_utc") or "",
        }
