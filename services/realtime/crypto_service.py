from __future__ import annotations

import urllib.parse

from services.realtime.base import BaseRealtimeHandler
from services.realtime.types import RealtimeIntent

_SYMBOL_TO_COINGECKO_ID = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "ADA": "cardano",
    "XRP": "ripple",
    "DOGE": "dogecoin",
}


class CryptoRealtimeHandler(BaseRealtimeHandler):
    domain = "crypto"
    cache_ttl_seconds = 20.0

    def _handle(self, intent: RealtimeIntent):
        symbol = str(intent.entities.get("symbol") or "").upper()
        quote_currency = str(intent.entities.get("quote_currency") or "").upper() or "USD"

        if not symbol:
            return self._clarify("Anh/chị muốn xem coin nào ạ, ví dụ BTC, ETH, SOL hay BNB?")
        coin_id = _SYMBOL_TO_COINGECKO_ID.get(symbol)
        if not coin_id:
            return self._clarify(f"Em chưa map sẵn mã coin {symbol}. Anh/chị thử hỏi bằng mã phổ biến như BTC, ETH, SOL, BNB, ADA, XRP hoặc DOGE.")

        try:
            usd_price, updated_at = self._fetch_usd_price(coin_id=coin_id)
            price = float(usd_price)
            if quote_currency != "USD":
                price = self._convert_from_usd(price, quote_currency)
        except Exception as exc:
            return self._unavailable(
                f"Em chưa lấy được giá crypto realtime cho {symbol}/{quote_currency} lúc này.",
                data={"error": repr(exc), "symbol": symbol, "quote_currency": quote_currency},
            )

        updated_at = self._format_timestamp(updated_at)
        message = f"Giá {symbol}/{quote_currency} mới nhất em lấy được là khoảng {price:,.2f}, cập nhật lúc {updated_at}."
        return self._success(
            message=message,
            data={
                "symbol": symbol,
                "quote_currency": quote_currency,
                "price": price,
                "updated_at": updated_at,
            },
            source="api.coingecko.com",
        )

    def _fetch_usd_price(self, coin_id: str):
        def fetch_payload():
            query = urllib.parse.urlencode(
                {
                    "ids": coin_id,
                    "vs_currencies": "usd",
                    "include_last_updated_at": "true",
                }
            )
            return self._http_get_json(f"https://api.coingecko.com/api/v3/simple/price?{query}")

        payload = self._cached_provider_value(f"crypto:usd:{coin_id}", fetch_payload, ttl=20.0)
        item = payload.get(coin_id) or {}
        if "usd" not in item:
            raise RuntimeError("crypto price missing from provider")
        return item["usd"], str(item.get("last_updated_at") or self._now_text())

    def _convert_from_usd(self, usd_amount: float, quote_currency: str) -> float:
        payload = self._cached_provider_value(
            "fx:usd",
            lambda: self._http_get_json("https://open.er-api.com/v6/latest/USD"),
            ttl=45.0,
        )
        if str(payload.get("result") or "").lower() != "success":
            raise RuntimeError("fx conversion provider returned non-success result")
        rates = payload.get("rates") or {}
        target_rate = rates.get(quote_currency)
        if target_rate is None:
            raise RuntimeError("crypto quote currency missing from fx provider")
        return float(usd_amount) * float(target_rate)
