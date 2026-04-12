from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ai.intent_parser import normalize_text, parse_command_semantics
from controller.device_registry import get_registry
from core.event_bus import log_event


DEVICE_KIND_TERMS = {
    "light": ["den", "đèn"],
    "air_conditioner": ["dieu hoa", "điều hoà", "điều hòa", "may lanh", "máy lạnh"],
    "smart_switch": ["cong tac", "công tắc", "dien", "điện"],
}

AUTO_RESOLVE_MIN_SCORE = 0.98
AUTO_RESOLVE_MIN_MARGIN = 0.12
GENERIC_CONTEXT_MIN_SCORE = 0.75

GENERIC_DEVICE_TERMS = {"den", "dien", "cong", "tac", "cong tac", "dieu hoa", "may lanh"}
ACTION_NOISE_TOKENS = {
    "bat",
    "tat",
    "mo",
    "dong",
    "ngat",
    "dung",
    "khoi",
    "dong",
    "len",
    "cho",
    "anh",
    "chi",
    "em",
    "giup",
    "dum",
    "voi",
    "nhe",
    "ngay",
    "luon",
    "nha",
    "phong",
    "o",
    "tai",
}


def _has_phrase(text_n: str, phrase: str) -> bool:
    phrase_n = normalize_text(phrase)
    if not text_n or not phrase_n:
        return False
    return f" {phrase_n} " in f" {text_n} "


def _tokens(text: str) -> List[str]:
    return [token for token in normalize_text(text).split() if token]


def _score_token_overlap(text_n: str, term: str) -> float:
    text_tokens = _tokens(text_n)
    term_tokens = _tokens(term)
    if not text_tokens or not term_tokens:
        return 0.0

    common = sum(1 for token in term_tokens if token in text_tokens)
    if common <= 0:
        return 0.0

    coverage = common / len(term_tokens)
    ordered_bonus = 0.15 if " ".join(term_tokens) in " ".join(text_tokens) else 0.0
    return min(1.0, coverage * 0.9 + ordered_bonus)


def _build_device_terms(device: Dict[str, Any]) -> List[Tuple[str, bool]]:
    terms: List[Tuple[str, bool]] = []
    for raw in [
        device.get("id"),
        device.get("name"),
        *(device.get("aliases") or []),
        device.get("room"),
        *(device.get("room_aliases") or []),
    ]:
        normalized = normalize_text(raw)
        if normalized and all(item[0] != normalized for item in terms):
            terms.append((normalized, False))

    for raw in DEVICE_KIND_TERMS.get(str(device.get("device_kind") or "").strip().lower(), []):
        normalized = normalize_text(raw)
        if normalized and all(item[0] != normalized for item in terms):
            terms.append((normalized, True))

    return terms


def _extract_semantic_operation(action_config: Dict[str, Any]) -> str:
    semantic = action_config.get("semantic") or {}
    return str(semantic.get("operation") or "").strip().lower()


def _extract_requested_semantic_value(operation: str, semantic_info: Dict[str, Any]) -> Any:
    if operation == "set_temperature":
        return semantic_info.get("requested_temperature_c")
    if operation == "off_after":
        return semantic_info.get("requested_duration_seconds")
    if operation == "set_mode":
        return semantic_info.get("requested_mode")
    if operation == "set_fan_speed":
        return semantic_info.get("requested_fan_speed")
    if operation == "set_swing":
        return semantic_info.get("requested_swing")
    if operation == "set_sleep":
        return semantic_info.get("requested_sleep")
    return None


def _extract_action_semantic_value(operation: str, semantic: Dict[str, Any]) -> Any:
    if operation == "set_temperature":
        return semantic.get("temperature_c")
    if operation == "off_after":
        return semantic.get("duration_seconds")
    if operation == "set_mode":
        return semantic.get("mode")
    if operation == "set_fan_speed":
        return semantic.get("fan_speed")
    if operation == "set_swing":
        return semantic.get("swing")
    if operation == "set_sleep":
        return semantic.get("enabled")
    return None


def _semantic_value_matches(operation: str, action_value: Any, requested_value: Any) -> bool:
    if requested_value is None:
        return False
    if operation in {"set_temperature", "off_after"}:
        try:
            return int(action_value) == int(requested_value)
        except (TypeError, ValueError):
            return False
    if operation == "set_sleep":
        return bool(action_value) is bool(requested_value)
    return str(action_value or "").strip().lower() == str(requested_value or "").strip().lower()


def _find_exact_semantic_action(device_id: str, semantic_info: Dict[str, Any]) -> Optional[str]:
    if not device_id:
        return None

    target_operation = str(semantic_info.get("operation") or "").strip().lower()
    if not target_operation:
        return None

    registry = get_registry()
    registry.reload()
    device = registry.get_device(device_id) or {}
    actions_map = dict(device.get("actions") or {})

    for action_key, action_config in actions_map.items():
        semantic = action_config.get("semantic") or {}
        operation = str(semantic.get("operation") or "").strip().lower()
        if operation != target_operation:
            continue

        requested_value = _extract_requested_semantic_value(target_operation, semantic_info)
        action_value = _extract_action_semantic_value(target_operation, semantic)
        if target_operation in {"on", "off"}:
            return str(action_key or "").strip()
        if _semantic_value_matches(target_operation, action_value, requested_value):
            return str(action_key or "").strip()

    return None


def _find_nearest_semantic_action(device_id: str, semantic_info: Dict[str, Any]) -> Optional[str]:
    if not device_id:
        return None

    target_operation = str(semantic_info.get("operation") or "").strip().lower()
    requested_value = _extract_requested_semantic_value(target_operation, semantic_info)
    if requested_value is None or target_operation not in {"set_temperature", "off_after"}:
        return None

    registry = get_registry()
    registry.reload()
    device = registry.get_device(device_id) or {}
    actions_map = dict(device.get("actions") or {})

    ranked_candidates: List[Tuple[float, str]] = []
    for action_key, action_config in actions_map.items():
        semantic = action_config.get("semantic") or {}
        operation = str(semantic.get("operation") or "").strip().lower()
        if operation != target_operation:
            continue

        action_value = _extract_action_semantic_value(target_operation, semantic)
        try:
            distance = abs(int(action_value) - int(requested_value))
        except (TypeError, ValueError):
            continue
        ranked_candidates.append((float(distance), str(action_key or "").strip()))

    if not ranked_candidates:
        return None

    ranked_candidates.sort(key=lambda item: (item[0], item[1]))
    best_distance = ranked_candidates[0][0]
    same_distance = [item for item in ranked_candidates if item[0] == best_distance]
    if len(same_distance) != 1:
        return None

    max_distance = 1 if target_operation == "set_temperature" else 300
    if best_distance > max_distance:
        return None
    return same_distance[0][1]


def _find_supporting_power_action(device_id: str, target_operation: str) -> Optional[str]:
    normalized_target = str(target_operation or "").strip().lower()
    if normalized_target not in {"on", "off"}:
        return None

    registry = get_registry()
    registry.reload()
    device = registry.get_device(device_id) or {}
    actions_map = dict(device.get("actions") or {})

    for action_key, action_config in actions_map.items():
        semantic = action_config.get("semantic") or {}
        operation = str(semantic.get("operation") or "").strip().lower()
        if operation == normalized_target:
            return str(action_key or "").strip()
    return None


def _build_action_sequence(device_id: str, resolved_action: str, semantic_info: Dict[str, Any]) -> List[str]:
    normalized_action = str(resolved_action or "").strip()
    if not device_id or not normalized_action:
        return []

    semantic_operation = str(semantic_info.get("operation") or "").strip().lower()
    verb_operation = str(semantic_info.get("verb_operation") or "").strip().lower()
    if verb_operation != "on":
        return [normalized_action]

    if semantic_operation not in {"set_temperature", "set_mode", "set_fan_speed", "set_swing", "set_sleep"}:
        return [normalized_action]

    power_on_action = _find_supporting_power_action(device_id, "on")
    sequence: List[str] = []
    if power_on_action and power_on_action != normalized_action:
        sequence.append(power_on_action)
    sequence.append(normalized_action)
    return sequence


def _score_device(text_n: str, device: Dict[str, Any]) -> Dict[str, Any]:
    terms = _build_device_terms(device)
    exact_terms: List[str] = []
    best_score = 0.0
    generic_only = True

    for term, is_generic in terms:
        if _has_phrase(text_n, term):
            exact_terms.append(term)
            best_score = max(best_score, 0.7 if is_generic else 1.0)
            if not is_generic:
                generic_only = False
            continue
        overlap_score = _score_token_overlap(text_n, term)
        if overlap_score > 0 and not is_generic:
            generic_only = False
        if is_generic:
            overlap_score *= 0.7
        best_score = max(best_score, overlap_score)

    return {
        "device": device,
        "score": best_score,
        "matched_terms": exact_terms,
        "generic_only": generic_only,
    }


def _extract_context_phrase_tokens(text: str) -> List[str]:
    return [token for token in _tokens(text) if token and token not in ACTION_NOISE_TOKENS]


def _score_context_overlap(text_n: str, phrase: str) -> float:
    text_tokens = _extract_context_phrase_tokens(text_n)
    phrase_tokens = _extract_context_phrase_tokens(phrase)
    if not text_tokens or not phrase_tokens:
        return 0.0

    common = sum(1 for token in phrase_tokens if token in text_tokens)
    if common <= 0:
        return 0.0

    return min(1.0, common / len(phrase_tokens))


def _score_action(text_n: str, action_key: str, action_config: Dict[str, Any], semantic_info: Dict[str, Any]) -> Dict[str, Any]:
    operation = _extract_semantic_operation(action_config)
    semantic = action_config.get("semantic") or {}
    phrases = [normalize_text(item) for item in list(action_config.get("phrases") or []) if normalize_text(item)]

    phrase_score = 0.0
    context_score = 0.0
    matched_phrases: List[str] = []
    for phrase in phrases:
        if _has_phrase(text_n, phrase):
            matched_phrases.append(phrase)
            phrase_score = max(phrase_score, 1.0)
            continue
        phrase_score = max(phrase_score, _score_token_overlap(text_n, phrase))
        context_score = max(context_score, _score_context_overlap(text_n, phrase))

    operation_score = 0.0
    inferred_operation = semantic_info.get("operation")
    if inferred_operation and operation and inferred_operation == operation:
        operation_score = 1.0
    elif matched_phrases:
        operation_score = 0.7

    parameter_score = 0.0
    parameter_penalty = 0.0
    requested_value = _extract_requested_semantic_value(operation, semantic_info)
    action_value = _extract_action_semantic_value(operation, semantic)
    if requested_value is not None:
        if operation in {"set_temperature", "off_after"}:
            try:
                diff = abs(int(action_value) - int(requested_value))
            except (TypeError, ValueError):
                parameter_penalty = 0.35
            else:
                if diff == 0:
                    parameter_score = 1.25
                elif operation == "set_temperature":
                    parameter_penalty = min(0.45, 0.12 * diff)
                else:
                    parameter_penalty = min(0.45, diff / 600)
        elif _semantic_value_matches(operation, action_value, requested_value):
            parameter_score = 1.25
        else:
            parameter_penalty = 0.35

    return {
        "action": action_key,
        "operation": operation,
        "score": max(phrase_score, operation_score, context_score * 0.95, parameter_score),
        "context_score": context_score,
        "parameter_penalty": parameter_penalty,
        "matched_phrases": matched_phrases,
    }


def _rank_candidates(text_n: str, semantic_info: Dict[str, Any]) -> List[Dict[str, Any]]:
    registry = get_registry()
    registry.reload()
    ranked: List[Dict[str, Any]] = []

    for device in registry.list_devices():
        device_score = _score_device(text_n, device)
        if device_score["score"] < 0.45:
            continue

        actions_map = dict(device.get("actions") or {})
        for action_key, action_config in actions_map.items():
            action_score = _score_action(text_n, action_key, action_config, semantic_info)
            if action_score["score"] <= 0 and not action_score["matched_phrases"]:
                continue

            total_score = device_score["score"] * 0.55 + action_score["score"] * 0.45
            if device_score["matched_terms"]:
                total_score += 0.1
            if action_score["matched_phrases"]:
                total_score += 0.2
            if float(action_score.get("context_score", 0.0)) >= 0.5:
                total_score += 0.25
            if device_score.get("generic_only") and float(action_score.get("context_score", 0.0)) < 0.4:
                total_score -= 0.18
            total_score -= float(action_score.get("parameter_penalty", 0.0))

            ranked.append(
                {
                    "device_id": device.get("id"),
                    "device_name": device.get("name") or device.get("id"),
                    "device_kind": device.get("device_kind"),
                    "room": device.get("room") or "",
                    "action": action_key,
                    "operation": action_score["operation"],
                    "score": round(min(total_score, 1.5), 4),
                    "matched_device_terms": device_score["matched_terms"],
                    "matched_action_phrases": action_score["matched_phrases"],
                    "context_score": action_score.get("context_score", 0.0),
                    "generic_only": bool(device_score.get("generic_only")),
                }
            )

    ranked.sort(
        key=lambda item: (
            item.get("score", 0.0),
            len(" ".join(item.get("matched_action_phrases") or [])),
            len(" ".join(item.get("matched_device_terms") or [])),
        ),
        reverse=True,
    )
    return ranked


def _build_clarification(top_candidates: List[Dict[str, Any]], semantic_info: Dict[str, Any]) -> str:
    operation = semantic_info.get("operation")
    devices = []
    for item in top_candidates:
        name = item.get("device_name") or item.get("device_id")
        if name and name not in devices:
            devices.append(name)

    if not operation:
        if len(devices) == 1:
            return f"Anh/chị muốn bật hay tắt {devices[0]} ạ?"
        return "Anh/chị muốn bật hay tắt thiết bị nào ạ?"

    if len(devices) > 1:
        return f"Em thấy có nhiều thiết bị phù hợp: {', '.join(devices[:3])}. Anh/chị muốn điều khiển thiết bị nào ạ?"

    return "Anh/chị nói rõ thêm giúp em tên thiết bị hoặc vị trí thiết bị ạ."


def _build_missing_semantic_message(device_name: str, semantic_info: Dict[str, Any]) -> str:
    operation = str(semantic_info.get("operation") or "").strip().lower()
    if operation == "set_temperature":
        return f"{device_name} chưa có lệnh đã học cho mức nhiệt này."
    if operation == "set_mode":
        return f"{device_name} chưa có lệnh đã học cho chế độ này."
    if operation == "set_fan_speed":
        return f"{device_name} chưa có lệnh đã học cho mức quạt này."
    if operation == "set_swing":
        return f"{device_name} chưa có lệnh đã học cho chế độ đảo gió này."
    if operation == "set_sleep":
        return f"{device_name} chưa có lệnh đã học cho chế độ ngủ này."
    if operation == "off_after":
        return f"{device_name} chưa có lệnh đã học cho mốc hẹn giờ này."
    return f"{device_name} chưa có lệnh đã học phù hợp."


def _top_distinct_device_candidates(ranked: List[Dict[str, Any]], tolerance: float = 0.08) -> List[Dict[str, Any]]:
    if not ranked:
        return []

    top_score = float(ranked[0].get("score", 0.0))
    selected: List[Dict[str, Any]] = []
    seen_devices: List[str] = []
    for item in ranked:
        if abs(float(item.get("score", 0.0)) - top_score) > tolerance:
            continue
        device_id = str(item.get("device_id") or "")
        if device_id and device_id not in seen_devices:
            seen_devices.append(device_id)
            selected.append(item)
    return selected


def _should_clarify(top: Dict[str, Any], ranked: List[Dict[str, Any]], semantic_info: Dict[str, Any]) -> Optional[str]:
    if not semantic_info.get("operation"):
        same_device_candidates = [item for item in ranked if item.get("device_id") == top.get("device_id")][:3]
        return _build_clarification(same_device_candidates, semantic_info)

    top_score = float(top.get("score", 0.0))
    top_context = float(top.get("context_score", 0.0))
    top_has_phrase = bool(top.get("matched_action_phrases"))
    top_generic_only = bool(top.get("generic_only"))

    if top_score < AUTO_RESOLVE_MIN_SCORE and not top_has_phrase:
        return _build_clarification(_top_distinct_device_candidates(ranked)[:3], semantic_info)

    if top_generic_only and top_context < GENERIC_CONTEXT_MIN_SCORE and not top_has_phrase:
        return _build_clarification(_top_distinct_device_candidates(ranked)[:3], semantic_info)

    for second in ranked[1:]:
        if second.get("device_id") == top.get("device_id"):
            continue
        second_score = float(second.get("score", 0.0))
        if top_score - second_score < AUTO_RESOLVE_MIN_MARGIN:
            return _build_clarification(_top_distinct_device_candidates(ranked)[:3], semantic_info)
        break

    return None


def resolve_device_command(text: str) -> Dict[str, Any]:
    semantic_info = parse_command_semantics(text)
    text_n = semantic_info.get("normalized_text") or normalize_text(text)
    learned_action_info = semantic_info.get("learned_action_info") or {}
    semantic_operation = str(semantic_info.get("operation") or "").strip().lower()

    if not semantic_info.get("is_control_request"):
        result = {
            "status": "not_control",
            "intent": None,
            "message": "",
            "semantic": semantic_info,
            "candidates": [],
        }
        log_event(source="semantic-resolver", level="info", message="Bo qua vi khong phai lenh dieu khien", payload=result)
        return result

    if (
        learned_action_info.get("device_id")
        and learned_action_info.get("action")
        and not learned_action_info.get("ambiguous")
    ):
        exact_semantic_action = None
        if semantic_operation not in {"", "on", "off"}:
            exact_semantic_action = _find_exact_semantic_action(str(learned_action_info.get("device_id") or ""), semantic_info)
            if not exact_semantic_action:
                exact_semantic_action = _find_nearest_semantic_action(str(learned_action_info.get("device_id") or ""), semantic_info)
        if semantic_operation not in {"", "on", "off"} and not exact_semantic_action:
            learned_action_info = {}
        elif exact_semantic_action and exact_semantic_action != learned_action_info.get("action"):
            learned_action_info = {
                **learned_action_info,
                "action": exact_semantic_action,
            }
        if learned_action_info:
            registry = get_registry()
            registry.reload()
            resolved_action_info = registry.resolve_action_config(
                str(learned_action_info.get("device_id") or ""),
                str(learned_action_info.get("action") or ""),
            )
            result = {
                "status": "resolved",
                "intent": {
                    "device": learned_action_info.get("device_id"),
                    "action": learned_action_info.get("action"),
                    "action_sequence": _build_action_sequence(
                        str(learned_action_info.get("device_id") or ""),
                        str(learned_action_info.get("action") or ""),
                        semantic_info,
                    ),
                },
                "message": "",
                "semantic": semantic_info,
                "candidates": list(learned_action_info.get("matched_actions") or []),
                "resolved_device": learned_action_info.get("device_id"),
                "resolved_name": learned_action_info.get("device_name"),
                "action_config": dict(resolved_action_info.get("action_config") or {}),
            }
            log_event(source="semantic-resolver", level="success", message="Resolve bang learned phrase", payload=result)
            return result

    ranked = _rank_candidates(text_n, semantic_info)
    if not ranked:
        result = {
            "status": "unresolved",
            "intent": None,
            "message": "Em chưa tìm thấy thiết bị phù hợp trong cấu hình.",
            "semantic": semantic_info,
            "candidates": [],
        }
        log_event(source="semantic-resolver", level="warning", message=result["message"], payload=result)
        return result

    top = ranked[0]
    distinct_devices = _top_distinct_device_candidates(ranked)[:3]
    second_device_score = 0.0
    for item in ranked[1:]:
        if item.get("device_id") != top.get("device_id"):
            second_device_score = float(item.get("score", 0.0))
            break

    exact_semantic_action = None
    if len(distinct_devices) == 1 or (float(top.get("score", 0.0)) - second_device_score) >= AUTO_RESOLVE_MIN_MARGIN:
        exact_semantic_action = _find_exact_semantic_action(str(top.get("device_id") or ""), semantic_info)
        if not exact_semantic_action:
            exact_semantic_action = _find_nearest_semantic_action(str(top.get("device_id") or ""), semantic_info)

    if exact_semantic_action:
        registry = get_registry()
        registry.reload()
        resolved_action_info = registry.resolve_action_config(
            str(top.get("device_id") or ""),
            str(exact_semantic_action or ""),
        )
        result = {
            "status": "resolved",
            "intent": {
                "device": top.get("device_id"),
                "action": exact_semantic_action,
                "action_sequence": _build_action_sequence(
                    str(top.get("device_id") or ""),
                    str(exact_semantic_action or ""),
                    semantic_info,
                ),
            },
            "message": "",
            "semantic": semantic_info,
            "candidates": ranked[:5],
            "resolved_device": top.get("device_id"),
            "resolved_name": top.get("device_name"),
            "action_config": dict(resolved_action_info.get("action_config") or {}),
        }
        log_event(source="semantic-resolver", level="success", message="Resolve bang semantic metadata", payload=result)
        return result

    if semantic_operation not in {"", "on", "off"} and (len(distinct_devices) == 1 or (float(top.get("score", 0.0)) - second_device_score) >= AUTO_RESOLVE_MIN_MARGIN):
        result = {
            "status": "unresolved",
            "intent": None,
            "message": _build_missing_semantic_message(str(top.get("device_name") or top.get("device_id") or "Thiết bị"), semantic_info),
            "semantic": semantic_info,
            "candidates": ranked[:5],
        }
        log_event(source="semantic-resolver", level="warning", message=result["message"], payload=result)
        return result

    clarify_message = _should_clarify(top, ranked, semantic_info)
    if clarify_message:
        top_candidates = distinct_devices or ranked[:3]
        result = {
            "status": "clarify",
            "intent": None,
            "message": clarify_message,
            "semantic": semantic_info,
            "candidates": top_candidates,
        }
        log_event(source="semantic-resolver", level="warning", message=result["message"], payload=result)
        return result

    result = {
        "status": "resolved",
        "intent": {
            "device": top.get("device_id"),
            "action": top.get("action"),
            "action_sequence": _build_action_sequence(
                str(top.get("device_id") or ""),
                str(top.get("action") or ""),
                semantic_info,
            ),
        },
        "message": "",
        "semantic": semantic_info,
        "candidates": ranked[:5],
        "resolved_device": top.get("device_id"),
        "resolved_name": top.get("device_name"),
    }
    registry = get_registry()
    registry.reload()
    resolved_action_info = registry.resolve_action_config(
        str(top.get("device_id") or ""),
        str(top.get("action") or ""),
    )
    result["action_config"] = dict(resolved_action_info.get("action_config") or {})
    log_event(source="semantic-resolver", level="success", message="Resolve thiet bi thanh cong", payload=result)
    return result
