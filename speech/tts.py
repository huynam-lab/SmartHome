import asyncio
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from queue import Empty, Full, Queue
from typing import Dict, Optional

try:
    import edge_tts
except Exception as exc:  # pragma: no cover
    edge_tts = None
    _EDGE_TTS_IMPORT_ERROR = repr(exc)
else:
    _EDGE_TTS_IMPORT_ERROR = ""

from config import ENABLE_TTS, TTS_MIC_BLOCK_COOLDOWN_SECONDS, TTS_QUEUE_SIZE, TTS_SYNTH_TIMEOUT_SECONDS, TTS_VOICE_NAME
from core.event_bus import log_event
from core.voice_state import set_assistant_speaking, update_last_tts
from services.music_player import get_music_player


_TTS_LOCK = threading.Lock()
_REQUIRED_TTS_VOICE = "vi-VN-HoaiMyNeural"
_TTS_VOICE = _REQUIRED_TTS_VOICE
_TTS_RATE = "-20%"
_DEFAULT_PLAYER_CANDIDATES = [
    ["mpv", "--really-quiet", "--no-video", "--audio-display=no", "--keep-open=no"],
    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error"],
]
_TTS_QUEUE: "Queue[str]" = Queue(maxsize=max(1, int(TTS_QUEUE_SIZE)))
_TTS_WORKER_THREAD: Optional[threading.Thread] = None
_TTS_WORKER_LOCK = threading.Lock()


def _log_tts(level: str, message: str, payload: Optional[Dict] = None) -> None:
    safe_payload = payload or {}
    log_event(source="tts", level=level, message=message, payload=safe_payload)


def _ensure_tts_voice() -> str:
    global _TTS_VOICE
    if _TTS_VOICE != _REQUIRED_TTS_VOICE or TTS_VOICE_NAME != _REQUIRED_TTS_VOICE:
        _log_tts(
            "warning",
            "override unsupported tts voice",
            {
                "configured_voice": TTS_VOICE_NAME,
                "active_voice": _TTS_VOICE,
                "required_voice": _REQUIRED_TTS_VOICE,
            },
        )
        _TTS_VOICE = _REQUIRED_TTS_VOICE
    return _TTS_VOICE


def split_text_for_tts(text: str, max_len: int = 220) -> list:
    cleaned = " ".join((text or "").strip().split())
    if not cleaned:
        return []
    return [cleaned]


def _normalize_tts_text(text: str, strict: bool = False) -> str:
    """Giảm rủi ro NoAudioReceived bằng cách làm sạch ký tự/punctuation."""
    cleaned = " ".join(str(text or "").strip().split())
    if not cleaned:
        return ""
    cleaned = re.sub(r"[\x00-\x1F\x7F]", " ", cleaned)
    cleaned = re.sub(r"\bTP\.\s*", "thanh pho ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bQ\.\s*", "quan ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(\d{1,2})/(\d{1,2})", r"\1 thang \2", cleaned)
    cleaned = cleaned.replace("“", '"').replace("”", '"').replace("’", "'")
    cleaned = cleaned.replace('"', "").strip()
    if not strict:
        return cleaned
    cleaned = re.sub(r"(\d+)[.,](\d+)", r"\1 phay \2", cleaned)
    cleaned = re.sub(r"\bkm/h\b", " ki lo met tren gio ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bm/s\b", " met tren giay ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bmm\b", " mi li met ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bcm\b", " xen ti met ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bkg\b", " ki lo gam ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bkm\b", " ki lo met ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bmb\b", " mê ga bai ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bgb\b", " ghi ga bai ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bhttps?://\S+\b", " lien ket web ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bwww\.\S+\b", " lien ket web ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[,;:(){}\[\]/\\]+", " ", cleaned)
    cleaned = re.sub(r"[.!?]+$", "", cleaned)
    cleaned = cleaned.replace("%", " phan tram")
    cleaned = cleaned.replace("°C", " do C").replace("°", " do ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _split_smaller(text: str, max_len: int) -> list:
    cleaned = " ".join((text or "").strip().split())
    if not cleaned:
        return []
    return [cleaned]


def _synthesize_with_retries(text: str, output_path: str) -> None:
    last_error: Optional[Exception] = None
    for attempt in range(1, 4):
        effective_rate = _TTS_RATE if attempt == 1 else "+0%"
        effective_text = _normalize_tts_text(text, strict=attempt >= 3)
        try:
            asyncio.run(_synthesize_audio(text=effective_text, output_path=output_path, rate=effective_rate))
            return
        except Exception as exc:
            last_error = exc
            _log_tts(
                "error",
                "synthesis failed",
                {
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                    "error": repr(exc),
                    "voice": _ensure_tts_voice(),
                    "rate": effective_rate,
                    "text": effective_text,
                    "audio_path": output_path,
                    "retry": attempt,
                },
            )
            if attempt < 3:
                time.sleep(0.35 * attempt)
    if last_error:
        raise last_error


async def _synthesize_audio(text: str, output_path: str, rate: str) -> None:
    if edge_tts is None:
        raise RuntimeError(f"edge_tts import failed: {_EDGE_TTS_IMPORT_ERROR}")
    communicate = edge_tts.Communicate(text=text, voice=_ensure_tts_voice(), rate=rate)
    adaptive_timeout = max(1.0, TTS_SYNTH_TIMEOUT_SECONDS, 12.0 + (len(text) * 0.12))
    await asyncio.wait_for(communicate.save(output_path), timeout=adaptive_timeout)


def _list_available_audio_players() -> list:
    available_commands = []
    for command in _DEFAULT_PLAYER_CANDIDATES:
        if shutil.which(command[0]):
            available_commands.append(command)
    return available_commands


def _play_audio(audio_path: str) -> Dict[str, object]:
    player_commands = _list_available_audio_players()
    if not player_commands:
        message = "Không tìm thấy audio player hỗ trợ. Cần cài mpg123, ffplay hoặc mpv"
        _log_tts("error", message, {"audio_path": audio_path})
        return {"success": False, "message": message, "returncode": None, "stderr": "", "stdout": ""}

    failures = []
    for player_command in player_commands:
        command = [*player_command, audio_path]
        _log_tts("info", "player command", {"command": command, "audio_path": audio_path})

        try:
            result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=20)
            payload = {
                "audio_path": audio_path,
                "command": command,
                "returncode": result.returncode,
                "stdout": (result.stdout or "").strip(),
                "stderr": (result.stderr or "").strip(),
            }
            if result.returncode == 0:
                _log_tts("success", "playback success", payload)
                return {"success": True, "message": "Phát âm thanh thành công", **payload}

            failures.append(payload)
            _log_tts("warning", "playback failed, trying next player", payload)
        except subprocess.TimeoutExpired as exc:
            payload = {
                "audio_path": audio_path,
                "command": command,
                "error": f"timeout after {exc.timeout}s",
            }
            failures.append(payload)
            _log_tts("warning", "playback timeout, trying next player", payload)
        except Exception as exc:
            payload = {"audio_path": audio_path, "command": command, "error": repr(exc)}
            failures.append(payload)
            _log_tts("warning", "playback exception, trying next player", payload)

    final_payload = {"audio_path": audio_path, "attempts": failures}
    _log_tts("error", "all playback methods failed", final_payload)
    return {"success": False, "message": "Phát âm thanh thất bại", **final_payload}


def speak_text(text: str) -> bool:
    """Public TTS entrypoint, luôn log rõ từng bước để debug."""
    if not text:
        _log_tts("warning", "skip empty text", {"text": text})
        return False

    _log_tts("info", "start", {"text": text, "enabled": ENABLE_TTS})
    if not ENABLE_TTS:
        _log_tts("info", "tts disabled by config", {"text": text})
        return True

    if edge_tts is None:
        _log_tts(
            "error",
            "edge_tts module chưa sẵn sàng",
            {
                "error": _EDGE_TTS_IMPORT_ERROR,
                "voice": _ensure_tts_voice(),
                "text": text,
                "hint": "Hãy chạy python3.10 -m pip install -r requirements-py310.txt",
            },
        )
        return False

    with _TTS_LOCK:
        set_assistant_speaking(True)
        temp_file = None
        music_player = get_music_player()
        chunks = split_text_for_tts(text, max_len=220)
        total_chunks = len(chunks)
        try:
            try:
                duck_result = music_player.duck_for_tts()
                _log_tts("info", "music duck before tts", duck_result)
            except Exception as exc:
                _log_tts("warning", "music duck failed before tts", {"error": repr(exc)})

            if not chunks:
                _log_tts("warning", "skip empty chunks", {"text": text})
                return False

            voice = _ensure_tts_voice()
            for idx, chunk in enumerate(chunks, start=1):
                chunk_len = len(chunk)
                _log_tts(
                    "info",
                    "chunk start",
                    {"chunk_index": idx, "chunk_total": total_chunks, "text_len": chunk_len},
                )

                def _process_chunk(text_value: str, depth: int = 0) -> bool:
                    if not text_value:
                        return False
                    if depth > 2:
                        return False

                    fd, temp_file = tempfile.mkstemp(prefix="tts_", suffix=".mp3")
                    os.close(fd)
                    try:
                        _log_tts(
                            "info",
                            "audio temp file allocated",
                            {
                                "audio_path": temp_file,
                                "chunk_index": idx,
                                "chunk_total": total_chunks,
                                "text_len": len(text_value),
                                "depth": depth,
                            },
                        )

                        _log_tts(
                            "info",
                            "before synthesis",
                            {
                                "voice": voice,
                                "rate": _TTS_RATE,
                                "text": text_value,
                                "audio_path": temp_file,
                                "chunk_index": idx,
                                "chunk_total": total_chunks,
                                "text_len": len(text_value),
                                "depth": depth,
                            },
                        )
                        _synthesize_with_retries(text_value, temp_file)

                        if not os.path.exists(temp_file):
                            raise RuntimeError("audio file missing after synthesis")

                        file_size = os.path.getsize(temp_file)
                        if file_size <= 0:
                            raise RuntimeError("audio file empty")

                        _log_tts(
                            "info",
                            "before playback",
                            {
                                "audio_path": temp_file,
                                "file_size": file_size,
                                "chunk_index": idx,
                                "chunk_total": total_chunks,
                                "text_len": len(text_value),
                                "depth": depth,
                            },
                        )
                        play_result = _play_audio(temp_file)
                        if not play_result.get("success"):
                            _log_tts(
                                "error",
                                "playback failed",
                                {
                                    "audio_path": temp_file,
                                    "chunk_index": idx,
                                    "chunk_total": total_chunks,
                                    "text_len": len(text_value),
                                    "depth": depth,
                                },
                            )
                            return False
                        return True
                    except Exception as exc:
                        _log_tts(
                            "warning",
                            "chunk synthesis failed",
                            {
                                "exception_type": type(exc).__name__,
                                "exception_message": str(exc),
                                "error": repr(exc),
                                "text_len": len(text_value),
                                "depth": depth,
                            },
                        )
                        return False
                    finally:
                        if temp_file and os.path.exists(temp_file):
                            try:
                                os.remove(temp_file)
                                _log_tts("info", "audio temp file removed", {"audio_path": temp_file})
                            except Exception as exc:
                                _log_tts(
                                    "warning",
                                    "failed to remove temp audio",
                                    {"audio_path": temp_file, "error": repr(exc)},
                                )

                if not _process_chunk(chunk, depth=0):
                    return False

            return True
        finally:
            try:
                restore_result = music_player.restore_after_tts()
                _log_tts("info", "music restore after tts", restore_result)
            except Exception as exc:
                _log_tts("warning", "music restore failed after tts", {"error": repr(exc)})
            update_last_tts(text)
            time.sleep(max(0.0, TTS_MIC_BLOCK_COOLDOWN_SECONDS))
            set_assistant_speaking(False)
            _log_tts("info", "done", {"text": text})


def speak_text_async(text: str) -> bool:
    """Đẩy TTS vào worker nền cố định để tránh sinh quá nhiều thread."""
    if not text:
        _log_tts("warning", "skip empty text async", {"text": text})
        return False

    _ensure_tts_worker()
    normalized_text = " ".join(str(text).strip().split())
    if not normalized_text:
        _log_tts("warning", "skip normalized empty text async", {"text": text})
        return False

    try:
        _TTS_QUEUE.put_nowait(normalized_text)
        _log_tts("info", "tts queued", {"text": normalized_text, "queue_size": _TTS_QUEUE.qsize()})
        return True
    except Full:
        dropped_text = None
        try:
            dropped_text = _TTS_QUEUE.get_nowait()
        except Empty:
            pass

        try:
            _TTS_QUEUE.put_nowait(normalized_text)
            _log_tts(
                "warning",
                "tts queue full, dropped oldest pending item",
                {"dropped_text": dropped_text, "text": normalized_text, "queue_size": _TTS_QUEUE.qsize()},
            )
            return True
        except Full:
            _log_tts("error", "tts queue still full after drop", {"text": normalized_text, "dropped_text": dropped_text})
            return False


def _tts_worker_loop() -> None:
    while True:
        text = _TTS_QUEUE.get()
        try:
            speak_text(text)
        except Exception as exc:
            _log_tts("error", "tts worker failed", {"text": text, "error": repr(exc)})
        finally:
            _TTS_QUEUE.task_done()


def _ensure_tts_worker() -> None:
    global _TTS_WORKER_THREAD
    worker = _TTS_WORKER_THREAD
    if worker and worker.is_alive():
        return

    with _TTS_WORKER_LOCK:
        worker = _TTS_WORKER_THREAD
        if worker and worker.is_alive():
            return
        worker = threading.Thread(target=_tts_worker_loop, name="tts-worker", daemon=True)
        worker.start()
        _TTS_WORKER_THREAD = worker
        _log_tts("info", "tts worker started", {"thread_name": worker.name, "queue_size": _TTS_QUEUE.maxsize})
    return True


def speak(text: str) -> bool:
    return speak_text(text)
