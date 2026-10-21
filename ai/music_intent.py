import re
from typing import Any, Dict, Optional
from ai.intent_parser import normalize_text

def _has_phrase(text_n: str, phrase: str) -> bool:
    p = normalize_text(phrase)
    return bool(text_n and p and re.search(rf"(?<![a-z0-9]){re.escape(p)}(?![a-z0-9])", text_n))

def _extract_number(text_n: str) -> Optional[int]:
    m = re.search(r"(?<![a-z0-9])(\d{1,3})(?![a-z0-9])", text_n)
    if not m: return None
    try: return int(m.group(1))
    except Exception: return None

def _has_any_phrase(text_n: str, phrases) -> bool:
    return any(_has_phrase(text_n, p) for p in phrases)

def _clamp_volume(value: int) -> int:
    return max(0, min(100, int(value)))

def _cleanup_query(query: str) -> str:
    s = " ".join(str(query or "").strip().split())
    if not s: return ""
    s = re.sub(r"\b(giup em|giúp em|giup toi|giúp tôi|nhe|nhé|nha|với|voi|di|đi|a|ạ)\b", " ", s, flags=re.I)
    s = re.sub(r"\b(cho\s+anh|cho\s+chi|cho\s+chị|cho\s+em|cho\s+toi|cho\s+tôi|khong|không)\b", " ", s, flags=re.I)
    return " ".join(s.split()).strip(" ,.!?;:")

def _normalize_play_query_prefix(query: str) -> str:
    s = _cleanup_query(query)
    if not s: return ""
    return re.sub(r"^(?:bài\s+nhạc|bai\s+nhac|bài\s+hát|bai\s+hat|nhạc|nhac|bài|bai)\s+", "", s, flags=re.I).strip()

def _extract_play_query(text: str) -> str:
    prefix = r"^(?:(?:em|anh|chi|chị|oi|ơi|nhe|nhé|lam\s+on|làm\s+ơn|giup|giúp|hay|hãy|xin|vui\s+lòng)\s+)*(?:(?:co\s+the|có\s+thể)\s+)?"
    patterns = [
        prefix + r"(?:xin\s+)?(?:mở|mo|phát|phat|bật|bat)\s+(?:(?:cho|giup|giúp|anh|chi|chị|em|toi|tôi)\s+)*(?:bài\s+nhạc|bai\s+nhac|bài\s+hát|bai\s+hat|nhạc|nhac|bài|bai)\s+(.+)$",
        prefix + r"(?:xin\s+)?(?:mở|mo|phát|phat|bật|bat)\s+(?:cho\s+)?(?:(?:anh|chi|chị|em|toi|tôi)\s+)*(?:nhạc|nhac|bài|bai)\s+(.+)$"
    ]
    s = " ".join(str(text or "").strip().split())
    for p in patterns:
        m = re.search(p, s, flags=re.I)
        if m:
            q = _normalize_play_query_prefix(m.group(1))
            if q: return q
    return ""

def _looks_like_play_request(text: str, text_n: str) -> bool:
    if _extract_play_query(text): return True
    patterns = (
        r"^(?:(?:em|anh|chi|oi|nhe|giup|hay|xin|vui\s+long)\s+)*(?:(?:co\s+the)\s+)?(?:mo|phat|bat)\s+(?:(?:cho|anh|chi|em|toi)\s+)*(?:nhac|bai)\b",
        r"^(?:(?:em|anh|chi|oi|nhe|giup|hay|xin|vui\s+long)\s+)*(?:(?:co\s+the)\s+)?(?:mo|phat|bat)\s+(?:nhac|bai)\s+(?:(?:cho|anh|chi|em|toi)\b)"
    )
    return any(re.search(p, text_n) for p in patterns)

def parse_music_intent(text: str) -> Optional[Dict[str, Any]]:
    if not text: return None
    t = normalize_text(text)
    if not t: return None

    status = ("nhac dang phat gi", "bai dang phat gi", "dang phat gi", "nhac gi dang phat", "trang thai nhac")
    pause = ("tam dung nhac", "tam dung bai hat", "pause nhac")
    resume = ("phat tiep", "tiep tuc phat", "choi tiep", "tiep tuc nhac")
    stop = ("tat nhac", "dung nhac", "ngung nhac", "stop nhac", "tat bai nhac")

    if _has_any_phrase(t, status): return {"type":"music","action":"status","query":None,"value":None}
    if _has_any_phrase(t, pause): return {"type":"music","action":"pause","query":None,"value":None}
    if _has_any_phrase(t, resume): return {"type":"music","action":"resume","query":None,"value":None}
    if _has_any_phrase(t, stop): return {"type":"music","action":"stop","query":None,"value":None}

    n = _extract_number(t)
    if _has_phrase(t, "tang am luong") and n is not None and _has_any_phrase(t, ("len","toi","muc")):
        return {"type":"music","action":"set_volume","query":None,"value":_clamp_volume(n)}
    if _has_phrase(t, "giam am luong") and n is not None and _has_any_phrase(t, ("xuong","ve","con")):
        return {"type":"music","action":"set_volume","query":None,"value":_clamp_volume(n)}
    if _has_phrase(t, "tang am luong"):
        return {"type":"music","action":"volume_up","query":None,"value":max(1, n or 10)}
    if _has_phrase(t, "giam am luong"):
        return {"type":"music","action":"volume_down","query":None,"value":max(1, n or 10)}
    if _has_phrase(t, "am luong") and n is not None:
        return {"type":"music","action":"set_volume","query":None,"value":_clamp_volume(n)}
    if _looks_like_play_request(text, t):
        return {"type":"music","action":"play","query":_extract_play_query(text) or "nhac hot","value":None}
    return None