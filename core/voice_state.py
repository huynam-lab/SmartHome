import threading
import time
from typing import Tuple


assistant_speaking = threading.Event()
_tts_state_lock = threading.Lock()
last_tts_text = ""
last_tts_time = 0.0


def set_assistant_speaking(is_speaking: bool) -> None:
    if is_speaking:
        assistant_speaking.set()
    else:
        assistant_speaking.clear()


def is_assistant_speaking() -> bool:
    return assistant_speaking.is_set()


def update_last_tts(text: str) -> None:
    global last_tts_text, last_tts_time
    with _tts_state_lock:
        last_tts_text = (text or "").strip()
        last_tts_time = time.time()


def get_last_tts_state() -> Tuple[str, float]:
    with _tts_state_lock:
        return last_tts_text, last_tts_time
