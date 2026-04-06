from __future__ import annotations

import html
import re
import urllib.parse
import xml.etree.ElementTree as ET

from services.realtime.base import BaseRealtimeHandler
from services.realtime.types import RealtimeIntent

_PREFERRED_PUBLISHERS = (
    "VnExpress",
    "Tuổi Trẻ",
    "Thanh Niên",
    "Dân trí",
    "Vietnamnet",
    "Người Lao Động",
    "Tiền Phong",
    "Báo Chính phủ",
    "baotintuc.vn",
    "Báo điện tử VTC News",
)

_TITLE_SOURCE_HINTS = (
    "vnexpress",
    "tuổi trẻ",
    "tuoi tre",
    "thanh niên",
    "thanh nien",
    "dân trí",
    "dan tri",
    "vietnamnet",
    "người lao động",
    "nguoi lao dong",
    "tiền phong",
    "tien phong",
    "báo",
    "bao",
    "online",
)
_PREFERRED_PUBLISHER_KEYS = tuple(name.lower() for name in _PREFERRED_PUBLISHERS)
_WHITESPACE_RE = re.compile(r"\s+")
_TITLE_SPLIT_RE = re.compile(r"\s+-\s+")


class NewsRealtimeHandler(BaseRealtimeHandler):
    domain = "news"
    cache_ttl_seconds = 120.0

    def _handle(self, intent: RealtimeIntent):
        topic = self._normalize_topic(intent.entities.get("topic"))
        try:
            items = self._fetch_news(topic)
        except Exception as exc:
            return self._unavailable(
                "Em chưa lấy được tin tức realtime lúc này.",
                data={"error": repr(exc), "topic": topic},
            )

        if not items:
            return self._unavailable(
                "Em chưa tìm thấy tin phù hợp lúc này.",
                data={"topic": topic},
            )

        message = self._build_reply(topic=topic, items=items[:4])
        return self._success(
            message=message,
            data={"topic": topic, "items": items[:5]},
            source="news.google.com/rss",
        )

    def _fetch_news(self, topic: str):
        if topic:
            query = urllib.parse.urlencode({"q": topic, "hl": "vi", "gl": "VN", "ceid": "VN:vi"})
            url = f"https://news.google.com/rss/search?{query}"
        else:
            query = urllib.parse.urlencode({"q": "thoi su Viet Nam hom nay", "hl": "vi", "gl": "VN", "ceid": "VN:vi"})
            url = f"https://news.google.com/rss/search?{query}"
        xml_text = self._http_get_text(url, timeout=10.0)
        root = ET.fromstring(xml_text)
        items = []
        for item in root.iterfind("./channel/item"):
            title = html.unescape((item.findtext("title") or "").strip())
            link = (item.findtext("link") or "").strip()
            source = html.unescape((item.findtext("source") or "").strip())
            title = _WHITESPACE_RE.sub(" ", title)
            if title:
                items.append({"title": self._clean_title(title, source), "link": link, "publisher": source})
        return self._rank_items(items)[:5]

    def _build_reply(self, topic: str, items):
        titles = [str(item.get("title") or "").strip(" .") for item in items if str(item.get("title") or "").strip()]
        if not titles:
            return "Em chưa tìm thấy tin phù hợp lúc này."

        if topic:
            intro = f"Thong tin mới nhất hôm nay "
        else:
            intro = "Thông tin thời sự hôm nay em vừa cập nhật như sau. "

        if len(titles) == 1:
            body = f"Đáng chú ý là {titles[0]}."
        elif len(titles) == 2:
            body = f"Đáng chú ý có {titles[0]}. Ngoài ra còn có {titles[1]}."
        else:
            opening = f"Đáng chú ý có {titles[0]}. "
            middle = " ".join(f"{title}." for title in titles[1:-1])
            closing = f"Thêm một diễn biến khác là {titles[-1]}."
            body = opening + middle + (" " if middle else "") + closing

        return intro + body

    def _clean_title(self, title: str, publisher: str) -> str:
        cleaned = str(title or "").strip()
        source = str(publisher or "").strip()
        if source:
            cleaned = re.sub(rf"\s*-\s*{re.escape(source)}\s*$", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(rf"\s*\|\s*{re.escape(source)}\s*$", "", cleaned, flags=re.IGNORECASE)
        parts = _TITLE_SPLIT_RE.split(cleaned)
        if len(parts) > 1:
            tail = parts[-1].strip().lower()
            if any(hint in tail for hint in _TITLE_SOURCE_HINTS):
                cleaned = " - ".join(parts[:-1]).strip()
        cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip(" .")
        return cleaned

    def _normalize_topic(self, raw_topic) -> str:
        topic = _WHITESPACE_RE.sub(" ", str(raw_topic or "").strip().lower())
        generic_topics = {
            "",
            "moi",
            "nhat",
            "moi nhat",
            "hom nay",
            "tin",
            "tin moi",
            "tin tuc",
            "tin tuc moi nhat",
            "tin moi nhat",
            "thoi su",
            "thoi su hom nay",
            "cap nhat",
            "xem nhanh",
        }
        if topic in generic_topics:
            return ""
        return topic

    def _rank_items(self, items):
        def score(item):
            publisher = str(item.get("publisher") or "").lower()
            preferred_index = len(_PREFERRED_PUBLISHER_KEYS) + 1
            for index, name in enumerate(_PREFERRED_PUBLISHER_KEYS):
                if name in publisher:
                    preferred_index = index
                    break
            return (preferred_index, publisher, item.get("title") or "")

        deduped = []
        seen = set()
        for item in sorted(items, key=score):
            title_key = _WHITESPACE_RE.sub(" ", str(item.get("title") or "").strip().lower())
            if not title_key or title_key in seen:
                continue
            seen.add(title_key)
            deduped.append(item)
        return deduped
