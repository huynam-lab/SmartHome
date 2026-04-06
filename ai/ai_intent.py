import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ai.realtime_intent import parse_realtime_intent
from config import (
    CHAT_FALLBACK_TEXT,
    DEVICE_LATITUDE,
    DEVICE_LOCATION_NAME,
    DEVICE_LONGITUDE,
    GEMINI_CHAT_MAX_TOKENS,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GEMINI_RPM_LIMIT,
    GEMINI_UNAVAILABLE_TEXT,
    WAKE_REPLY_TEXT,
    WEATHER_API_TIMEOUT_SECONDS,
    WEATHER_ENABLED,
    WEATHER_LATITUDE,
    WEATHER_LOCATION_NAME,
    WEATHER_LONGITUDE,
)
from ai.intent_parser import detect_control_request, normalize_text, parse_local_device_intent
from core.event_bus import log_event
from services.realtime.router import get_realtime_router

_request_lock = threading.Lock()
_request_timestamps = deque()
_client_lock = threading.Lock()
_client_cache = None
_weather_cache_lock = threading.Lock()
_weather_cache: Dict[str, Any] = {"timestamp": 0.0, "data": None}
_geocode_cache_lock = threading.Lock()
_geocode_cache: Dict[str, Dict[str, Any]] = {}
_reverse_geocode_cache_lock = threading.Lock()
_reverse_geocode_cache: Dict[str, Dict[str, Any]] = {}

WEATHER_CODE_LABELS = {
    0: "trời quang",
    1: "ít mây",
    2: "có mây rải rác",
    3: "nhiều mây",
    45: "sương mù",
    48: "sương mù đóng băng nhẹ",
    51: "mưa phùn nhẹ",
    53: "mưa phùn vừa",
    55: "mưa phùn dày",
    56: "mưa phùn lạnh nhẹ",
    57: "mưa phùn lạnh dày",
    61: "mưa nhẹ",
    63: "mưa vừa",
    65: "mưa to",
    66: "mưa lạnh nhẹ",
    67: "mưa lạnh to",
    71: "tuyết nhẹ",
    73: "tuyết vừa",
    75: "tuyết dày",
    77: "hạt tuyết",
    80: "mưa rào nhẹ",
    81: "mưa rào vừa",
    82: "mưa rào to",
    85: "mưa tuyết nhẹ",
    86: "mưa tuyết to",
    95: "dông",
    96: "dông kèm mưa đá nhẹ",
    99: "dông kèm mưa đá mạnh",
}


def _log(message: str) -> None:
    print(f"[AI] {message}")


def _extract_response_text(response: Any) -> str:
    text = (getattr(response, "text", "") or "").strip()
    if text:
        return text

    try:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return ""

        content = getattr(candidates[0], "content", None)
        parts = getattr(content, "parts", None) or []
        return "".join((getattr(part, "text", "") or "") for part in parts).strip()
    except Exception:
        return ""


def _extract_finish_reason(response: Any) -> str:
    try:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return ""

        finish_reason = getattr(candidates[0], "finish_reason", None)
        if finish_reason is None:
            return ""

        return str(getattr(finish_reason, "name", finish_reason) or "").strip()
    except Exception:
        return ""


def _extract_usage_metadata(response: Any) -> Dict[str, Any]:
    usage = getattr(response, "usage_metadata", None)
    if not usage:
        return {}

    payload: Dict[str, Any] = {}
    for field in (
        "prompt_token_count",
        "candidates_token_count",
        "total_token_count",
        "thoughts_token_count",
    ):
        value = getattr(usage, field, None)
        if value is not None:
            payload[field] = value
    return payload


def _wait_for_rpm_slot() -> None:
    rpm_limit = max(1, int(GEMINI_RPM_LIMIT))

    while True:
        now = time.time()
        with _request_lock:
            while _request_timestamps and now - _request_timestamps[0] >= 60:
                _request_timestamps.popleft()

            if len(_request_timestamps) < rpm_limit:
                _request_timestamps.append(now)
                return

            wait_seconds = 60 - (now - _request_timestamps[0])

        _log(f"Đạt giới hạn RPM={rpm_limit}, chờ {max(0.1, wait_seconds):.1f}s")
        time.sleep(max(0.1, wait_seconds))


def build_gemini_client() -> Optional[Any]:
    if not GEMINI_API_KEY:
        _log("Thiếu GEMINI_API_KEY")
        return None

    global _client_cache
    if _client_cache is not None:
        return _client_cache

    with _client_lock:
        if _client_cache is not None:
            return _client_cache

        try:
            from google import genai

            _client_cache = genai.Client(api_key=GEMINI_API_KEY)
            _log("Đã khởi tạo Gemini client")
            return _client_cache
        except Exception as exc:
            _log(f"Không khởi tạo được Gemini client: {exc}")
            return None


def _generate_with_gemini(
    prompt: str,
    temperature: float = 0.2,
    max_output_tokens: int = 220,
) -> Dict[str, Any]:
    client = build_gemini_client()
    if not client:
        return {"text": "", "finish_reason": "", "usage_metadata": {}}

    _wait_for_rpm_slot()

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config={
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
            },
        )
        _log(f"Raw response type: {type(response)}")
        text = _extract_response_text(response)
        finish_reason = _extract_finish_reason(response)
        usage_metadata = _extract_usage_metadata(response)
        _log(
            f"Gemini finish_reason={finish_reason or 'unknown'} "
            f"usage={usage_metadata or {}}"
        )
        _log(f"Gemini text: {text!r}")
        return {
            "text": (text or "").strip(),
            "finish_reason": finish_reason,
            "usage_metadata": usage_metadata,
        }
    except Exception as exc:
        _log(f"Lỗi gọi Gemini model={GEMINI_MODEL}: {repr(exc)}")
        return {"text": "", "finish_reason": "", "usage_metadata": {}}


def _strip_code_fence(text: str) -> str:
    if not text:
        return ""

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _build_time_context_text() -> str:
    vn_timezone = timezone(timedelta(hours=7))
    now = datetime.now(vn_timezone)
    weekday_names = {
        0: "Thứ Hai",
        1: "Thứ Ba",
        2: "Thứ Tư",
        3: "Thứ Năm",
        4: "Thứ Sáu",
        5: "Thứ Bảy",
        6: "Chủ Nhật",
    }
    weekday_text = weekday_names.get(now.weekday(), "Hôm nay")
    return (
        f"Thời gian hệ thống hiện tại theo múi giờ Asia/Saigon là {now.strftime('%H:%M:%S ngày %d/%m/%Y')}. "
        f"Hôm nay là {weekday_text}."
    )


def _build_chat_prompt(text: str) -> str:
    return f'''
Bạn là trợ lý nhà thông minh nói tiếng Việt.
Luôn xưng là "em" và gọi người dùng là "anh/chị".
Trả lời tự nhiên, rõ ràng, đủ ý, không cụt câu, không bỏ dở nửa câu.
Trả lời trọn vẹn trong một lần. Nếu câu hỏi rộng, hãy tóm tắt gọn nhưng vẫn đầy đủ ý chính.
Không nhắc đến JSON, schema, intent, command, type hay phân loại nội bộ.
Nếu người dùng hỏi thông tin chung thì trả lời trong khả năng của em một cách tự nhiên.
Nếu thông tin cần dữ liệu thời gian thực mà em không chắc, hãy nói rõ điều đó ngắn gọn và lịch sự.
Khi câu hỏi liên quan đến ngày, giờ, hôm nay, thứ mấy hoặc thời điểm hiện tại, bắt buộc ưu tiên dùng đúng dữ liệu thời gian hệ thống được cung cấp bên dưới, không tự suy đoán.

Ngữ cảnh thời gian hệ thống: {_build_time_context_text()}

Người dùng nói: {text}
Hãy trả lời trực tiếp cho người dùng bằng tiếng Việt tự nhiên.
'''.strip()


def _is_weather_question(text: str) -> bool:
    text_n = normalize_text(text)
    if not text_n:
        return False

    weather_phrases = (
        "thoi tiet",
        "nhiet do",
        "troi",
        "co mua",
        "mua khong",
        "nong qua",
        "lanh qua",
    )
    return any(phrase in text_n for phrase in weather_phrases)


def _extract_weather_location(text: str) -> str:
    raw_text = " ".join(str(text or "").strip().split())
    text_n = normalize_text(text)
    if not text_n:
        return ""

    location_patterns = [
        r"(?:o|tai)\s+([a-z0-9\s]+?)(?:\s+(?:hom nay|bay gio|luc nay|nhu the nao|bao nhieu|co mua khong)|$)",
        r"thoi tiet\s+([a-z0-9\s]+?)(?:\s+(?:hom nay|bay gio|luc nay|nhu the nao|bao nhieu|co mua khong)|$)",
    ]
    stop_words = {
        "hom",
        "nay",
        "bay",
        "gio",
        "hien",
        "luc",
        "nao",
        "nhu",
        "the",
        "ra",
        "sao",
        "bao",
        "nhieu",
        "co",
        "mua",
        "khong",
        "thoi",
        "tiet",
    }

    for pattern in location_patterns:
        match = re.search(pattern, text_n)
        if not match:
            continue
        candidate = " ".join(word for word in match.group(1).split() if word not in stop_words).strip()
        candidate = re.sub(r"^(?:o|tai)\s+", "", candidate).strip()
        if candidate:
            return candidate
    raw_patterns = [
        r"(?:thời\s+tiết|thoi\s+tiet)\s+(?:ở|o|tại|tai)\s+(.+?)(?:\s+(?:hôm\s+nay|hom\s+nay|bây\s+giờ|bay\s+gio|lúc\s+này|luc\s+nay|như\s+thế\s+nào|nhu\s+the\s+nao|bao\s+nhiêu|bao\s+nhieu|có\s+mưa\s+không|co\s+mua\s+khong)|$)",
        r"(?:thời\s+tiết|thoi\s+tiet)\s+(.+?)(?:\s+(?:hôm\s+nay|hom\s+nay|bây\s+giờ|bay\s+gio|lúc\s+này|luc\s+nay|như\s+thế\s+nào|nhu\s+the\s+nao|bao\s+nhiêu|bao\s+nhieu|có\s+mưa\s+không|co\s+mua\s+khong)|$)",
    ]
    for pattern in raw_patterns:
        match = re.search(pattern, raw_text, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = " ".join(str(match.group(1) or "").split()).strip(" ,.!?;:")
        if candidate:
            return candidate
    return ""


def _build_weather_location_queries(location_query: str) -> List[str]:
    base_query = " ".join(str(location_query or "").strip().split())
    if not base_query:
        return []

    variants = [base_query]
    normalized_query = normalize_text(base_query)
    if normalized_query and normalized_query not in variants:
        variants.append(normalized_query)

    words = normalized_query.split()
    if len(words) >= 3:
        admin2 = " ".join(words[:-2]).strip()
        admin1 = " ".join(words[-2:]).strip()
        if admin2 and admin1:
            variants.append(f"{admin2}, {admin1}")

    alias_pairs = {
        "ha noi": ["Ha Noi", "Hanoi"],
        "hanoi": ["Ha Noi", "Hanoi"],
        "ho chi minh": ["Ho Chi Minh", "Ho Chi Minh City"],
        "ho chi minh city": ["Ho Chi Minh", "Ho Chi Minh City"],
        "tp hcm": ["Ho Chi Minh", "Ho Chi Minh City"],
        "tphcm": ["Ho Chi Minh", "Ho Chi Minh City"],
        "sai gon": ["Ho Chi Minh", "Sai Gon"],
        "da nang": ["Da Nang"],
        "can tho": ["Can Tho"],
        "hai phong": ["Hai Phong"],
    }
    for needle, replacements in alias_pairs.items():
        if needle not in normalized_query:
            continue
        for replacement in replacements:
            variants.append(re.sub(re.escape(needle), replacement, normalized_query, flags=re.IGNORECASE))

    deduped: List[str] = []
    for item in variants:
        cleaned = " ".join(str(item or "").strip().split()).strip(" ,.!?;:")
        if cleaned and cleaned not in deduped:
            deduped.append(cleaned)
    return deduped


def _geocode_with_open_meteo(location_queries: List[str]) -> Dict[str, Any]:
    for query_text in location_queries:
        query = urllib.parse.urlencode(
            {
                "name": query_text,
                "count": 1,
                "language": "vi",
                "format": "json",
            }
        )
        url = f"https://geocoding-api.open-meteo.com/v1/search?{query}"

        with urllib.request.urlopen(url, timeout=max(1.0, WEATHER_API_TIMEOUT_SECONDS)) as response:
            payload = response.read().decode("utf-8")
        import json

        data = json.loads(payload)
        results = data.get("results") or []
        if not results:
            continue

        first = results[0]
        return {
            "name": first.get("name") or query_text.strip(),
            "latitude": first.get("latitude"),
            "longitude": first.get("longitude"),
            "admin1": first.get("admin1") or "",
            "country": first.get("country") or "",
            "is_default": False,
        }
    return {}


def _geocode_with_nominatim(location_queries: List[str]) -> Dict[str, Any]:
    for query_text in location_queries:
        query = urllib.parse.urlencode(
            {
                "q": query_text,
                "format": "jsonv2",
                "limit": 1,
                "accept-language": "vi",
            }
        )
        url = f"https://nominatim.openstreetmap.org/search?{query}"
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "smart-home-weather/1.0",
                "Accept": "application/json",
            },
        )

        with urllib.request.urlopen(request, timeout=max(1.0, WEATHER_API_TIMEOUT_SECONDS)) as response:
            payload = response.read().decode("utf-8")
        import json

        data = json.loads(payload)
        if not data:
            continue

        first = data[0]
        address = first.get("address") or {}
        name = (
            address.get("city_district")
            or address.get("suburb")
            or address.get("town")
            or address.get("city")
            or address.get("county")
            or query_text.strip()
        )
        return {
            "name": name,
            "latitude": first.get("lat"),
            "longitude": first.get("lon"),
            "admin1": address.get("state") or address.get("region") or "",
            "country": address.get("country") or "",
            "is_default": False,
        }
    return {}


def _coerce_location_context(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    safe_context = context or {}
    latitude = safe_context.get("latitude")
    longitude = safe_context.get("longitude")
    try:
        if latitude is None or longitude is None:
            return {}
        return {
            "name": str(safe_context.get("name") or "").strip() or "vị trí hiện tại của anh/chị",
            "latitude": float(latitude),
            "longitude": float(longitude),
            "is_default": True,
            "default_source": str(safe_context.get("source") or "browser").strip().lower() or "browser",
        }
    except Exception:
        return {}


def _reverse_geocode_location(location: Dict[str, Any]) -> Dict[str, Any]:
    latitude = location.get("latitude")
    longitude = location.get("longitude")
    if latitude is None or longitude is None:
        return location

    cache_key = f"{round(float(latitude), 3)}:{round(float(longitude), 3)}"
    with _reverse_geocode_cache_lock:
        cached = _reverse_geocode_cache.get(cache_key)
        if cached:
            return {**location, **cached}

    query = urllib.parse.urlencode(
        {
            "format": "jsonv2",
            "lat": latitude,
            "lon": longitude,
            "zoom": 10,
            "accept-language": "vi",
        }
    )
    url = f"https://nominatim.openstreetmap.org/reverse?{query}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "smart-home-weather/1.0",
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=max(1.0, WEATHER_API_TIMEOUT_SECONDS)) as response:
            payload = response.read().decode("utf-8")
        import json

        data = json.loads(payload)
        address = data.get("address") or {}
        enriched = {
            "name": address.get("city")
            or address.get("town")
            or address.get("county")
            or address.get("state")
            or location.get("name")
            or "vị trí hiện tại của anh/chị",
            "admin1": address.get("state") or address.get("region") or "",
            "country": address.get("country") or "",
        }
        with _reverse_geocode_cache_lock:
            _reverse_geocode_cache[cache_key] = enriched
        return {**location, **enriched}
    except Exception as exc:
        _log(f"Lỗi reverse geocoding tọa độ thời tiết '{cache_key}': {repr(exc)}")
        return location


def _resolve_weather_location(location_query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    normalized_query = normalize_text(location_query)
    if not normalized_query:
        context_location = _coerce_location_context(context)
        if context_location:
            return _reverse_geocode_location(context_location)
        return {
            "name": DEVICE_LOCATION_NAME,
            "latitude": DEVICE_LATITUDE,
            "longitude": DEVICE_LONGITUDE,
            "is_default": True,
            "default_source": "device",
        }

    with _geocode_cache_lock:
        cached = _geocode_cache.get(normalized_query)
        if cached:
            return cached

    location_queries = _build_weather_location_queries(location_query)

    try:
        resolved = _geocode_with_open_meteo(location_queries)
        if not resolved:
            resolved = _geocode_with_nominatim(location_queries)
        if resolved:
            with _geocode_cache_lock:
                _geocode_cache[normalized_query] = resolved
            return resolved
    except Exception as exc:
        _log(f"Lỗi geocoding địa điểm thời tiết '{location_query}': {repr(exc)}")

    fallback = {
        "name": DEVICE_LOCATION_NAME,
        "latitude": DEVICE_LATITUDE,
        "longitude": DEVICE_LONGITUDE,
        "is_default": True,
        "default_source": "device",
    }
    with _geocode_cache_lock:
        _geocode_cache[normalized_query] = fallback
    return fallback


def _fetch_weather_data(location: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not WEATHER_ENABLED:
        return None

    latitude = location.get("latitude")
    longitude = location.get("longitude")
    if latitude is None or longitude is None:
        return None

    cache_key = f"{round(float(latitude), 4)}:{round(float(longitude), 4)}"
    now = time.time()
    with _weather_cache_lock:
        cached_bucket = _weather_cache.get(cache_key) or {}
        cached = cached_bucket.get("data")
        cached_at = float(cached_bucket.get("timestamp") or 0.0)
        if cached and now - cached_at < 600:
            return cached

    query = urllib.parse.urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "Asia/Bangkok",
            "forecast_days": 1,
        }
    )
    url = f"https://api.open-meteo.com/v1/forecast?{query}"

    try:
        with urllib.request.urlopen(url, timeout=max(1.0, WEATHER_API_TIMEOUT_SECONDS)) as response:
            payload = response.read().decode("utf-8")
        import json

        data = json.loads(payload)
        current = data.get("current") or {}
        daily = data.get("daily") or {}
        result = {
            "temperature": current.get("temperature_2m"),
            "apparent_temperature": current.get("apparent_temperature"),
            "humidity": current.get("relative_humidity_2m"),
            "wind_speed": current.get("wind_speed_10m"),
            "weather_code": current.get("weather_code"),
            "temp_max": (daily.get("temperature_2m_max") or [None])[0],
            "temp_min": (daily.get("temperature_2m_min") or [None])[0],
            "rain_probability": (daily.get("precipitation_probability_max") or [None])[0],
            "location_name": location.get("name") or WEATHER_LOCATION_NAME,
            "location_admin1": location.get("admin1") or "",
            "location_country": location.get("country") or "",
            "used_default_location": bool(location.get("is_default")),
            "default_source": location.get("default_source") or "",
        }
        with _weather_cache_lock:
            _weather_cache[cache_key] = {"timestamp": now, "data": result}
        return result
    except Exception as exc:
        _log(f"Lỗi lấy thời tiết realtime: {repr(exc)}")
        return None


def _build_weather_reply_text(weather: Dict[str, Any]) -> str:
    temperature = weather.get("temperature")
    apparent_temperature = weather.get("apparent_temperature")
    humidity = weather.get("humidity")
    wind_speed = weather.get("wind_speed")
    weather_code = weather.get("weather_code")
    temp_max = weather.get("temp_max")
    temp_min = weather.get("temp_min")
    rain_probability = weather.get("rain_probability")

    weather_label = WEATHER_CODE_LABELS.get(weather_code, "thời tiết khá ổn định")

    location_name = weather.get("location_name") or WEATHER_LOCATION_NAME
    location_admin1 = weather.get("location_admin1") or ""
    location_country = weather.get("location_country") or ""
    default_source = weather.get("default_source") or ""
    place_text = location_name
    if location_admin1 and location_admin1.lower() not in location_name.lower():
        place_text = f"{location_name}, {location_admin1}"
    elif location_country and location_country.lower() not in location_name.lower():
        place_text = f"{location_name}, {location_country}"

    prefix = "Thời tiết hiện tại ở"
    if weather.get("used_default_location") and default_source == "device":
        prefix = "Thời tiết hiện tại tại vị trí thiết bị ở"

    parts = [f"{prefix} {place_text} đang {weather_label}"]
    if temperature is not None:
        parts.append(f"nhiệt độ khoảng {round(float(temperature))} độ C")
    if apparent_temperature is not None:
        parts.append(f"cảm giác như {round(float(apparent_temperature))} độ")
    if humidity is not None:
        parts.append(f"độ ẩm khoảng {round(float(humidity))}%")
    if wind_speed is not None:
        parts.append(f"gió khoảng {round(float(wind_speed), 1)} km/h")

    reply = ", ".join(parts) + "."

    extras = []
    if temp_min is not None and temp_max is not None:
        extras.append(f"Nhiệt độ hôm nay dự kiến từ {round(float(temp_min))} đến {round(float(temp_max))} độ C")
    if rain_probability is not None:
        extras.append(f"khả năng mưa cao nhất khoảng {round(float(rain_probability))}%")

    if extras:
        reply += " " + ", ".join(extras) + "."
    return reply


def build_weather_reply(text: str, context: Optional[Dict[str, Any]] = None) -> str:
    requested_location = _extract_weather_location(text)
    resolved_location = _resolve_weather_location(requested_location, context=context)
    weather = _fetch_weather_data(resolved_location)
    if weather:
        if not requested_location and weather.get("used_default_location"):
            return _build_weather_reply_text(weather)

        if requested_location and weather.get("used_default_location"):
            reply = _build_weather_reply_text(weather)
            return (
                f"Em chưa xác định chính xác địa điểm '{requested_location}', nên đang dùng dữ liệu mặc định ở "
                f"{DEVICE_LOCATION_NAME}. {reply}"
            )
        return _build_weather_reply_text(weather)

    if GEMINI_API_KEY:
        fallback_prompt = (
            f"{_build_chat_prompt(text)}\n\n"
            "Lưu ý thêm: Em không lấy được dữ liệu thời tiết realtime từ API ngoài."
            " Hãy nói rõ là em chưa truy cập được dữ liệu thời tiết hiện tại,"
            " nhưng vẫn trả lời lịch sự và trọn ý."
        )
        output_text = _generate_with_gemini(
            prompt=fallback_prompt,
            temperature=0.4,
            max_output_tokens=max(int(GEMINI_CHAT_MAX_TOKENS), 512),
        )
        output_text = str(output_text.get("text") or "").strip()
        if output_text:
            return _postprocess_ai_text(output_text)

    return (
        f"Em chưa lấy được dữ liệu thời tiết hiện tại cho {resolved_location.get('name') or DEVICE_LOCATION_NAME} lúc này. "
        "Anh/chị thử lại sau giúp em ạ."
    )


def _looks_incomplete_ai_text(text: str) -> bool:
    if not text:
        return True

    stripped = str(text).strip()
    if not stripped:
        return True

    if stripped.endswith((":", ",", ";", "-", "–", "(", "[", "{")):
        return True

    dangling_words = {
        "va",
        "nhung",
        "hoac",
        "vi",
        "neu",
        "de",
        "la",
        "gom",
        "nhu",
        "rang",
    }
    last_word = re.sub(r"[^a-zA-Z0-9à-ỹÀ-ỸđĐ]+", "", stripped.split()[-1]).lower()
    if last_word in dangling_words:
        return True

    if stripped.count("(") > stripped.count(")"):
        return True

    return False


def try_handle_realtime_query(text: str) -> Optional[Dict[str, Any]]:
    intent = parse_realtime_intent(text)
    if not intent:
        return None

    router = get_realtime_router()
    result = router.handle(intent)
    if not result:
        return None

    _log(f"Realtime intent matched: domain={intent.domain} entities={intent.entities}")
    return result


def _response_needs_retry(response_payload: Dict[str, Any]) -> bool:
    text = str(response_payload.get("text") or "").strip()
    if not text:
        return True

    finish_reason = str(response_payload.get("finish_reason") or "").strip().upper()
    if finish_reason in {"MAX_TOKENS", "SAFETY", "RECITATION", "OTHER"}:
        return True

    return _looks_incomplete_ai_text(text)


def build_chat_reply_with_ai(text: str, context: Optional[Dict[str, Any]] = None) -> str:
    if not text:
        return CHAT_FALLBACK_TEXT

    realtime_result = try_handle_realtime_query(text)
    if realtime_result:
        return str(realtime_result.get("message") or "").strip() or CHAT_FALLBACK_TEXT

    if _is_weather_question(text):
        return build_weather_reply(text, context=context)

    if not GEMINI_API_KEY:
        return GEMINI_UNAVAILABLE_TEXT

    max_tokens = max(int(GEMINI_CHAT_MAX_TOKENS), 512)
    response_payload = _generate_with_gemini(
        prompt=_build_chat_prompt(text),
        temperature=0.6,
        max_output_tokens=max_tokens,
    )
    output_text = str(response_payload.get("text") or "").strip()
    if _response_needs_retry(response_payload):
        retry_prompt = (
            f"{_build_chat_prompt(text)}\n\n"
            "Yêu cầu bổ sung: Hãy trả lời lại thành một đoạn hoàn chỉnh, kết thúc trọn ý,"
            " không bị dở giữa câu."
        )
        retry_payload = _generate_with_gemini(
            prompt=retry_prompt,
            temperature=0.4,
            max_output_tokens=min(max_tokens * 2, 1024),
        )
        retry_text = str(retry_payload.get("text") or "").strip()
        if retry_text:
            output_text = retry_text
    if output_text:
        return _postprocess_ai_text(output_text)
    return GEMINI_UNAVAILABLE_TEXT


def build_wake_reply_with_ai() -> str:
    return WAKE_REPLY_TEXT


def _build_safe_chat_result(text: str, reply: str = "", context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    final_reply = _postprocess_ai_text(reply) if reply else ""
    if not final_reply:
        final_reply = build_chat_reply_with_ai(text, context=context)
    if not final_reply:
        final_reply = GEMINI_UNAVAILABLE_TEXT if GEMINI_API_KEY else CHAT_FALLBACK_TEXT
    return {
        "type": "chat",
        "device": None,
        "action": None,
        "reply": final_reply,
    }


def classify_user_request(text: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not text:
        return {
            "type": "chat",
            "device": None,
            "action": None,
            "reply": CHAT_FALLBACK_TEXT,
        }

    control_info = detect_control_request(text)
    if control_info.get("is_control_request"):
        local_result = parse_local_device_intent(text)
        if local_result:
            return local_result

        log_event(
            source="ai-intent",
            level="warning",
            message="Câu điều khiển parse local thất bại, không fallback sang AI chat xác nhận hành động",
            payload={"text": text, "control_info": control_info},
        )
        return {
            "type": "control_parse_failed",
            "device": None,
            "action": control_info.get("action"),
            "reply": None,
            "reason": "control_request_parse_failed",
            "control_info": control_info,
        }

    local_result = parse_local_device_intent(text)
    if local_result:
        return local_result

    return {
        "type": "chat",
        "device": None,
        "action": None,
        "reply": build_chat_reply_with_ai(text, context=context),
    }


def classify_user_request_with_ai(text: str) -> Dict[str, Any]:
    """Giữ tương thích API cũ, nhưng chuyển sang luồng classify local trước."""
    return classify_user_request(text)


def _postprocess_ai_text(text: str) -> str:
    if not text:
        return ""

    cleaned = " ".join(str(text).strip().split())
    cleaned = _strip_code_fence(cleaned)
    if not cleaned:
        return ""

    cleaned = re.sub(r'^["\']+|["\']+$', "", cleaned).strip()
    if not cleaned:
        return ""

    if cleaned.endswith((":", ",", "-", "–")):
        cleaned = cleaned[:-1].rstrip()

    if cleaned and not cleaned.endswith((".", "!", "?", "…")):
        cleaned += "."

    return cleaned
