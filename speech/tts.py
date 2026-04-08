import asyncio
import os
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Dict, Optional

try:
    import edge_tts
except Exception as exc:  # pragma: no cover
    edge_tts = None
    _EDGE_TTS_IMPORT_ERROR = repr(exc)
else:
    _EDGE_TTS_IMPORT_ERROR = ""

from config import ENABLE_TTS, TTS_MIC_BLOCK_COOLDOWN_SECONDS, TTS_SYNTH_TIMEOUT_SECONDS
from core.event_bus import log_event
from core.voice_state import set_assistant_speaking, update_last_tts
from services.music_player import get_music_player


_TTS_LOCK = threading.Lock()
_TTS_VOICE = "vi-VN-HoaiMyNeural"
_TTS_RATE = "-20%"
_DEFAULT_PLAYER_CANDIDATES = [
    ["mpg123", "-q"],
    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error"],
    ["mpv", "--really-quiet"],
]
_ESPEAK_BIN = shutil.which("espeak")


def _log_tts(level: str, message: str, payload: Optional[Dict] = None) -> None:
    safe_payload = payload or {}
    if safe_payload:
        print(f"[TTS] {message} | {safe_payload}")
    else:
        print(f"[TTS] {message}")
    log_event(source="tts", level=level, message=message, payload=safe_payload)


async def _synthesize_audio(text: str, output_path: str) -> None:
    if edge_tts is None:
        raise RuntimeError(f"edge_tts import failed: {_EDGE_TTS_IMPORT_ERROR}")
    communicate = edge_tts.Communicate(text=text, voice=_TTS_VOICE, rate=_TTS_RATE)
    await asyncio.wait_for(communicate.save(output_path), timeout=max(1.0, TTS_SYNTH_TIMEOUT_SECONDS))


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
            result = subprocess.run(command, check=False, capture_output=True, text=True)
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
        except Exception as exc:
            payload = {"audio_path": audio_path, "command": command, "error": repr(exc)}
            failures.append(payload)
            _log_tts("warning", "playback exception, trying next player", payload)

    final_payload = {"audio_path": audio_path, "attempts": failures}
    _log_tts("error", "all playback methods failed", final_payload)
    return {"success": False, "message": "Phát âm thanh thất bại", **final_payload}


def _speak_with_espeak(text: str) -> bool:
    if not _ESPEAK_BIN:
        _log_tts("warning", "espeak unavailable for fallback", {})
        return False
    command = [_ESPEAK_BIN, "-v", "vi", "-s", "150", text]
    _log_tts("info", "fallback espeak command", {"command": command})
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=20)
    except Exception as exc:
        _log_tts("error", "fallback espeak failed", {"error": repr(exc)})
        return False

    payload = {
        "command": command,
        "returncode": result.returncode,
        "stdout": (result.stdout or "").strip(),
        "stderr": (result.stderr or "").strip(),
    }
    if result.returncode == 0:
        _log_tts("success", "fallback espeak success", payload)
        return True
    _log_tts("error", "fallback espeak non-zero", payload)
    return False


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
            {"error": _EDGE_TTS_IMPORT_ERROR, "hint": "Hãy chạy python3.10 -m pip install -r requirements-py310.txt"},
        )
        return False

    with _TTS_LOCK:
        set_assistant_speaking(True)
        temp_file = None
        music_player = get_music_player()
        try:
            try:
                duck_result = music_player.duck_for_tts()
                _log_tts("info", "music duck before tts", duck_result)
            except Exception as exc:
                _log_tts("warning", "music duck failed before tts", {"error": repr(exc)})

            fd, temp_file = tempfile.mkstemp(prefix="tts_", suffix=".mp3")
            os.close(fd)
            _log_tts("info", "audio temp file allocated", {"audio_path": temp_file})

            try:
                asyncio.run(_synthesize_audio(text=text, output_path=temp_file))
                _log_tts("info", "audio file created", {"audio_path": temp_file})
            except Exception as exc:
                _log_tts("error", "synthesis failed", {"text": text, "audio_path": temp_file, "error": repr(exc)})
                return _speak_with_espeak(text)

            if not os.path.exists(temp_file):
                _log_tts("error", "audio file missing after synthesis", {"audio_path": temp_file})
                return False

            file_size = os.path.getsize(temp_file)
            if file_size <= 0:
                _log_tts("error", "audio file empty", {"audio_path": temp_file, "file_size": file_size})
                return False

            _log_tts("info", "before playback", {"audio_path": temp_file, "file_size": file_size})
            play_result = _play_audio(temp_file)
            return bool(play_result.get("success"))
        finally:
            try:
                restore_result = music_player.restore_after_tts()
                _log_tts("info", "music restore after tts", restore_result)
            except Exception as exc:
                _log_tts("warning", "music restore failed after tts", {"error": repr(exc)})
            update_last_tts(text)
            time.sleep(max(0.0, TTS_MIC_BLOCK_COOLDOWN_SECONDS))
            set_assistant_speaking(False)
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                    _log_tts("info", "audio temp file removed", {"audio_path": temp_file})
                except Exception as exc:
                    _log_tts("warning", "failed to remove temp audio", {"audio_path": temp_file, "error": repr(exc)})
            _log_tts("info", "done", {"text": text})


def speak_text_async(text: str) -> bool:
    """Chạy TTS nền để không chặn luồng trả response/log."""
    if not text:
        _log_tts("warning", "skip empty text async", {"text": text})
        return False

    worker = threading.Thread(target=speak_text, args=(text,), daemon=True)
    worker.start()
    _log_tts("info", "async worker started", {"text": text, "thread_name": worker.name})
    return True


def speak(text: str) -> bool:
    return speak_text(text)
