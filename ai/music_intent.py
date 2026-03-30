import re
from typing import Any, Dict, Optional

from ai.intent_parser import normalize_text


def _has_phrase(text_n: str, phrase: str) -> bool:
    phrase_n = normalize_text(phrase)
    if not text_n or not phrase_n:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(phrase_n)}(?![a-z0-9])", text_n) is not None


def _extract_number(text_n: str) -> Optional[int]:
    match = re.search(r"(?<![a-z0-9])(\d{1,3})(?![a-z0-9])", text_n)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _has_any_phrase(text_n: str, phrases) -> bool:
    return any(_has_phrase(text_n, phrase) for phrase in phrases)


def _clamp_volume(value: int) -> int:
    return max(0, min(100, int(value)))


def _cleanup_query(query: str) -> str:
    cleaned = " ".join(str(query or "").strip().split())
    if not cleaned:
        return ""

    cleaned = re.sub(
        r"\b(giup em|giúp em|giup toi|giúp tôi|nhe|nhé|nha|với|voi|di|đi|a|ạ)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = " ".join(cleaned.split()).strip(" ,.!?;:")
    return cleaned


def _normalize_play_query_prefix(query: str) -> str:
    cleaned = _cleanup_query(query)
    if not cleaned:
        return ""

    cleaned = re.sub(
        r"^(?:bài\s+nhạc|bai\s+nhac|bài\s+hát|bai\s+hat|nhạc|nhac|bài|bai)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    return cleaned


def _extract_play_query(text: str) -> str:
    polite_prefix = r"^(?:(?:em|anh|chi|chị|oi|ơi|nhe|nhé|lam\s+on|làm\s+ơn|giup|giúp)\s+)*"
    patterns = [
        polite_prefix + r"(?:xin\s+)?(?:mở|mo|phát|phat|bật|bat)\s+(?:(?:cho|giup|giúp|anh|chi|chị|em|toi|tôi)\s+)*(?:bài\s+nhạc|bai\s+nhac|bài\s+hát|bai\s+hat|nhạc|nhac|bài|bai)\s+(.+)$",
        polite_prefix + r"(?:xin\s+)?(?:mở|mo|phát|phat|bật|bat)\s+(?:cho\s+)?(?:(?:anh|chi|chị|em|toi|tôi)\s+)*(?:nhạc|nhac|bài|bai)\s+(.+)$",
    ]
    raw_text = " ".join(str(text or "").strip().split())
    for pattern in patterns:
        match = re.search(pattern, raw_text, flags=re.IGNORECASE)
        if not match:
            continue
        query = _normalize_play_query_prefix(match.group(1))
        if query:
            return query
    return ""


def _looks_like_play_request(text: str, text_n: str) -> bool:
    if _extract_play_query(text):
        return True

    relaxed_patterns = (
        r"^(?:(?:em|anh|chi|oi|nhe|giup)\s+)*(?:mo|phat|bat)\s+(?:(?:cho|anh|chi|em|toi)\s+)*(?:nhac|bai)\b",
    )
    return any(re.search(pattern, text_n) for pattern in relaxed_patterns)


def parse_music_intent(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None

    text_n = normalize_text(text)
    if not text_n:
        return None

    status_phrases = (
        "nhac dang phat gi",
        "bai dang phat gi",
        "dang phat gi",
        "nhac gi dang phat",
        "trang thai nhac",
    )
    if any(_has_phrase(text_n, phrase) for phrase in status_phrases):
        return {"type": "music", "action": "status", "query": None, "value": None}

    pause_phrases = (
        "tam dung nhac",
        "tam dung bai hat",
        "pause nhac",
    )
    if any(_has_phrase(text_n, phrase) for phrase in pause_phrases):
        return {"type": "music", "action": "pause", "query": None, "value": None}

    resume_phrases = (
        "phat tiep",
        "tiep tuc phat",
        "choi tiep",
        "tiep tuc nhac",
    )
    if any(_has_phrase(text_n, phrase) for phrase in resume_phrases):
        return {"type": "music", "action": "resume", "query": None, "value": None}

    stop_phrases = (
        "tat nhac",
        "dung nhac",
        "ngung nhac",
        "stop nhac",
        "tat bai nhac",
    )
    if _has_any_phrase(text_n, stop_phrases):
        return {"type": "music", "action": "stop", "query": None, "value": None}

    target_volume_value = _extract_number(text_n)
    if _has_phrase(text_n, "tang am luong") and target_volume_value is not None and _has_any_phrase(text_n, ("len", "toi", "muc")):
        return {
            "type": "music",
            "action": "set_volume",
            "query": None,
            "value": _clamp_volume(target_volume_value),
        }

    if _has_phrase(text_n, "giam am luong") and target_volume_value is not None and _has_any_phrase(text_n, ("xuong", "ve", "con")):
        return {
            "type": "music",
            "action": "set_volume",
            "query": None,
            "value": _clamp_volume(target_volume_value),
        }

    if _has_phrase(text_n, "tang am luong"):
        step = target_volume_value or 10
        return {"type": "music", "action": "volume_up", "query": None, "value": max(1, step)}

    if _has_phrase(text_n, "giam am luong"):
        step = target_volume_value or 10
        return {"type": "music", "action": "volume_down", "query": None, "value": max(1, step)}

    if _has_phrase(text_n, "am luong"):
        if target_volume_value is not None:
            return {
                "type": "music",
                "action": "set_volume",
                "query": None,
                "value": _clamp_volume(target_volume_value),
            }

    if _looks_like_play_request(text, text_n):
        query = _extract_play_query(text)
        return {
            "type": "music",
            "action": "play",
            "query": query or "nhac hot",
            "value": None,
        }

    return None
