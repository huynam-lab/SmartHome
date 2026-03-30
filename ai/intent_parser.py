import re
import unicodedata
from typing import Any, Dict, List, Optional

from controller.device_registry import get_registry
from core.event_bus import log_event


Intent = Dict[str, str]

CONTROL_ACTION_SYNONYMS = {
    "on": ["bat", "mo", "khoi dong"],
    "off": ["tat", "dong", "ngat", "dung"],
}

COMMAND_PREFIX_WORDS = {
    "em",
    "anh",
    "chi",
    "cho",
    "giup",
    "dum",
    "lam",
    "on",
    "nho",
    "hay",
}

COMMAND_TAIL_WORDS = {
    "giup",
    "dum",
    "voi",
    "nhe",
    "di",
    "ngay",
    "luon",
}

DEVICE_REFERENCE_FILLER_WORDS = {
    "o",
    "tai",
    "trong",
    "ngoai",
    "tren",
    "duoi",
    "ben",
    "canh",
    "khu",
    "vuc",
    "phia",
    "cua",
}

INFO_QUESTION_PHRASES = [
    "la gi",
    "the nao",
    "tai sao",
    "vi sao",
    "bao nhieu",
    "may gio",
    "khi nao",
    "co khong",
    "chua",
    "dang",
    "hay khong",
    "phai khong",
]

TIMER_ONE_MINUTE_PHRASES = [
    "1 phut",
    "mot phut",
]


def normalize_text(text: str) -> str:
    """Chuẩn hóa text để match ổn định với tiếng Việt có/không dấu."""
    if not text:
        return ""

    normalized = str(text).lower().strip().replace("đ", "d")
    normalized = unicodedata.normalize("NFD", normalized)
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    normalized = " ".join(normalized.split())
    return normalized


def _has_phrase(text: str, phrase: str) -> bool:
    phrase_n = normalize_text(phrase)
    if not text or not phrase_n:
        return False
    pattern = rf"(?<![a-z0-9]){re.escape(phrase_n)}(?![a-z0-9])"
    return re.search(pattern, text) is not None


def _extract_action(text_n: str) -> Optional[str]:
    matched_actions: List[str] = []
    for action, keywords in CONTROL_ACTION_SYNONYMS.items():
        if any(_has_phrase(text_n, keyword) for keyword in keywords):
            matched_actions.append(action)

    matched_actions = list(dict.fromkeys(matched_actions))
    if len(matched_actions) == 1:
        return matched_actions[0]
    return None


def _has_one_minute_timer_phrase(text_n: str) -> bool:
    return any(_has_phrase(text_n, phrase) for phrase in TIMER_ONE_MINUTE_PHRASES)


def _extract_requested_duration_seconds(text_n: str) -> Optional[int]:
    minute_match = re.search(r"(\d+)\s+phut", text_n)
    if minute_match:
        return int(minute_match.group(1)) * 60

    if _has_phrase(text_n, "mot phut"):
        return 60

    hour_match = re.search(r"(\d+)\s+gio", text_n)
    if hour_match:
        return int(hour_match.group(1)) * 3600

    return None


def _extract_requested_temperature(text_n: str) -> Optional[int]:
    temp_match = re.search(r"(\d+)\s+do", text_n)
    if temp_match:
        return int(temp_match.group(1))
    return None


def _find_semantic_action(device_id: str, text_n: str) -> Optional[str]:
    registry = get_registry()
    registry.reload()
    device_config = registry.get_device(device_id) or {}
    actions_map = dict(device_config.get("actions") or {})
    duration_seconds = _extract_requested_duration_seconds(text_n)
    temperature_c = _extract_requested_temperature(text_n)

    for action_key, action_config in actions_map.items():
        semantic = action_config.get("semantic") or {}
        if not isinstance(semantic, dict):
            continue

        if duration_seconds is not None and semantic.get("operation") == "off_after":
            try:
                if int(semantic.get("duration_seconds")) == duration_seconds:
                    return str(action_key or "").strip()
            except Exception:
                pass

        if temperature_c is not None and semantic.get("operation") == "set_temperature":
            try:
                if int(semantic.get("temperature_c")) == temperature_c:
                    return str(action_key or "").strip()
            except Exception:
                pass

    return None


def _resolve_contextual_action(device_id: str, base_action: str, text_n: str) -> str:
    if not device_id or not base_action:
        return base_action

    semantic_action = _find_semantic_action(device_id, text_n)
    if semantic_action:
        return semantic_action

    registry = get_registry()
    registry.reload()
    device_config = registry.get_device(device_id) or {}
    actions_map = dict(device_config.get("actions") or {})

    if _has_one_minute_timer_phrase(text_n):
        for timer_action in (
            "timer.off_after_1_min",
            "timer.1m.off",
            "off_after_1_min",
            "1_min_off",
        ):
            if timer_action in actions_map:
                return timer_action

    return base_action


def _contains_any_phrase(text_n: str, phrases: List[str]) -> bool:
    return any(_has_phrase(text_n, phrase) for phrase in phrases)


def _has_device_phrase(text_n: str, phrase: str) -> bool:
    if _has_phrase(text_n, phrase):
        return True

    phrase_n = normalize_text(phrase)
    phrase_words = phrase_n.split()
    text_words = normalize_text(text_n).split()
    if not phrase_words or not text_words:
        return False

    first_word = phrase_words[0]
    expected_tail = phrase_words[1:]
    max_gap = 2

    for start_index, word in enumerate(text_words):
        if word != first_word:
            continue

        cursor = start_index + 1
        matched = True
        for expected_word in expected_tail:
            gap_count = 0
            while cursor < len(text_words) and text_words[cursor] != expected_word:
                if text_words[cursor] not in DEVICE_REFERENCE_FILLER_WORDS:
                    matched = False
                    break
                gap_count += 1
                if gap_count > max_gap:
                    matched = False
                    break
                cursor += 1

            if not matched or cursor >= len(text_words):
                matched = False
                break

            cursor += 1

        if matched:
            return True

    return False


def _extract_action_keywords() -> List[str]:
    keywords: List[str] = []
    for items in CONTROL_ACTION_SYNONYMS.values():
        for item in items:
            if item not in keywords:
                keywords.append(item)
    return keywords


def _has_command_starter(text_n: str) -> bool:
    if not text_n:
        return False

    words = text_n.split()
    action_keywords = _extract_action_keywords()
    if any(_has_phrase(" ".join(words[:2]), keyword) for keyword in action_keywords):
        return True

    head_window = words[:5]
    for index, word in enumerate(head_window):
        if word not in COMMAND_PREFIX_WORDS:
            continue
        trailing_text = " ".join(head_window[index + 1 :])
        if trailing_text and any(_has_phrase(trailing_text, keyword) for keyword in action_keywords):
            return True
    return False


def _has_command_tail(text_n: str) -> bool:
    words = text_n.split()
    if not words:
        return False
    return any(word in COMMAND_TAIL_WORDS for word in words[-3:])


def _looks_like_information_question(text_n: str, original_text: str) -> bool:
    if not text_n:
        return False

    if "?" in (original_text or "") and not _has_command_starter(text_n):
        return True

    if _contains_any_phrase(text_n, INFO_QUESTION_PHRASES) and not _has_command_starter(text_n):
        return True

    question_starters = ("gi", "sao", "tai", "vi", "bao", "may", "khi", "nao", "ai")
    first_word = text_n.split()[0] if text_n.split() else ""
    return first_word in question_starters


def detect_control_request(user_text: str) -> Dict[str, Any]:
    """Nhận diện đây có phải câu điều khiển thiết bị hay không."""
    text_n = normalize_text(user_text)
    matched_keywords: List[str] = []
    for keywords in CONTROL_ACTION_SYNONYMS.values():
        for keyword in keywords:
            if _has_phrase(text_n, keyword):
                matched_keywords.append(keyword)

    action = _extract_action(text_n)
    has_command_starter = _has_command_starter(text_n)
    has_command_tail = _has_command_tail(text_n)
    is_information_question = _looks_like_information_question(text_n, user_text)
    is_control = bool(action and (has_command_starter or has_command_tail))
    if is_information_question and not has_command_starter:
        is_control = False
    result = {
        "is_control_request": is_control,
        "normalized_text": text_n,
        "matched_keywords": list(dict.fromkeys(matched_keywords)),
        "action": action,
        "ambiguous_action": bool(matched_keywords) and action is None and (has_command_starter or has_command_tail),
        "has_command_starter": has_command_starter,
        "has_command_tail": has_command_tail,
        "is_information_question": is_information_question,
    }
    log_event(source="intent-parser", level="info", message="detect_control_request", payload=result)
    return result


def _build_device_candidates() -> List[Dict[str, str]]:
    registry = get_registry()
    registry.reload()
    candidates: List[Dict[str, str]] = []

    for device in registry.list_devices():
        device_id = device.get("id") or ""
        names = [device_id, device.get("name") or ""] + list(device.get("aliases") or [])
        unique_terms = []
        for item in names:
            normalized = normalize_text(item)
            if normalized and normalized not in unique_terms:
                unique_terms.append(normalized)

        for term in unique_terms:
            candidates.append(
                {
                    "device_id": device_id,
                    "term": term,
                    "display_name": device.get("name") or device_id,
                }
            )
    candidates.sort(key=lambda item: len(item["term"]), reverse=True)
    return candidates


def _build_action_phrase_candidates() -> List[Dict[str, str]]:
    registry = get_registry()
    registry.reload()
    candidates: List[Dict[str, str]] = []

    for device in registry.list_devices():
        device_id = device.get("id") or ""
        display_name = device.get("name") or device_id
        actions_map = dict(device.get("actions") or {})
        for action_key, action_config in actions_map.items():
            phrases = action_config.get("phrases") or []
            for phrase in phrases:
                normalized_phrase = normalize_text(phrase)
                if not normalized_phrase:
                    continue
                candidates.append(
                    {
                        "device_id": device_id,
                        "action": str(action_key or "").strip(),
                        "phrase": normalized_phrase,
                        "display_name": display_name,
                    }
                )

    candidates.sort(key=lambda item: len(item["phrase"]), reverse=True)
    return candidates


def parse_learned_action_reference(text: str) -> Dict[str, Any]:
    text_n = normalize_text(text)
    matches: List[Dict[str, str]] = []

    for candidate in _build_action_phrase_candidates():
        if _has_phrase(text_n, candidate["phrase"]):
            matches.append(candidate)

    if matches:
        best_phrase_length = max(len(item["phrase"]) for item in matches)
        matches = [item for item in matches if len(item["phrase"]) == best_phrase_length]

    deduped: List[Dict[str, str]] = []
    seen_keys: List[str] = []
    for item in matches:
        key = f"{item['device_id']}::{item['action']}"
        if key in seen_keys:
            continue
        seen_keys.append(key)
        deduped.append(item)

    result = {
        "normalized_text": text_n,
        "matched_actions": deduped,
        "device_id": deduped[0]["device_id"] if len(deduped) == 1 else None,
        "device_name": deduped[0]["display_name"] if len(deduped) == 1 else None,
        "action": deduped[0]["action"] if len(deduped) == 1 else None,
        "ambiguous": len(deduped) > 1,
    }
    log_event(source="intent-parser", level="info", message="parse_learned_action_reference", payload=result)
    return result


def _fallback_generic_device_reference(text_n: str) -> List[Dict[str, str]]:
    registry = get_registry()
    registry.reload()

    generic_terms = {
        "light": ["den"],
        "air_conditioner": ["dieu hoa", "may lanh"],
        "smart_switch": ["cong tac"],
    }

    for device_kind, terms in generic_terms.items():
        if not any(_has_device_phrase(text_n, term) for term in terms):
            continue

        candidates = []
        for device in registry.list_devices():
            if str(device.get("device_kind") or device.get("type") or "").strip().lower() != device_kind:
                continue
            candidates.append(
                {
                    "device_id": device.get("id") or "",
                    "term": terms[0],
                    "display_name": device.get("name") or device.get("id") or "",
                }
            )

        if len(candidates) == 1 and candidates[0]["device_id"]:
            return candidates

    return []


def parse_device_reference(text: str) -> Dict[str, Any]:
    """Tìm thiết bị theo id, name, alias trong JSON."""
    text_n = normalize_text(text)
    matches: List[Dict[str, str]] = []

    for candidate in _build_device_candidates():
        if _has_device_phrase(text_n, candidate["term"]):
            matches.append(candidate)

    if not matches:
        matches = _fallback_generic_device_reference(text_n)

    seen_devices: List[str] = []
    resolved_matches: List[Dict[str, str]] = []
    for item in matches:
        if item["device_id"] not in seen_devices:
            seen_devices.append(item["device_id"])
            resolved_matches.append(item)

    result = {
        "normalized_text": text_n,
        "matched_devices": resolved_matches,
        "device_id": resolved_matches[0]["device_id"] if len(resolved_matches) == 1 else None,
        "device_name": resolved_matches[0]["display_name"] if len(resolved_matches) == 1 else None,
        "ambiguous": len(resolved_matches) > 1,
    }
    log_event(source="intent-parser", level="info", message="parse_device_reference", payload=result)
    return result


def parse_intent(text: str) -> Optional[Intent]:
    """Parse intent local từ device map JSON, không hardcode alias."""
    if not text:
        return None

    text_n = normalize_text(text)
    learned_action_info = parse_learned_action_reference(text)
    if learned_action_info.get("device_id") and learned_action_info.get("action") and not learned_action_info.get("ambiguous"):
        intent = {
            "device": learned_action_info.get("device_id"),
            "action": learned_action_info.get("action"),
        }
        log_event(
            source="intent-parser",
            level="success",
            message="Parse local intent thành công từ câu mẫu đã học",
            payload=intent,
        )
        return intent

    control_info = detect_control_request(text)
    device_info = parse_device_reference(text)
    action = control_info.get("action")
    inferred_embedded_command = bool(
        not control_info.get("is_control_request")
        and action
        and not control_info.get("ambiguous_action")
        and not control_info.get("is_information_question")
        and device_info.get("device_id")
    )

    if not control_info.get("is_control_request") and not inferred_embedded_command:
        return None

    if control_info.get("ambiguous_action"):
        log_event(
            source="intent-parser",
            level="warning",
            message="Phát hiện câu điều khiển nhưng action mơ hồ",
            payload=control_info,
        )
        return None

    if device_info.get("ambiguous"):
        log_event(
            source="intent-parser",
            level="warning",
            message="Phát hiện nhiều thiết bị khớp trong cùng câu lệnh",
            payload=device_info,
        )
        return None

    device_id = device_info.get("device_id")
    if not device_id or not action:
        log_event(
            source="intent-parser",
            level="warning",
            message="Không parse được device/action từ câu điều khiển",
            payload={"control_info": control_info, "device_info": device_info},
        )
        return None

    resolved_action = _resolve_contextual_action(device_id, action, text_n)
    intent = {"device": device_id, "action": resolved_action}
    log_event(
        source="intent-parser",
        level="success",
        message="Parse local intent thành công",
        payload={**intent, "inferred_embedded_command": inferred_embedded_command},
    )
    return intent


def parse_local_device_intent(text: str) -> Optional[Dict[str, Any]]:
    """Trả kết quả command local nếu parse thành công hoàn toàn."""
    intent = parse_intent(text)
    if not intent:
        return None

    return {
        "type": "command",
        "device": intent.get("device"),
        "action": intent.get("action"),
        "reply": None,
    }


def is_explicit_device_command(text: str) -> bool:
    info = detect_control_request(text)
    return bool(info.get("is_control_request"))
