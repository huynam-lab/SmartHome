import speech_recognition as sr
import time
import os
import threading
import re
import unicodedata
from difflib import SequenceMatcher
from contextlib import contextmanager
from core.event_bus import log_event
from core.voice_state import get_last_tts_state, is_assistant_speaking
from config import (
    MIC_DEVICE_INDEX,
    MIC_PREFERRED_KEYWORDS,
    LISTEN_TIMEOUT,
    PHRASE_TIME_LIMIT,
    AMBIENT_NOISE_DURATION,
    AMBIENT_NOISE_REFRESH_SECONDS,
    DEBUG_VOICE,
    SUPPRESS_NATIVE_AUDIO_LOGS,
    TTS_ECHO_IGNORE_WINDOW_SECONDS,
    VOICE_BLOCK_SLEEP_SECONDS,
)


_recognizer = sr.Recognizer()
_recognizer.energy_threshold = 250
_recognizer.dynamic_energy_threshold = True
_recognizer.pause_threshold = 0.8
_recognizer.non_speaking_duration = 0.4

_AUDIO_BACKEND_OK = None
_LAST_BACKEND_ERROR_AT = 0.0
_LAST_BACKEND_ERROR_MESSAGE = ""
_LAST_AMBIENT_CALIBRATED_AT = 0.0
_STDERR_REDIRECT_LOCK = threading.Lock()


@contextmanager
def _suppress_native_audio_stderr():
    """An log native ALSA/PortAudio ra stderr, giu lai log Python cua app."""
    if not SUPPRESS_NATIVE_AUDIO_LOGS:
        yield
        return

    with _STDERR_REDIRECT_LOCK:
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        saved_stderr_fd = os.dup(2)
        try:
            os.dup2(devnull_fd, 2)
            yield
        finally:
            os.dup2(saved_stderr_fd, 2)
            os.close(saved_stderr_fd)
            os.close(devnull_fd)


def _check_audio_backend() -> bool:
    """Kiem tra backend micro (PyAudio/PortAudio) co hoat dong khong."""
    global _AUDIO_BACKEND_OK, _LAST_BACKEND_ERROR_AT, _LAST_BACKEND_ERROR_MESSAGE

    if _AUDIO_BACKEND_OK is True:
        return True

    try:
        with _suppress_native_audio_stderr():
            sr.Microphone.list_microphone_names()
        _AUDIO_BACKEND_OK = True
        _LAST_BACKEND_ERROR_MESSAGE = ""
        log_event(source="stt", level="info", message="Audio backend sẵn sàng", payload={})
        return True
    except Exception as exc:
        _LAST_BACKEND_ERROR_AT = time.time()
        _LAST_BACKEND_ERROR_MESSAGE = str(exc)
        _AUDIO_BACKEND_OK = False
        log_event(source="stt", level="error", message="Audio backend lỗi", payload={"error": repr(exc)})
        return False


def _resolve_microphone_index():
    """-1 -> tu dong tim mic phu hop, nguoc lai dung index chi dinh."""
    if MIC_DEVICE_INDEX >= 0:
        return MIC_DEVICE_INDEX

    try:
        with _suppress_native_audio_stderr():
            names = sr.Microphone.list_microphone_names()
    except Exception as exc:
        log_event(source="stt", level="error", message="Không lấy được danh sách microphone", payload={"error": repr(exc)})
        return None

    if not names:
        return None

    lowered = [name.lower() for name in names]
    for keyword in MIC_PREFERRED_KEYWORDS:
        for idx, mic_name in enumerate(lowered):
            if keyword in mic_name:
                return idx

    # Fallback ve default cua he thong neu khong match keyword
    return None


def print_microphone_list():
    try:
        with _suppress_native_audio_stderr():
            names = sr.Microphone.list_microphone_names()
        print("[MIC] Danh sach microphone:")
        for idx, name in enumerate(names):
            print(f"  - index={idx}: {name}")
    except Exception as e:
        print(f"[MIC] Khong doc duoc danh sach microphone: {e}")


def normalize_text_for_compare(text: str) -> str:
    if not text:
        return ""

    normalized = str(text).lower().strip().replace("đ", "d")
    normalized = unicodedata.normalize("NFD", normalized)
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    normalized = " ".join(normalized.split())
    return normalized


def is_echo_from_tts(user_text: str, last_tts_text: str, last_tts_time: float) -> bool:
    if not user_text or not last_tts_text or last_tts_time <= 0:
        return False

    elapsed = time.time() - last_tts_time
    if elapsed < 0 or elapsed > TTS_ECHO_IGNORE_WINDOW_SECONDS:
        return False

    norm_user = normalize_text_for_compare(user_text)
    norm_tts = normalize_text_for_compare(last_tts_text)
    if not norm_user or not norm_tts:
        return False

    substring_match = norm_user in norm_tts or norm_tts in norm_user
    similarity = SequenceMatcher(None, norm_user, norm_tts).ratio()
    high_similarity = similarity >= 0.82

    return substring_match or high_similarity


def recognize_once():
    global _LAST_AMBIENT_CALIBRATED_AT

    if is_assistant_speaking():
        time.sleep(max(0.01, VOICE_BLOCK_SLEEP_SECONDS))
        return ""

    if not _check_audio_backend():
        return ""

    mic_index = _resolve_microphone_index()

    try:
        with _suppress_native_audio_stderr():
            with sr.Microphone(device_index=mic_index) as source:
                log_event(source="stt", level="info", message="Bắt đầu lắng nghe microphone", payload={"mic_index": mic_index})

                now = time.time()
                should_refresh_ambient = (
                    _LAST_AMBIENT_CALIBRATED_AT <= 0
                    or (now - _LAST_AMBIENT_CALIBRATED_AT) >= max(1.0, AMBIENT_NOISE_REFRESH_SECONDS)
                )
                if should_refresh_ambient:
                    _recognizer.adjust_for_ambient_noise(source, duration=AMBIENT_NOISE_DURATION)
                    _LAST_AMBIENT_CALIBRATED_AT = time.time()
                    log_event(
                        source="stt",
                        level="info",
                        message="Đã calibrate ambient noise",
                        payload={
                            "duration": AMBIENT_NOISE_DURATION,
                            "refresh_seconds": AMBIENT_NOISE_REFRESH_SECONDS,
                        },
                    )
                else:
                    log_event(
                        source="stt",
                        level="info",
                        message="Bo qua calibrate ambient noise vi con hieu luc",
                        payload={
                            "seconds_since_last_calibration": round(now - _LAST_AMBIENT_CALIBRATED_AT, 3),
                            "refresh_seconds": AMBIENT_NOISE_REFRESH_SECONDS,
                        },
                    )

                try:
                    if is_assistant_speaking():
                        time.sleep(max(0.01, VOICE_BLOCK_SLEEP_SECONDS))
                        return ""

                    audio = _recognizer.listen(
                        source,
                        timeout=LISTEN_TIMEOUT,
                        phrase_time_limit=PHRASE_TIME_LIMIT,
                    )
                    log_event(source="stt", level="info", message="Đã thu được audio từ microphone", payload={"timeout": LISTEN_TIMEOUT, "phrase_time_limit": PHRASE_TIME_LIMIT})
                except sr.WaitTimeoutError:
                    log_event(source="stt", level="warning", message="Listen timeout, không có giọng nói", payload={})
                    return ""

        try:
            if is_assistant_speaking():
                time.sleep(max(0.01, VOICE_BLOCK_SLEEP_SECONDS))
                return ""

            text = _recognizer.recognize_google(audio, language="vi-VN")
            text = text.strip()
            log_event(source="stt", level="info", message="STT nhận diện thành công", payload={"text": text})

            if is_assistant_speaking():
                return ""
            last_tts_text, last_tts_time = get_last_tts_state()
            if is_echo_from_tts(text, last_tts_text, last_tts_time):
                log_event(source="stt", level="warning", message="Bỏ qua do nghi là echo từ TTS", payload={"text": text, "last_tts_text": last_tts_text})
                return ""

            return text

        except sr.UnknownValueError:
            log_event(source="stt", level="warning", message="Không nhận diện được giọng nói", payload={})
            return ""

        except sr.RequestError as e:
            log_event(source="stt", level="error", message="Lỗi request tới engine STT", payload={"error": repr(e)})
            return ""

    except Exception as exc:
        log_event(source="stt", level="error", message="Lỗi runtime khi đọc microphone/STT", payload={"error": repr(exc), "mic_index": mic_index})
        return ""
