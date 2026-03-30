import threading
import time
from datetime import timedelta
from queue import Empty, Full, Queue

from flask import Flask, render_template, session
from flask_socketio import SocketIO, disconnect

from api.routes import api_bp
from config import CURRENT_JETSON_ID, FLASK_SECRET_KEY, RUN_WEB_SERVER, VOICE_POLL_INTERVAL_SECONDS, VOICE_QUEUE_SIZE
from controller.command_service import is_exit_command, process_text_command
from core.device_state_store import build_devices_snapshot
from core.event_bus import log_event
from core.realtime import emit_system_log, init_socketio
from core.voice_state import is_assistant_speaking
from speech.speech_to_text import print_microphone_list, recognize_once
from speech.tts import speak_text


socketio = SocketIO(cors_allowed_origins="*", async_mode="threading")


def create_app():
    app = Flask(
        __name__,
        template_folder="web/templates",
        static_folder="web/static",
        static_url_path="/static",
    )
    app.config.update(
        SECRET_KEY=FLASK_SECRET_KEY,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=False,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    )

    @app.get("/")
    def index():
        return render_template("index.html")

    app.register_blueprint(api_bp)
    socketio.init_app(app)
    init_socketio(socketio)

    @socketio.on("connect")
    def handle_connect():
        if not session.get("authenticated"):
            log_event(source="socketio", level="warning", message="Tu choi websocket vi chua dang nhap")
            disconnect()
            return

        session_jetson_id = str(session.get("jetson_id") or "").strip()
        if session_jetson_id != str(CURRENT_JETSON_ID).strip():
            log_event(
                source="socketio",
                level="warning",
                message="Tu choi websocket vi session khong dung Jetson",
                payload={"session_jetson_id": session_jetson_id, "current_jetson_id": CURRENT_JETSON_ID},
            )
            disconnect()
            return

        log_event(source="socketio", level="info", message="Client ket noi WebSocket")
        devices = []
        try:
            from api.device_api import list_devices

            devices = list_devices()
        except Exception as exc:
            log_event(source="socketio", level="error", message="Khong tao duoc snapshot khi connect", payload={"error": repr(exc)})

        build_devices_snapshot(devices)
        emit_system_log(message="Client da ket noi realtime", level="info")

    @socketio.on("disconnect")
    def handle_disconnect():
        log_event(source="socketio", level="warning", message="Client ngat ket noi WebSocket")

    return app


def run_jetson_voice_listener(stop_event: threading.Event, voice_queue: Queue):
    """Thread 1: Nhận giọng nói từ micro và đẩy vào queue."""
    log_event(source="jetson-mic", message="Khoi dong listener micro", level="info")

    while not stop_event.is_set():
        if is_assistant_speaking():
            print("[VOICE] Assistant dang noi, tam bo qua microphone input")
            time.sleep(0.05)
            continue

        text = recognize_once()
        if not text:
            continue

        if is_assistant_speaking():
            print("[VOICE] Assistant dang noi, tam bo qua ket qua microphone")
            continue

        print(f"[VOICE] user_text={text}")
        log_event(source="jetson-mic", message="Nghe duoc cau noi", level="info", payload={"text": text})

        try:
            voice_queue.put_nowait(text)
        except Full:
            dropped_text = voice_queue.get_nowait()
            voice_queue.put_nowait(text)
            log_event(
                source="jetson-mic",
                message="Queue day, da bo cau noi cu de uu tien cau moi",
                level="warning",
                payload={"dropped": dropped_text, "latest": text},
            )


def run_jetson_command_worker(stop_event: threading.Event, voice_queue: Queue):
    """Thread 2: Lấy text từ queue, gọi AI/intent, thực thi hành động và phản hồi."""
    log_event(source="voice-worker", message="Khoi dong worker xu ly lenh", level="info")

    while not stop_event.is_set():
        try:
            text = voice_queue.get(timeout=VOICE_POLL_INTERVAL_SECONDS)
        except Empty:
            continue

        if is_assistant_speaking():
            print("[VOICE] Assistant dang noi, tam bo qua command trong queue")
            voice_queue.task_done()
            continue

        # "ve thoi" chi dung xu ly lenh, KHONG tat he thong
        if is_exit_command(text):
            result = process_text_command(text, source="jetson-mic")
            print(f"[AI] reply={result.get('reply_text', '')}")
            print("[VOICE] resume listening")
            voice_queue.task_done()
            continue

        result = process_text_command(text, source="jetson-mic")
        print(f"[AI] reply={result.get('reply_text', '')}")
        print("[VOICE] resume listening")
        voice_queue.task_done()


if __name__ == "__main__":
    stop_event = threading.Event()
    voice_queue = Queue(maxsize=VOICE_QUEUE_SIZE)

    try:
        print_microphone_list()
    except Exception as exc:
        log_event(source="bootstrap", level="error", message="Không in được danh sách microphone", payload={"error": repr(exc)})

    try:
        speak_text("Hệ thống smart home đã khởi động.")
    except Exception as exc:
        log_event(source="bootstrap", level="error", message="TTS test khi khởi động thất bại", payload={"error": repr(exc)})

    listener_thread = threading.Thread(
        target=run_jetson_voice_listener,
        args=(stop_event, voice_queue),
        daemon=True,
    )
    worker_thread = threading.Thread(
        target=run_jetson_command_worker,
        args=(stop_event, voice_queue),
        daemon=True,
    )
    listener_thread.start()
    worker_thread.start()

    if RUN_WEB_SERVER:
        app = create_app()
        try:
            socketio.run(app, host="0.0.0.0", port=5000, debug=False, use_reloader=False)
        finally:
            stop_event.set()
    else:
        try:
            while not stop_event.is_set():
                time.sleep(0.3)
        except KeyboardInterrupt:
            stop_event.set()
