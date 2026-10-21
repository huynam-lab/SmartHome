import json, os, shutil, socket, subprocess, sys, threading, time
from typing import Any, Dict, List, Optional
from core.event_bus import log_event

class MusicPlayer:
    def __init__(self, socket_path="/tmp/mpv_socket", default_volume=50, command_timeout=4.0, startup_timeout=8.0, yt_timeout=15.0, autoplay_count=5, playlist_cache_ttl=300.0):
        self.socket_path = socket_path
        self.default_volume = self._clamp_volume(default_volume)
        self.command_timeout = max(.5, float(command_timeout))
        self.startup_timeout = max(1., float(startup_timeout))
        self.yt_timeout = max(3., float(yt_timeout))
        self.autoplay_count = max(1, int(autoplay_count))
        self.playlist_cache_ttl = max(10., float(playlist_cache_ttl))
        self.python_path = sys.executable
        self.deno_path = shutil.which("deno") or os.path.expanduser("~/.deno/bin/deno")
        self.mpv_path = shutil.which("mpv") or "/usr/bin/mpv"
        self._lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None
        self._yt_process: Optional[subprocess.Popen] = None
        self._current_query = ""
        self._current_title = ""
        self._current_source_url = ""
        self._playlist_items: List[Dict[str, str]] = []
        self._playlist_cache: Dict[str, Dict[str, Any]] = {}
        self._volume = self.default_volume
        self._tts_duck_snapshot: Optional[Dict[str, Any]] = None

    def play(self, query: str) -> Dict[str, Any]:
        query = " ".join(str(query or "").split()).strip()
        if not query: return self._error("Anh/chị nói rõ tên bài hát hoặc ca sĩ giúp em.")
        with self._lock:
            resolved = self._get_audio_playlist(query)
            if not resolved.get("ok"): return resolved
            items = list(resolved.get("items") or [])
            if not items: return self._error("Không tìm được nhạc trên YouTube.")
            item = items[0]
            source = str(item.get("webpage_url") or "").strip()
            if not source: return self._error("Không lấy được nguồn nhạc từ YouTube.")

            self._stop_unlocked(True)
            result = self._start_player_unlocked(source)
            if not result.get("ok"): return result
            self._current_query = query
            self._current_title = str(item.get("title") or query).strip()
            self._current_source_url = str(item.get("webpage_url") or "").strip()
            self._playlist_items = [{"title": str(x.get("title") or "").strip(), "webpage_url": str(x.get("webpage_url") or "").strip()} for x in items]
            return {"ok": True, "message": "Dạ", "data": {"query": query, "title": self._current_title, "webpage_url": self._current_source_url, "queue_length": len(items), "volume": self._volume, "paused": False, "is_playing": True}}

    def stop(self) -> Dict[str, Any]:
        with self._lock:
            if not self._has_active_player_unlocked():
                self._cleanup_process_unlocked()
                return self._error("Hiện chưa có nhạc đang phát.")
            self._stop_unlocked(False)
            return {"ok": True, "message": "Dạ", "data": {"query": "", "title": "", "volume": self._volume, "paused": False, "is_playing": False}}

    def pause(self) -> Dict[str, Any]:
        with self._lock:
            if not self._has_active_player_unlocked(): return self._error("Hiện chưa có nhạc đang phát.")
            r = self._send_command_unlocked({"command": ["set_property", "pause", True]})
            return {"ok": True, "message": "Em đã tạm dừng nhạc.", "data": self._build_status_unlocked()} if r.get("ok") else self._error("Em chưa tạm dừng được nhạc.")

    def resume(self) -> Dict[str, Any]:
        with self._lock:
            if not self._has_active_player_unlocked(): return self._error("Hiện chưa có nhạc đang phát.")
            r = self._send_command_unlocked({"command": ["set_property", "pause", False]})
            return {"ok": True, "message": "Em đã phát tiếp nhạc.", "data": self._build_status_unlocked()} if r.get("ok") else self._error("Em chưa phát tiếp được nhạc.")

    def volume_up(self, step=10) -> Dict[str, Any]:
        with self._lock:
            if not self._has_active_player_unlocked(): return self._error("Hiện chưa có nhạc đang phát.")
            return self._set_volume_unlocked(self._clamp_volume(self._get_volume_unlocked() + max(1, int(step or 10))), "Em đã tăng âm lượng lên")

    def volume_down(self, step=10) -> Dict[str, Any]:
        with self._lock:
            if not self._has_active_player_unlocked(): return self._error("Hiện chưa có nhạc đang phát.")
            return self._set_volume_unlocked(self._clamp_volume(self._get_volume_unlocked() - max(1, int(step or 10))), "Em đã giảm âm lượng xuống")

    def set_volume(self, value=50) -> Dict[str, Any]:
        with self._lock:
            if not self._has_active_player_unlocked(): return self._error("Hiện chưa có nhạc đang phát.")
            return self._set_volume_unlocked(self._clamp_volume(value), "Em đã đặt âm lượng ở mức")

    def status(self) -> Dict[str, Any]:
        with self._lock: return self._build_status_unlocked()

    def is_playing(self) -> bool:
        with self._lock: return bool(self._build_status_unlocked().get("is_playing"))

    def send_command(self, payload) -> Dict[str, Any]:
        with self._lock: return self._send_command_unlocked(payload)

    def duck_for_tts(self, step_delay=.06, step_size=8) -> Dict[str, Any]:
        with self._lock:
            status = self._build_status_unlocked()
            if not status.get("is_running"):
                self._tts_duck_snapshot = None
                return {"ok": True, "message": "Không có nhạc để giảm khi TTS phát.", "data": status}
            volume, paused = self._get_volume_unlocked(), bool(status.get("paused"))
            self._tts_duck_snapshot = {"volume": volume, "was_paused": paused}
            if volume > 0: self._fade_volume_unlocked(volume, 0, step_size, step_delay)
            if not paused: self._send_command_unlocked({"command": ["set_property", "pause", True]})
            return {"ok": True, "message": "Đã giảm nhạc cho TTS.", "data": self._build_status_unlocked()}

    def restore_after_tts(self, step_delay=.06, step_size=8) -> Dict[str, Any]:
        with self._lock:
            snap = self._tts_duck_snapshot
            self._tts_duck_snapshot = None
            if not snap: return {"ok": True, "message": "Không có nhạc cần khôi phục sau TTS.", "data": self._build_status_unlocked()}
            if not self._has_active_player_unlocked(): return {"ok": True, "message": "Player nhạc không còn chạy sau TTS.", "data": self._build_status_unlocked()}
            target, paused = self._clamp_volume(snap.get("volume", self._volume)), bool(snap.get("was_paused"))
            if paused:
                self._send_command_unlocked({"command": ["set_property", "volume", target]}); self._volume = target
            else:
                self._send_command_unlocked({"command": ["set_property", "pause", False]})
                self._send_command_unlocked({"command": ["set_property", "volume", 0]}); self._volume = 0
                self._fade_volume_unlocked(0, target, step_size, step_delay)
            return {"ok": True, "message": "Đã khôi phục nhạc sau TTS.", "data": self._build_status_unlocked()}

    def _yt_base_cmd(self) -> List[str]:
        return [self.python_path, "-m", "yt_dlp", "--js-runtimes", f"deno:{self.deno_path}", "--extractor-args", "youtube:player_client=web_embedded"]

    def _get_audio_playlist(self, query: str) -> Dict[str, Any]:
        query = " ".join(str(query or "").split()).strip() or "nhạc hot"
        key, now = query.lower(), time.time()
        cached = self._playlist_cache.get(key)
        if cached and now - float(cached.get("saved_at", 0)) <= self.playlist_cache_ttl:
            items = list(cached.get("items") or [])
            if items: return {"ok": True, "items": items}

        cmd = self._yt_base_cmd() + ["--skip-download", "--flat-playlist", "--dump-single-json", f"ytsearch{self.autoplay_count}:{query}"]
        try:
            r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=self.yt_timeout)
            if r.returncode != 0: raise RuntimeError(r.stderr.strip())
            info = json.loads(r.stdout)
        except Exception as exc:
            self._log("error", "yt-dlp search failed", {"query": query, "error": repr(exc)})
            return self._error("Không tìm được nhạc trên YouTube.")

        items = []
        for e in info.get("entries") or []:
            if not isinstance(e, dict): continue
            video_id = str(e.get("id") or "").strip()
            url = str(e.get("webpage_url") or "").strip() or (f"https://www.youtube.com/watch?v={video_id}" if video_id else "")
            if url: items.append({"title": str(e.get("title") or query).strip(), "webpage_url": url})
        if not items: return self._error("Không tìm được nhạc trên YouTube.")

        self._playlist_cache[key] = {"saved_at": now, "items": items}
        self._log("info", "resolved playlist", {"query": query, "count": len(items), "first_title": items[0]["title"]})
        return {"ok": True, "items": items}

    def _start_player_unlocked(self, source: str, extra_audio_urls=None) -> Dict[str, Any]:
        if not os.path.isfile(self.deno_path): return self._error("Chưa tìm thấy Deno.")
        if not os.path.isfile(self.mpv_path): return self._error("Chưa có mpv để phát nhạc.")

        self._cleanup_socket_unlocked(True)

        yt_cmd = self._yt_base_cmd() + [
            "--no-playlist",
            "-f", "bestaudio/best",
            "-o", "-",
            source
        ]

        mpv_cmd = [
            self.mpv_path,
            "--no-video",
            "--cache=yes",
            "--cache-secs=1",
            "--idle=no",
            f"--input-ipc-server={self.socket_path}",
            f"--volume={self._volume}",
            "-"
        ]

        try:
            self._yt_process = subprocess.Popen(
                yt_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL
            )

            self._process = subprocess.Popen(
                mpv_cmd,
                stdin=self._yt_process.stdout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            if self._yt_process.stdout:
                self._yt_process.stdout.close()

        except Exception as exc:
            self._stop_process_only_unlocked()
            return self._error(
                "Không khởi chạy được luồng phát nhạc.",
                {"error": repr(exc)}
            )

        deadline = time.time() + 5

        while time.time() < deadline:
            if self._process.poll() is not None:
                self._stop_process_only_unlocked()
                return self._error("mpv không khởi động thành công.")

            if self._yt_process and self._yt_process.poll() is not None:
                self._stop_process_only_unlocked()
                return self._error("Không lấy được audio từ YouTube.")

            if os.path.exists(self.socket_path):
                r = self._send_command_unlocked(
                    {"command": ["get_property", "pause"]}
                )
                if r.get("ok"):
                    return {"ok": True}

            time.sleep(.03)

        self._stop_process_only_unlocked()
        self._cleanup_socket_unlocked(True)
        return self._error("mpv không phản hồi.")


    def _replace_playlist_unlocked(self, query: str, extra_audio_urls=None) -> Dict[str, Any]:
        self._stop_process_only_unlocked(); self._cleanup_socket_unlocked(True)
        return self._start_player_unlocked(query)

    def _build_status_unlocked(self) -> Dict[str, Any]:
        active, paused, volume = self._has_active_player_unlocked(), False, self._volume
        if active:
            r = self._send_command_unlocked({"command": ["get_property", "pause"]})
            if r.get("ok"): paused = bool(r.get("data"))
            r = self._send_command_unlocked({"command": ["get_property", "volume"]})
            if r.get("ok"):
                try: volume = self._clamp_volume(r.get("data")); self._volume = volume
                except Exception: pass
        return {"ok": True, "is_running": active, "is_playing": active and not paused, "paused": paused, "query": self._current_query, "title": self._current_title, "volume": volume, "source_url": self._current_source_url, "queue_length": len(self._playlist_items)}

    def _set_volume_unlocked(self, value, success_prefix):
        r = self._send_command_unlocked({"command": ["set_property", "volume", value]})
        if not r.get("ok"): return self._error("Em chưa chỉnh được âm lượng.", self._build_status_unlocked())
        self._volume = self._clamp_volume(value)
        status = self._build_status_unlocked()
        return {"ok": True, "message": f"{success_prefix} {status.get('volume')} phần trăm.", "data": status}

    def _fade_volume_unlocked(self, start, end, step_size, step_delay):
        current, target, step = self._clamp_volume(start), self._clamp_volume(end), max(1, int(step_size or 1))
        if current == target:
            self._send_command_unlocked({"command": ["set_property", "volume", target]}); self._volume = target
            return
        direction = 1 if target > current else -1
        while current != target:
            current = min(current + step, target) if direction > 0 else max(current - step, target)
            self._send_command_unlocked({"command": ["set_property", "volume", current]}); self._volume = current
            if step_delay > 0: time.sleep(step_delay)

    def _get_volume_unlocked(self):
        r = self._send_command_unlocked({"command": ["get_property", "volume"]})
        if r.get("ok"):
            try: self._volume = self._clamp_volume(r.get("data"))
            except Exception: pass
        return self._volume

    def _has_active_player_unlocked(self):
        self._cleanup_process_unlocked()
        return self._process is not None and self._process.poll() is None and os.path.exists(self.socket_path)

    def _stop_unlocked(self, silent_if_missing=False):
        had = self._has_active_player_unlocked()
        if had: self._send_command_unlocked({"command": ["quit"]})
        self._stop_process_only_unlocked(); self._cleanup_socket_unlocked(True)
        self._current_query = self._current_title = self._current_source_url = ""
        self._playlist_items = []; self._tts_duck_snapshot = None
        return {"ok": True} if had or silent_if_missing else self._error("Hiện chưa có nhạc đang phát.")

    def _stop_process_only_unlocked(self):
        for name in ("_process", "_yt_process"):
            p = getattr(self, name, None)
            if p and p.poll() is None:
                try: p.terminate(); p.wait(timeout=1.5)
                except Exception:
                    try: p.kill(); p.wait(timeout=.5)
                    except Exception: pass
            setattr(self, name, None)

    def _cleanup_process_unlocked(self):
        if self._process is not None and self._process.poll() is not None:
            self._stop_process_only_unlocked(); self._cleanup_socket_unlocked(True)
            self._current_query = self._current_title = self._current_source_url = ""
            self._playlist_items = []; self._tts_duck_snapshot = None

    def _cleanup_socket_unlocked(self, force=False):
        if not os.path.exists(self.socket_path): return
        if not force and self._process is not None and self._process.poll() is None: return
        try: os.remove(self.socket_path)
        except FileNotFoundError: pass
        except Exception as exc: self._log("warning", "failed to remove stale mpv socket", {"error": repr(exc), "socket_path": self.socket_path})

    def _send_command_unlocked(self, payload):
        if not self._process or self._process.poll() is not None or not os.path.exists(self.socket_path):
            return self._error("Hiện chưa có player nhạc đang chạy.")
        raw, client = b"", None
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(self.command_timeout); client.connect(self.socket_path)
            client.sendall((json.dumps(payload, ensure_ascii=True) + "\n").encode("utf-8"))
            while not raw.endswith(b"\n"):
                chunk = client.recv(4096)
                if not chunk: break
                raw += chunk
        except Exception as exc:
            self._log("warning", "mpv ipc command failed", {"payload": payload, "error": repr(exc)})
            return self._error("Không gửi được lệnh tới player nhạc.")
        finally:
            if client:
                try: client.close()
                except Exception: pass

        if not raw: return self._error("Player nhạc không phản hồi.")
        try: data = json.loads(raw.decode("utf-8").strip())
        except Exception as exc:
            self._log("warning", "invalid mpv ipc response", {"payload": payload, "error": repr(exc)})
            return self._error("Phản hồi từ player nhạc không hợp lệ.")
        if data.get("error") not in ("success", None): return self._error("Player nhạc trả về lỗi.", data)
        return {"ok": True, "data": data.get("data"), "raw": data}

    @staticmethod
    def _clamp_volume(value):
        try: return max(0, min(100, int(round(float(value)))))
        except Exception: return 50

    def _error(self, message, data=None):
        return {"ok": False, "message": message, "data": data or {}}

    def _log(self, level, message, payload=None):
        log_event(source="music-player", level=level, message=message, payload=payload or {})

_MUSIC_PLAYER = MusicPlayer()

def get_music_player() -> MusicPlayer:
    return _MUSIC_PLAYER