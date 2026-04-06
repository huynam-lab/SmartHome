import re
import unicodedata
from typing import Any, Dict, List, Optional

from controller.device_registry import get_registry
from core.event_bus import log_event


Intent = Dict[str, str]

CONTROL_ACTION_SYNONYMS = {
    "on": ["bat", "mo", "khoi dong", "bat len", "mo len"],
    "off": ["tat", "dong", "ngat", "dung", "tat di", "ngat di"],
}

ACTION_VERB_HINTS = {
    "on": [
        "bat",
        "mo",
        "khoi dong",
    ],
    "off": [
        "tat",
        "dong",
        "ngat",
        "dung",
    ],
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
    "cho",
    "toi",
    "giup",
    "dum",
    "voi",
    "nhe",
    "di",
    "nha",
    "cai",
    "chiec",
    "ho",
}

COMMAND_NOISE_WORDS = COMMAND_PREFIX_WORDS | COMMAND_TAIL_WORDS | DEVICE_REFERENCE_FILLER_WORDS | {
    "toi",
    "minh",
    "tao",
    "tui",
    "ho",
    "phat",
    "thu",
    "xem",
    "duoc",
    "khong",
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
    for action, keywords in ACTION_VERB_HINTS.items():
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


def _split_meaningful_tokens(text: str) -> List[str]:
    return [
        token
        for token in normalize_text(text).split()
        if token and token not in COMMAND_NOISE_WORDS
    ]


def _tokens_in_order(text_tokens: List[str], expected_tokens: List[str]) -> bool:
    if not text_tokens or not expected_tokens:
        return False
    cursor = 0
    for token in expected_tokens:
        while cursor < len(text_tokens) and text_tokens[cursor] != token:
            cursor += 1
        if cursor >= len(text_tokens):
            return False
        cursor += 1
    return True


def _score_term_match(text_n: str, term: str) -> float:
    if not text_n or not term:
        return 0.0

    if _has_device_phrase(text_n, term):
        return 1.0

    text_tokens = _split_meaningful_tokens(text_n)
    term_tokens = _split_meaningful_tokens(term)
    if not text_tokens or not term_tokens:
        return 0.0

    common_count = sum(1 for token in term_tokens if token in text_tokens)
    coverage = common_count / max(len(term_tokens), 1)
    ordered_bonus = 0.2 if _tokens_in_order(text_tokens, term_tokens) else 0.0
    single_token_penalty = 0.15 if len(term_tokens) == 1 else 0.0
    score = max(0.0, min(1.0, coverage * 0.85 + ordered_bonus - single_token_penalty))
    return score


def _score_phrase_match(text_n: str, phrase: str) -> float:
    if not text_n or not phrase:
        return 0.0
    if _has_phrase(text_n, phrase):
        return 1.0

    text_tokens = _split_meaningful_tokens(text_n)
    phrase_tokens = _split_meaningful_tokens(phrase)
    if not text_tokens or not phrase_tokens:
        return 0.0

    common_count = sum(1 for token in phrase_tokens if token in text_tokens)
    coverage = common_count / max(len(phrase_tokens), 1)
    ordered_bonus = 0.15 if _tokens_in_order(text_tokens, phrase_tokens) else 0.0
    return max(0.0, min(1.0, coverage * 0.9 + ordered_bonus))


def _extract_action_keywords() -> List[str]:
    keywords: List[str] = []
    for items in ACTION_VERB_HINTS.values():
        for item in items:
            if item not in keywords:
                keywords.append(item)
    return keywords


def parse_command_semantics(text: str) -> Dict[str, Any]:
    text_n = normalize_text(text)
    matched_keywords: List[str] = []

    for action, keywords in ACTION_VERB_HINTS.items():
        for keyword in keywords:
            if _has_phrase(text_n, keyword):
                matched_keywords.append(keyword)

    action = _extract_action(text_n)
    has_command_starter = _has_command_starter(text_n)
    has_command_tail = _has_command_tail(text_n)
    learned_action_info = parse_learned_action_reference(text)
    is_information_question = _looks_like_information_question(text_n, text)
    phrase_implied_control = bool(learned_action_info.get("matched_actions"))
    is_control = bool((action and (has_command_starter or has_command_tail)) or phrase_implied_control)
    if is_information_question and not phrase_implied_control and not has_command_starter:
        is_control = False

    return {
        "normalized_text": text_n,
        "operation": action,
        "matched_keywords": list(dict.fromkeys(matched_keywords)),
        "has_command_starter": has_command_starter,
        "has_command_tail": has_command_tail,
        "ambiguous_action": bool(matched_keywords) and action is None and (has_command_starter or has_command_tail),
        "is_information_question": is_information_question,
        "is_control_request": is_control,
        "learned_action_info": learned_action_info,
    }


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
    parsed = parse_command_semantics(user_text)
    result = {
        "is_control_request": parsed.get("is_control_request"),
        "normalized_text": parsed.get("normalized_text"),
        "matched_keywords": parsed.get("matched_keywords"),
        "action": parsed.get("operation"),
        "ambiguous_action": parsed.get("ambiguous_action"),
        "has_command_starter": parsed.get("has_command_starter"),
        "has_command_tail": parsed.get("has_command_tail"),
        "is_information_question": parsed.get("is_information_question"),
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

            semantic = action_config.get("semantic") or {}
            operation = str(semantic.get("operation") or "").strip().lower()
            if operation in {"on", "off"}:
                action_synonyms = CONTROL_ACTION_SYNONYMS.get(operation, [])
                device_terms = [device_id, device.get("name") or ""] + list(device.get("aliases") or [])
                seen_generated: List[str] = []
                for action_synonym in action_synonyms:
                    action_text = normalize_text(action_synonym)
                    for device_term in device_terms:
                        device_text = normalize_text(device_term)
                        generated_phrase = f"{action_text} {device_text}".strip()
                        if not device_text or generated_phrase in seen_generated:
                            continue
                        seen_generated.append(generated_phrase)
                        candidates.append(
                            {
                                "device_id": device_id,
                                "action": str(action_key or "").strip(),
                                "phrase": generated_phrase,
                                "display_name": display_name,
                            }
                        )

    candidates.sort(key=lambda item: len(item["phrase"]), reverse=True)
    return candidates


def parse_learned_action_reference(text: str) -> Dict[str, Any]:
    text_n = normalize_text(text)
    matches: List[Dict[str, str]] = []
    scored_matches: List[Dict[str, Any]] = []

    for candidate in _build_action_phrase_candidates():
        if _has_phrase(text_n, candidate["phrase"]):
            matches.append(candidate)
            continue
        score = _score_phrase_match(text_n, candidate["phrase"])
        if score >= 0.78:
            scored_matches.append({**candidate, "score": score})

    if matches:
        best_phrase_length = max(len(item["phrase"]) for item in matches)
        matches = [item for item in matches if len(item["phrase"]) == best_phrase_length]
    elif scored_matches:
        best_score = max(float(item["score"]) for item in scored_matches)
        matches = [item for item in scored_matches if float(item["score"]) >= best_score - 0.06]

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
    scored_by_device: Dict[str, Dict[str, Any]] = {}

    for candidate in _build_device_candidates():
        if _has_device_phrase(text_n, candidate["term"]):
            matches.append(candidate)

    if not matches:
        for candidate in _build_device_candidates():
            score = _score_term_match(text_n, candidate["term"])
            if score < 0.78:
                continue
            existing = scored_by_device.get(candidate["device_id"])
            enriched = {
                **candidate,
                "score": score,
            }
            if not existing or float(existing.get("score", 0.0)) < score:
                scored_by_device[candidate["device_id"]] = enriched

        if scored_by_device:
            ranked = sorted(
                scored_by_device.values(),
                key=lambda item: (float(item.get("score", 0.0)), len(item.get("term", ""))),
                reverse=True,
            )
            best_score = float(ranked[0].get("score", 0.0))
            matches = [item for item in ranked if float(item.get("score", 0.0)) >= best_score - 0.06]
        else:
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
    """Parse intent local theo pipeline parser -> semantic resolver."""
    if not text:
        return None

    from ai.semantic_resolver import resolve_device_command

    resolved = resolve_device_command(text)
    intent = resolved.get("intent")
    if resolved.get("status") != "resolved" or not intent:
        return None

    log_event(
        source="intent-parser",
        level="success",
        message="Parse local intent thanh cong qua semantic resolver",
        payload={"intent": intent, "resolver_status": resolved.get("status")},
    )
    return {
        "device": intent.get("device"),
        "action": intent.get("action"),
    }


def parse_local_device_intent(text: str) -> Optional[Dict[str, Any]]:
    """Trả kết quả command local nếu parse thành công hoàn toàn."""
    from ai.semantic_resolver import resolve_device_command

    resolved = resolve_device_command(text)
    intent = resolved.get("intent")
    if resolved.get("status") != "resolved" or not intent:
        return None

    return {
        "type": "command",
        "device": intent.get("device"),
        "action": intent.get("action"),
        "reply": None,
        "resolver": resolved,
    }


def is_explicit_device_command(text: str) -> bool:
    info = detect_control_request(text)
    return bool(info.get("is_control_request"))
