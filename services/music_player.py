import json
import os
import shutil
import socket
import subprocess
import threading
import time
from typing import Any, Dict, Optional

from core.event_bus import log_event

try:
    import yt_dlp
except Exception as exc:  # pragma: no cover
    yt_dlp = None
    _YT_DLP_IMPORT_ERROR = repr(exc)
else:
    _YT_DLP_IMPORT_ERROR = ""


class MusicPlayer:
    """Phát và điều khiển nhạc bằng mpv IPC trên Linux/Jetson."""

    def __init__(
        self,
        socket_path: str = "/tmp/mpv_socket",
        default_volume: int = 50,
        command_timeout: float = 4.0,
        startup_timeout: float = 8.0,
        yt_timeout: float = 15.0,
        autoplay_count: int = 5,
    ) -> None:
        self.socket_path = socket_path
        self.default_volume = self._clamp_volume(default_volume)
        self.command_timeout = max(0.5, float(command_timeout))
        self.startup_timeout = max(1.0, float(startup_timeout))
        self.yt_timeout = max(3.0, float(yt_timeout))
        self.autoplay_count = max(1, int(autoplay_count))
        self._lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None
        self._current_query = ""
        self._current_title = ""
        self._current_source_url = ""
        self._playlist_items: list[Dict[str, str]] = []
        self._volume = self.default_volume
        self._tts_duck_snapshot: Optional[Dict[str, Any]] = None

    def play(self, query: str) -> Dict[str, Any]:
        clean_query = " ".join(str(query or "").split()).strip()
        if not clean_query:
            return self._error("Anh/chị nói rõ tên bài hát hoặc ca sĩ giúp em.")

        with self._lock:
            resolved = self._get_audio_playlist(clean_query)
            if not resolved.get("ok"):
                return resolved

            self._stop_unlocked(silent_if_missing=True)

            playlist_items = list(resolved.get("items") or [])
            first_audio_url = str((playlist_items[0] or {}).get("audio_url") or "")
            extra_audio_urls = [
                str(item.get("audio_url") or "").strip()
                for item in playlist_items[1:]
                if str(item.get("audio_url") or "").strip()
            ]

            start_result = self._start_player_unlocked(first_audio_url, extra_audio_urls=extra_audio_urls)
            if not start_result.get("ok"):
                return start_result

            self._current_query = clean_query
            self._current_title = str((playlist_items[0] or {}).get("title") or clean_query).strip()
            self._current_source_url = str((playlist_items[0] or {}).get("webpage_url") or "").strip()
            self._playlist_items = [
                {
                    "title": str(item.get("title") or "").strip(),
                    "webpage_url": str(item.get("webpage_url") or "").strip(),
                }
                for item in playlist_items
            ]

            return {
                "ok": True,
                "message": f"Dạ",
                "data": {
                    "query": self._current_query,
                    "title": self._current_title,
                    "webpage_url": self._current_source_url,
                    "queue_length": len(self._playlist_items),
                    "volume": self._volume,
                    "paused": False,
                    "is_playing": True,
                },
            }

    def stop(self) -> Dict[str, Any]:
        with self._lock:
            if not self._has_active_player_unlocked():
                self._cleanup_process_unlocked()
                return self._error("Hiện chưa có nhạc đang phát.")

            self._stop_unlocked(silent_if_missing=False)
            return {
                "ok": True,
                "message": "Dạ",
                "data": {
                    "query": "",
                    "title": "",
                    "volume": self._volume,
                    "paused": False,
                    "is_playing": False,
                },
            }

    def pause(self) -> Dict[str, Any]:
        with self._lock:
            if not self._has_active_player_unlocked():
                return self._error("Hiện chưa có nhạc đang phát.")

            result = self._send_command_unlocked({"command": ["set_property", "pause", True]})
            if not result.get("ok"):
                return self._error("Em chưa tạm dừng được nhạc.", data=self._build_status_unlocked())

            return {
                "ok": True,
                "message": "Em đã tạm dừng nhạc.",
                "data": self._build_status_unlocked(),
            }

    def resume(self) -> Dict[str, Any]:
        with self._lock:
            if not self._has_active_player_unlocked():
                return self._error("Hiện chưa có nhạc đang phát.")

            result = self._send_command_unlocked({"command": ["set_property", "pause", False]})
            if not result.get("ok"):
                return self._error("Em chưa phát tiếp được nhạc.", data=self._build_status_unlocked())

            return {
                "ok": True,
                "message": "Em đã phát tiếp nhạc.",
                "data": self._build_status_unlocked(),
            }

    def volume_up(self, step: int = 10) -> Dict[str, Any]:
        with self._lock:
            if not self._has_active_player_unlocked():
                return self._error("Hiện chưa có nhạc đang phát.")

            current_volume = self._get_volume_unlocked()
            new_volume = self._clamp_volume(current_volume + max(1, int(step or 10)))
            return self._set_volume_unlocked(new_volume, success_prefix="Em đã tăng âm lượng lên")

    def volume_down(self, step: int = 10) -> Dict[str, Any]:
        with self._lock:
            if not self._has_active_player_unlocked():
                return self._error("Hiện chưa có nhạc đang phát.")

            current_volume = self._get_volume_unlocked()
            new_volume = self._clamp_volume(current_volume - max(1, int(step or 10)))
            return self._set_volume_unlocked(new_volume, success_prefix="Em đã giảm âm lượng xuống")

    def set_volume(self, value: int = 50) -> Dict[str, Any]:
        with self._lock:
            if not self._has_active_player_unlocked():
                return self._error("Hiện chưa có nhạc đang phát.")
            return self._set_volume_unlocked(self._clamp_volume(value), success_prefix="Em đã đặt âm lượng ở mức")

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return self._build_status_unlocked()

    def is_playing(self) -> bool:
        with self._lock:
            status = self._build_status_unlocked()
            return bool(status.get("is_playing"))

    def send_command(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            return self._send_command_unlocked(payload)

    def duck_for_tts(self, step_delay: float = 0.06, step_size: int = 8) -> Dict[str, Any]:
        with self._lock:
            status = self._build_status_unlocked()
            if not status.get("is_running"):
                self._tts_duck_snapshot = None
                return {"ok": True, "message": "Không có nhạc để giảm khi TTS phát.", "data": status}

            current_volume = self._get_volume_unlocked()
            was_paused = bool(status.get("paused"))
            self._tts_duck_snapshot = {
                "volume": current_volume,
                "was_paused": was_paused,
            }

            if current_volume > 0:
                self._fade_volume_unlocked(start=current_volume, end=0, step_size=step_size, step_delay=step_delay)

            if not was_paused:
                self._send_command_unlocked({"command": ["set_property", "pause", True]})

            return {"ok": True, "message": "Đã giảm nhạc cho TTS.", "data": self._build_status_unlocked()}

    def restore_after_tts(self, step_delay: float = 0.06, step_size: int = 8) -> Dict[str, Any]:
        with self._lock:
            snapshot = self._tts_duck_snapshot
            self._tts_duck_snapshot = None
            if not snapshot:
                return {"ok": True, "message": "Không có nhạc cần khôi phục sau TTS.", "data": self._build_status_unlocked()}

            if not self._has_active_player_unlocked():
                return {"ok": True, "message": "Player nhạc không còn chạy sau TTS.", "data": self._build_status_unlocked()}

            target_volume = self._clamp_volume(snapshot.get("volume", self._volume))
            was_paused = bool(snapshot.get("was_paused"))

            if was_paused:
                self._send_command_unlocked({"command": ["set_property", "volume", target_volume]})
                self._volume = target_volume
            else:
                self._send_command_unlocked({"command": ["set_property", "pause", False]})
                self._send_command_unlocked({"command": ["set_property", "volume", 0]})
                self._volume = 0
                self._fade_volume_unlocked(start=0, end=target_volume, step_size=step_size, step_delay=step_delay)

            return {"ok": True, "message": "Đã khôi phục nhạc sau TTS.", "data": self._build_status_unlocked()}

    def _get_audio_playlist(self, query: str) -> Dict[str, Any]:
        if yt_dlp is None:
            return self._error(
                "Chưa có thư viện yt-dlp để phát nhạc.",
                data={"hint": "python3 -m pip install yt-dlp", "error": _YT_DLP_IMPORT_ERROR},
            )

        search_query = " ".join(str(query or "").split()).strip() or "nhạc hot"
        ydl_options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "default_search": f"ytsearch{self.autoplay_count}",
            "socket_timeout": self.yt_timeout,
            "format": "bestaudio/best",
        }

        try:
            with yt_dlp.YoutubeDL(ydl_options) as ydl:
                info = ydl.extract_info(f"ytsearch{self.autoplay_count}:{search_query}", download=False)
        except Exception as exc:
            self._log("error", "yt-dlp search failed", {"query": search_query, "error": repr(exc)})
            return self._error("Không tìm được nhạc trên YouTube.")

        entries = []
        if isinstance(info, dict) and info.get("entries"):
            entries = [item for item in info.get("entries") or [] if isinstance(item, dict)]
        elif isinstance(info, dict):
            entries = [info]

        if not entries:
            return self._error("Không tìm được nhạc trên YouTube.")

        playlist_items = []
        for entry in entries:
            audio_url = (
                entry.get("url")
                or (((entry.get("requested_formats") or [{}])[0]).get("url"))
                or (((entry.get("formats") or [{}])[-1]).get("url") if entry.get("formats") else "")
            )
            if not audio_url:
                continue
            playlist_items.append({
                "audio_url": str(audio_url).strip(),
                "title": str(entry.get("title") or search_query).strip(),
                "webpage_url": str(entry.get("webpage_url") or entry.get("original_url") or "").strip(),
            })

        if not playlist_items:
            return self._error("Không lấy được luồng audio từ YouTube.")

        self._log(
            "info",
            "resolved audio playlist",
            {"query": search_query, "count": len(playlist_items), "first_title": playlist_items[0]["title"]},
        )
        return {
            "ok": True,
            "items": playlist_items,
        }

    def _build_status_unlocked(self) -> Dict[str, Any]:
        active = self._has_active_player_unlocked()
        paused = False
        volume = self._volume

        if active:
            pause_result = self._send_command_unlocked({"command": ["get_property", "pause"]})
            if pause_result.get("ok"):
                paused = bool(pause_result.get("data"))

            volume_result = self._send_command_unlocked({"command": ["get_property", "volume"]})
            if volume_result.get("ok"):
                try:
                    volume = self._clamp_volume(volume_result.get("data"))
                    self._volume = volume
                except Exception:
                    volume = self._volume

        return {
            "ok": True,
            "is_running": active,
            "is_playing": active and not paused,
            "paused": paused,
            "query": self._current_query,
            "title": self._current_title,
            "volume": volume,
            "source_url": self._current_source_url,
            "queue_length": len(self._playlist_items),
        }

    def _set_volume_unlocked(self, value: int, success_prefix: str) -> Dict[str, Any]:
        result = self._send_command_unlocked({"command": ["set_property", "volume", value]})
        if not result.get("ok"):
            return self._error("Em chưa chỉnh được âm lượng.", data=self._build_status_unlocked())

        self._volume = self._clamp_volume(value)
        status = self._build_status_unlocked()
        return {
            "ok": True,
            "message": f"{success_prefix} {status.get('volume')} phần trăm.",
            "data": status,
        }

    def _fade_volume_unlocked(self, start: int, end: int, step_size: int, step_delay: float) -> None:
        current = self._clamp_volume(start)
        target = self._clamp_volume(end)
        step = max(1, int(step_size or 1))
        delay = max(0.0, float(step_delay))

        if current == target:
            self._send_command_unlocked({"command": ["set_property", "volume", target]})
            self._volume = target
            return

        direction = 1 if target > current else -1
        value = current
        while value != target:
            next_value = value + direction * step
            if direction > 0:
                next_value = min(next_value, target)
            else:
                next_value = max(next_value, target)
            self._send_command_unlocked({"command": ["set_property", "volume", next_value]})
            self._volume = next_value
            value = next_value
            if delay > 0:
                time.sleep(delay)

    def _get_volume_unlocked(self) -> int:
        result = self._send_command_unlocked({"command": ["get_property", "volume"]})
        if result.get("ok"):
            try:
                self._volume = self._clamp_volume(result.get("data"))
            except Exception:
                pass
        return self._volume

    def _has_active_player_unlocked(self) -> bool:
        self._cleanup_process_unlocked()
        return self._process is not None and self._process.poll() is None and os.path.exists(self.socket_path)

    def _start_player_unlocked(self, audio_url: str, extra_audio_urls: Optional[list[str]] = None) -> Dict[str, Any]:
        if not shutil.which("mpv"):
            return self._error("Chưa có mpv để phát nhạc.", data={"hint": "sudo apt install mpv"})

        self._cleanup_socket_unlocked(force=True)
        command = [
            "mpv",
            "--no-video",
            "--really-quiet",
            "--idle=no",
            f"--input-ipc-server={self.socket_path}",
            f"--volume={self._volume}",
            audio_url,
        ]
        for extra_url in list(extra_audio_urls or []):
            if extra_url:
                command.append(extra_url)

        try:
            self._process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except Exception as exc:
            self._process = None
            self._log("error", "mpv start failed", {"command": command, "error": repr(exc)})
            return self._error("Không khởi chạy được mpv để phát nhạc.")

        deadline = time.time() + self.startup_timeout
        while time.time() < deadline:
            if self._process.poll() is not None:
                stderr_text = ""
                try:
                    _, stderr_text = self._process.communicate(timeout=0.2)
                except Exception:
                    stderr_text = ""
                self._cleanup_process_unlocked()
                self._log("error", "mpv exited before ipc ready", {"stderr": stderr_text.strip()})
                return self._error("mpv không khởi động thành công.")

            if os.path.exists(self.socket_path):
                ping = self._send_command_unlocked({"command": ["get_property", "pause"]})
                if ping.get("ok"):
                    return {"ok": True}
            time.sleep(0.1)

        self._stop_process_only_unlocked()
        self._cleanup_socket_unlocked(force=True)
        return self._error("Hết thời gian chờ mpv sẵn sàng.")

    def _stop_unlocked(self, silent_if_missing: bool) -> Dict[str, Any]:
        had_player = self._has_active_player_unlocked()
        if had_player:
            self._send_command_unlocked({"command": ["quit-watch-later"]})
            deadline = time.time() + 2.5
            while time.time() < deadline:
                if not self._has_active_player_unlocked():
                    break
                time.sleep(0.1)

        self._stop_process_only_unlocked()
        self._cleanup_socket_unlocked(force=True)
        self._current_query = ""
        self._current_title = ""
        self._current_source_url = ""
        self._playlist_items = []

        if had_player or silent_if_missing:
            return {"ok": True}
        return self._error("Hiện chưa có nhạc đang phát.")

    def _stop_process_only_unlocked(self) -> None:
        if self._process is None:
            return

        process = self._process
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=2.0)
            except Exception:
                try:
                    process.kill()
                    process.wait(timeout=1.0)
                except Exception:
                    pass
        self._process = None

    def _cleanup_process_unlocked(self) -> None:
        if self._process is not None and self._process.poll() is not None:
            self._process = None
            self._cleanup_socket_unlocked(force=True)
            self._current_query = ""
            self._current_title = ""
            self._current_source_url = ""
            self._playlist_items = []
            self._tts_duck_snapshot = None

    def _cleanup_socket_unlocked(self, force: bool = False) -> None:
        if not os.path.exists(self.socket_path):
            return

        if not force and self._process is not None and self._process.poll() is None:
            return

        try:
            os.remove(self.socket_path)
        except FileNotFoundError:
            return
        except Exception as exc:
            self._log("warning", "failed to remove stale mpv socket", {"error": repr(exc), "socket_path": self.socket_path})

    def _send_command_unlocked(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._cleanup_process_unlocked()
        if not self._process or self._process.poll() is not None or not os.path.exists(self.socket_path):
            return self._error("Hiện chưa có player nhạc đang chạy.")

        raw_response = b""
        client: Optional[socket.socket] = None
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(self.command_timeout)
            client.connect(self.socket_path)
            client.sendall((json.dumps(payload, ensure_ascii=True) + "\n").encode("utf-8"))

            while not raw_response.endswith(b"\n"):
                chunk = client.recv(4096)
                if not chunk:
                    break
                raw_response += chunk
        except Exception as exc:
            self._log("warning", "mpv ipc command failed", {"payload": payload, "error": repr(exc)})
            return self._error("Không gửi được lệnh tới player nhạc.")
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

        if not raw_response:
            return self._error("Player nhạc không phản hồi.")

        try:
            decoded = json.loads(raw_response.decode("utf-8").strip())
        except Exception as exc:
            self._log("warning", "invalid mpv ipc response", {"payload": payload, "raw_response": raw_response.decode("utf-8", "ignore"), "error": repr(exc)})
            return self._error("Phản hồi từ player nhạc không hợp lệ.")

        if decoded.get("error") not in {"success", None}:
            return self._error("Player nhạc trả về lỗi.", data=decoded)

        return {"ok": True, "data": decoded.get("data"), "raw": decoded}

    @staticmethod
    def _clamp_volume(value: Any) -> int:
        try:
            return max(0, min(100, int(round(float(value)))))
        except Exception:
            return 50

    def _error(self, message: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {"ok": False, "message": message, "data": data or {}}

    def _log(self, level: str, message: str, payload: Optional[Dict[str, Any]] = None) -> None:
        print(f"[MUSIC] {message}")
        log_event(source="music-player", level=level, message=message, payload=payload or {})


_MUSIC_PLAYER = MusicPlayer()


def get_music_player() -> MusicPlayer:
    return _MUSIC_PLAYER
