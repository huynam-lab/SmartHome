import os
import secrets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_dotenv_if_present():
    """Nap file .env cung cap voi config.py neu bien moi truong chua co.
    Giup app van doc duoc GEMINI_API_KEY khi chay bang service/IDE
    ma khong can `source .env` thu cong.
    """
    env_path = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(env_path):
        return

    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip()
                value = value.replace("\r", "").replace("\n", "").strip().strip('"').strip("'")
                os.environ[key] = value
    except Exception:
        # Khong chan app khoi dong neu file .env loi format.
        pass


_load_dotenv_if_present()

IR_PACKET_DIR = os.path.join(BASE_DIR, "data", "ir_packets")
RF_PACKET_DIR = os.path.join(BASE_DIR, "data", "rf_packets")
DEVICE_MAP_FILE = os.path.join(BASE_DIR, "data", "device_map.json")
DEVICE_SCHEDULE_FILE = os.path.join(BASE_DIR, "data", "device_schedules.json")
DEVICE_TEMPLATE_FILE = os.path.join(BASE_DIR, "data", "device_template.json")
ENABLE_DEVICE_MAP_BACKUP = os.getenv("ENABLE_DEVICE_MAP_BACKUP", "0") == "1"

DISCOVER_TIMEOUT = float(os.getenv("DISCOVER_TIMEOUT", "2"))
LEARN_WAIT_SECONDS = 15
BROADLINK_CACHE_TTL_SECONDS = float(os.getenv("BROADLINK_CACHE_TTL_SECONDS", "20"))
BROADLINK_DEVICE_IP = os.getenv("BROADLINK_DEVICE_IP", "").strip()
BROADLINK_DEVICE_MAC = os.getenv("BROADLINK_DEVICE_MAC", "").strip().lower()

EXIT_WORDS = [
    "ve thoi",
    "về thôi"
]

WAKE_WORDS = [
    "li ly oi",
    "li ly ơi",
    "lily oi",
    "lily ơi",
]

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").replace("\r", "").replace("\n", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_TIMEOUT_SECONDS = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "8"))
GEMINI_RPM_LIMIT = int(os.getenv("GEMINI_RPM_LIMIT", "20"))
GEMINI_CLASSIFY_MAX_TOKENS = int(os.getenv("GEMINI_CLASSIFY_MAX_TOKENS", "120"))
GEMINI_CHAT_MAX_TOKENS = int(os.getenv("GEMINI_CHAT_MAX_TOKENS", "700"))
GEMINI_CHAT_RETRY_ENABLED = os.getenv("GEMINI_CHAT_RETRY_ENABLED", "1") == "1"
GEMINI_UNAVAILABLE_TEXT = os.getenv(
    "GEMINI_UNAVAILABLE_TEXT",
    "Em chưa trả lời được bằng Gemini lúc này. Anh/chị thử lại giúp em ạ.",
)

WEATHER_ENABLED = os.getenv("WEATHER_ENABLED", "1") == "1"
WEATHER_LATITUDE = float(os.getenv("WEATHER_LATITUDE", "10.7769"))
WEATHER_LONGITUDE = float(os.getenv("WEATHER_LONGITUDE", "106.7009"))
WEATHER_LOCATION_NAME = os.getenv("WEATHER_LOCATION_NAME", "TP.HCM").strip() or "TP.HCM"
DEVICE_LOCATION_NAME = os.getenv("DEVICE_LOCATION_NAME", WEATHER_LOCATION_NAME).strip() or WEATHER_LOCATION_NAME
DEVICE_LATITUDE = float(os.getenv("DEVICE_LATITUDE", str(WEATHER_LATITUDE)))
DEVICE_LONGITUDE = float(os.getenv("DEVICE_LONGITUDE", str(WEATHER_LONGITUDE)))
WEATHER_API_TIMEOUT_SECONDS = float(os.getenv("WEATHER_API_TIMEOUT_SECONDS", "6"))

LISTEN_TIMEOUT = int(os.getenv("LISTEN_TIMEOUT", "8"))
PHRASE_TIME_LIMIT = int(os.getenv("PHRASE_TIME_LIMIT", "6"))
AMBIENT_NOISE_DURATION = float(os.getenv("AMBIENT_NOISE_DURATION", "1"))
AMBIENT_NOISE_REFRESH_SECONDS = float(os.getenv("AMBIENT_NOISE_REFRESH_SECONDS", "45"))

# Dat MIC_DEVICE_INDEX=-1 de auto chon default microphone
MIC_DEVICE_INDEX = int(os.getenv("MIC_DEVICE_INDEX", "-1"))
MIC_PREFERRED_KEYWORDS = tuple(
    part.strip().lower()
    for part in os.getenv("MIC_PREFERRED_KEYWORDS", "usb,mic,microphone,pulse,default").split(",")
    if part.strip()
)

WAKE_REPLY_TEXT = os.getenv("WAKE_REPLY_TEXT", "Vâng , có em đây ")
ENABLE_TTS = os.getenv("ENABLE_TTS", "1") == "1"
TTS_LANGUAGE_CODE = os.getenv("TTS_LANGUAGE_CODE", "vi-VN")
TTS_VOICE_NAME = os.getenv("TTS_VOICE_NAME", "vi-VN-HoaiMyNeural")
TTS_SPEAKING_RATE = float(os.getenv("TTS_SPEAKING_RATE", "0.85"))
TTS_PITCH = float(os.getenv("TTS_PITCH", "0.0"))
TTS_VOLUME_GAIN_DB = float(os.getenv("TTS_VOLUME_GAIN_DB", "0.0"))
TTS_SYNTH_TIMEOUT_SECONDS = float(os.getenv("TTS_SYNTH_TIMEOUT_SECONDS", "20"))
RUN_WEB_SERVER = os.getenv("RUN_WEB_SERVER", "1") == "1"
VOICE_QUEUE_SIZE = int(os.getenv("VOICE_QUEUE_SIZE", "16"))
VOICE_POLL_INTERVAL_SECONDS = float(os.getenv("VOICE_POLL_INTERVAL_SECONDS", "0.05"))
TTS_MIC_BLOCK_COOLDOWN_SECONDS = float(os.getenv("TTS_MIC_BLOCK_COOLDOWN_SECONDS", "1.2"))
TTS_ECHO_IGNORE_WINDOW_SECONDS = float(os.getenv("TTS_ECHO_IGNORE_WINDOW_SECONDS", "3.0"))
VOICE_BLOCK_SLEEP_SECONDS = float(os.getenv("VOICE_BLOCK_SLEEP_SECONDS", "0.05"))

FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "").strip() or secrets.token_hex(32)
MONGO_URI = os.getenv("MONGO_URI", "").strip()
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "smart_home").strip() or "smart_home"
AUTH_COLLECTION_NAME = os.getenv("AUTH_COLLECTION_NAME", "tai_khoan").strip() or "tai_khoan"
CURRENT_JETSON_ID = os.getenv("CURRENT_JETSON_ID", "JETSON_001").strip() or "JETSON_001"

# Khi khong phai lenh dieu khien, tro ly se tra loi hoi dap thong thuong.
CHAT_FALLBACK_TEXT = os.getenv(
    "CHAT_FALLBACK_TEXT",
    "Em đang lắng nghe. Nếu cần điều khiển thiết bị, anh/chị nói rõ ví dụ: bật điều hòa hoặc tắt điều hòa.",
)

DEBUG_VOICE = os.getenv("DEBUG_VOICE", "0") == "1"
SUPPRESS_NATIVE_AUDIO_LOGS = os.getenv("SUPPRESS_NATIVE_AUDIO_LOGS", "1") == "1"
