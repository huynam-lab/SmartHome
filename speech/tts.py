import asyncio
import io
import threading
import time
from queue import Empty, Full, Queue
from typing import Optional

import pygame

try:
    import edge_tts
except Exception:
    edge_tts = None

from config import ENABLE_TTS, TTS_MIC_BLOCK_COOLDOWN_SECONDS, TTS_QUEUE_SIZE
from core.voice_state import set_assistant_speaking, update_last_tts
from services.music_player import get_music_player


_TTS_LOCK = threading.Lock()
_TTS_QUEUE: "Queue[str]" = Queue(maxsize=max(1, int(TTS_QUEUE_SIZE)))
_TTS_WORKER_THREAD: Optional[threading.Thread] = None
_TTS_WORKER_LOCK = threading.Lock()
_PYGAME_LOCK = threading.Lock()


def split_text_for_tts(text: str, max_len: int = 220) -> list:
    return [text]


def _ensure_pygame_mixer() -> None:
    with _PYGAME_LOCK:
        if not pygame.mixer.get_init():
            pygame.mixer.init()


async def _stream_and_play(text: str):
    communicate = edge_tts.Communicate(
        text=text,
        voice="vi-VN-HoaiMyNeural",
    )

    audio_data = b""

    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]

    audio_buffer = io.BytesIO(audio_data)
    _ensure_pygame_mixer()
    pygame.mixer.music.load(audio_buffer)
    pygame.mixer.music.play()

    while pygame.mixer.music.get_busy():
        time.sleep(0.1)


def speak_text(text: str) -> bool:
    if not text:
        return False

    if not ENABLE_TTS:
        return True

    if edge_tts is None:
        return False

    with _TTS_LOCK:
        set_assistant_speaking(True)
        music_player = get_music_player()
        chunks = split_text_for_tts(text, max_len=220)

        try:
            try:
                music_player.duck_for_tts()
            except Exception:
                pass

            if not chunks:
                return False

            for chunk in chunks:
                if not chunk:
                    continue
                asyncio.run(_stream_and_play(chunk))

            return True
        finally:
            try:
                music_player.restore_after_tts()
            except Exception:
                pass
            update_last_tts(text)
            time.sleep(max(0.0, TTS_MIC_BLOCK_COOLDOWN_SECONDS))
            set_assistant_speaking(False)


def speak_text_async(text: str) -> bool:
    if not text:
        return False

    _ensure_tts_worker()

    try:
        _TTS_QUEUE.put_nowait(text)
        return True
    except Full:
        try:
            _TTS_QUEUE.get_nowait()
        except Empty:
            pass

        try:
            _TTS_QUEUE.put_nowait(text)
            return True
        except Full:
            return False


def _tts_worker_loop() -> None:
    while True:
        text = _TTS_QUEUE.get()
        try:
            speak_text(text)
        except Exception:
            pass
        finally:
            _TTS_QUEUE.task_done()


def _ensure_tts_worker() -> bool:
    global _TTS_WORKER_THREAD
    worker = _TTS_WORKER_THREAD
    if worker and worker.is_alive():
        return True

    with _TTS_WORKER_LOCK:
        worker = _TTS_WORKER_THREAD
        if worker and worker.is_alive():
            return True
        worker = threading.Thread(target=_tts_worker_loop, name="tts-worker", daemon=True)
        worker.start()
        _TTS_WORKER_THREAD = worker
    return True


def speak(text: str) -> bool:
    return speak_text(text)
