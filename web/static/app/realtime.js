import { app } from "./core.js";
import { fetchJson } from "./api.js";
import { addChatMessage, ensureWelcomeMessage, hydrateChatHistory, setChatStatus, setVoiceUiState, showChatEmptyState } from "./ui.js";
import { handleDeviceStateChanged, handleSnapshot } from "./devices.js";
import { handleAssistantTtsChunk, renderEventAsChat } from "./chat.js";

export function stopRealtimeAndPolling() {
    if (app.state.socket) {
        app.state.socket.disconnect();
        app.state.socket = null;
    }
    if (app.state.pollingIntervalId) {
        window.clearInterval(app.state.pollingIntervalId);
        app.state.pollingIntervalId = null;
    }
}

export async function pollEvents() {
    if (!app.state.isAuthenticated) {
        return;
    }
    try {
        const { result } = await fetchJson(`/api/events?since_id=${app.state.lastEventId}&limit=80`);
        (result.events || []).forEach((event) => {
            const source = String(event?.source || "").trim().toLowerCase();
            const payload = event?.payload && typeof event.payload === "object" ? event.payload : null;

            // Fallback khi realtime/socket chập chờn:
            // cập nhật trạng thái thiết bị trực tiếp từ event log backend.
            if (source === "device-state" && payload?.id) {
                handleDeviceStateChanged(payload);
            }

            renderEventAsChat(event);
        });
        app.state.lastEventId = Number(result.last_id || app.state.lastEventId);
    } catch (error) {
        if (!error.isAuth) {
            // Avoid chat spam from polling errors.
        }
    }
}

export function setupRealtime() {
    if (!app.state.isAuthenticated || app.state.socket) {
        return;
    }
    if (typeof io === "undefined") {
        addChatMessage("system", "Realtime chưa sẵn sàng trên trình duyệt hiện tại.", Date.now(), {
            isError: true,
            fingerprint: "socket-missing",
        });
        return;
    }

    try {
        app.state.socket = io({
            transports: ["polling"],
            upgrade: false,
            reconnection: true,
            reconnectionAttempts: Infinity,
            reconnectionDelay: 1500,
        });
    } catch (error) {
        addChatMessage("system", "Không khởi tạo được realtime, giao diện sẽ chuyển sang polling an toàn.", Date.now(), {
            isError: true,
            fingerprint: "socket-init-failed",
        });
        return;
    }

    app.state.socket.on("connect_error", () => { });
    app.state.socket.on("disconnect", () => {
        if (!app.state.isAuthenticated) {
            app.state.socket = null;
        }
    });
    app.state.socket.on("devices_snapshot", handleSnapshot);
    app.state.socket.on("device_state_changed", handleDeviceStateChanged);
    app.state.socket.on("assistant_tts_chunk", handleAssistantTtsChunk);
    app.state.socket.on("system_log", (payload) => {
        // Không đẩy system log nội bộ vào khung chat.
        void payload;
    });
}

export function initializeApp() {
    if (app.state.appInitialized) {
        return;
    }
    app.state.appInitialized = true;
    const restoredChat = hydrateChatHistory();
    if (!restoredChat) {
        showChatEmptyState();
    }
    ensureWelcomeMessage();
    setupRealtime();
    pollEvents();
    app.state.pollingIntervalId = window.setInterval(pollEvents, 3000);
}

export function prepareLockedShell() {
    showChatEmptyState();
    ensureWelcomeMessage();
    setChatStatus("Vui lòng đăng nhập để sử dụng điều khiển thiết bị", "error");
    setVoiceUiState({
        listening: false,
        text: "Đăng nhập để dùng micro",
        transcript: "Toàn bộ lệnh điều khiển đang bị khóa cho tới khi đăng nhập thành công.",
    });
}
