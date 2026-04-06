import re
from typing import Dict, List, Optional

from ai.intent_parser import normalize_text
from services.realtime.types import RealtimeIntent


_FX_ALIASES = {
    "usd": "USD",
    "do": "USD",
    "do la": "USD",
    "do la my": "USD",
    "my kim": "USD",
    "eur": "EUR",
    "euro": "EUR",
    "jpy": "JPY",
    "yen": "JPY",
    "yen nhat": "JPY",
    "nhat": "JPY",
    "gbp": "GBP",
    "bang anh": "GBP",
    "cny": "CNY",
    "te": "CNY",
    "nhan dan te": "CNY",
    "yuan": "CNY",
    "aud": "AUD",
    "do uc": "AUD",
    "cad": "CAD",
    "do canada": "CAD",
    "sgd": "SGD",
    "do singapore": "SGD",
    "thb": "THB",
    "baht": "THB",
    "krw": "KRW",
    "won": "KRW",
    "won han": "KRW",
    "vnd": "VND",
    "viet nam dong": "VND",
    "tien viet": "VND",
    "dong": "VND",
}

_CRYPTO_ALIASES = {
    "btc": "BTC",
    "bitcoin": "BTC",
    "eth": "ETH",
    "ethereum": "ETH",
    "sol": "SOL",
    "solana": "SOL",
    "bnb": "BNB",
    "ada": "ADA",
    "xrp": "XRP",
    "doge": "DOGE",
    "dogecoin": "DOGE",
}

_GOLD_BRANDS = {
    "sjc": "SJC",
    "pnj": "PNJ",
    "doji": "DOJI",
    "bao tin minh chau": "Bảo Tín Minh Châu",
    "btmc": "Bảo Tín Minh Châu",
}

_GOLD_PRODUCTS = (
    "9999",
    "24k",
    "18k",
    "vang nhan",
    "nhan tron",
    "vang mieng",
)


def _extract_amount(text_n: str) -> Optional[float]:
    match = re.search(r"(?<![a-z0-9])(\d+(?:[.,]\d+)?)", text_n)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except Exception:
        return None


def _find_aliases(text_n: str, alias_map: Dict[str, str]) -> List[str]:
    matches = []
    for alias, normalized in sorted(alias_map.items(), key=lambda item: len(item[0]), reverse=True):
        for match in re.finditer(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text_n):
            matches.append((match.start(), match.end(), normalized))

    matches.sort(key=lambda item: (item[0], -(item[1] - item[0])))

    selected = []
    occupied = []
    seen = set()
    for start, end, normalized in matches:
        if any(not (end <= taken_start or start >= taken_end) for taken_start, taken_end in occupied):
            continue
        if normalized in seen:
            continue
        occupied.append((start, end))
        seen.add(normalized)
        selected.append(normalized)
    return selected


def _looks_like_fx_question(text_n: str) -> bool:
    return any(
        phrase in text_n
        for phrase in (
            "ty gia",
            "doi sang",
            " sang ",
            "bang bao nhieu",
            "quy doi",
            "gia do",
            "gia euro",
            "gia yen",
        )
    )


def _looks_like_gold_question(text_n: str) -> bool:
    return "gia vang" in text_n or "vang hom nay" in text_n


def _looks_like_crypto_question(text_n: str) -> bool:
    return any(phrase in text_n for phrase in ("crypto", "coin", "bitcoin", "btc", "ethereum", "eth", "gia btc", "gia coin"))


def _looks_like_news_question(text_n: str) -> bool:
    return any(
        phrase in text_n
        for phrase in (
            "tin tuc",
            "tin moi",
            "tin hom nay",
            "bao hom nay",
            "thoi su hom nay",
            "doc bao",
        )
    )


def _extract_news_topic(text: str) -> str:
    raw_text = " ".join(str(text or "").strip().split())
    cleaned = re.sub(
        r"\b(tin tuc|tin moi|tin hom nay|bao hom nay|thoi su hom nay|doc bao|cho toi|cho em|giup em|giup toi|hom nay|moi nhat|xem nhanh|cap nhat|ban tin|thoi su)\b",
        " ",
        normalize_text(raw_text),
    )
    cleaned = re.sub(r"\b(ve|về)\b", " ", cleaned)
    cleaned = " ".join(cleaned.split()).strip(" ,.!?;:")
    if cleaned in {"", "moi", "nhat", "moi nhat"}:
        return ""
    return cleaned


def parse_realtime_intent(text: str) -> Optional[RealtimeIntent]:
    text_n = normalize_text(text)
    if not text_n:
        return None

    if _looks_like_news_question(text_n):
        return RealtimeIntent(
            domain="news",
            raw_text=text,
            entities={"topic": _extract_news_topic(text)},
            time_scope="today" if "hom nay" in text_n else "now",
            confidence=0.87,
        )

    if _looks_like_gold_question(text_n):
        brand = ""
        for alias, normalized in _GOLD_BRANDS.items():
            if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text_n):
                brand = normalized
                break

        product = ""
        for item in _GOLD_PRODUCTS:
            if re.search(rf"(?<![a-z0-9]){re.escape(item)}(?![a-z0-9])", text_n):
                product = item
                break

        return RealtimeIntent(
            domain="gold",
            raw_text=text,
            entities={"brand": brand, "product": product},
            time_scope="today" if "hom nay" in text_n else "now",
            confidence=0.92,
        )

    if _looks_like_crypto_question(text_n):
        symbols = _find_aliases(text_n, _CRYPTO_ALIASES)
        quote_currencies = _find_aliases(text_n, _FX_ALIASES)
        return RealtimeIntent(
            domain="crypto",
            raw_text=text,
            entities={
                "symbol": symbols[0] if symbols else "",
                "quote_currency": quote_currencies[0] if quote_currencies else "USD",
            },
            time_scope="now",
            confidence=0.9,
        )

    if _looks_like_fx_question(text_n):
        currencies = _find_aliases(text_n, _FX_ALIASES)
        base_currency = currencies[0] if currencies else ""
        quote_currency = currencies[1] if len(currencies) > 1 else ""
        if base_currency and not quote_currency and base_currency != "VND":
            quote_currency = "VND"
        amount = _extract_amount(text_n) or 1
        return RealtimeIntent(
            domain="fx",
            raw_text=text,
            entities={
                "base_currency": base_currency,
                "quote_currency": quote_currency,
                "amount": amount,
            },
            time_scope="today" if "hom nay" in text_n else "now",
            confidence=0.88,
        )

    return None
