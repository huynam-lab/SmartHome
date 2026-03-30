const deviceListEl = document.getElementById("device-list");
const reloadBtnEl = document.getElementById("reload-btn");
const summaryTextEl = document.getElementById("summary-text");
const chatMessagesEl = document.getElementById("chat-messages");
const chatFormEl = document.getElementById("chat-form");
const chatStatusBannerEl = document.getElementById("chat-status-banner");
const chatStatusTextEl = document.getElementById("chat-status-text");
const micBtnEl = document.getElementById("mic-btn");
const voiceStatusTextEl = document.getElementById("voice-status-text");
const irLearnFormEl = document.getElementById("ir-learn-form");
const irStartBtnEl = document.getElementById("ir-start-btn");
const irCancelBtnEl = document.getElementById("ir-cancel-btn");
const appShellEl = document.getElementById("app-shell");
const authOverlayEl = document.getElementById("auth-overlay");
const authFormEl = document.getElementById("auth-form");
const authEmailEl = document.getElementById("auth-email");
const authPasswordEl = document.getElementById("auth-password");
const authJetsonFieldEl = document.getElementById("auth-jetson-field");
const authJetsonIdEl = document.getElementById("auth-jetson-id");
const authSubmitBtnEl = document.getElementById("auth-submit-btn");
const authErrorEl = document.getElementById("auth-error");
const authChipTextEl = document.getElementById("auth-chip-text");
const authLoginTabEl = document.getElementById("auth-login-tab");
const authRegisterTabEl = document.getElementById("auth-register-tab");
const authFormNoteEl = document.getElementById("auth-form-note");
const settingsBtnEl = document.getElementById("settings-btn");
const settingsMenuEl = document.getElementById("settings-menu");
const addDeviceBtnEl = document.getElementById("add-device-btn");
const learnCommandBtnEl = document.getElementById("learn-command-btn");
const changePasswordBtnEl = document.getElementById("change-password-btn");
const logoutBtnEl = document.getElementById("logout-btn");
const passwordModalEl = document.getElementById("password-modal");
const passwordBackdropEl = document.getElementById("password-backdrop");
const passwordCloseBtnEl = document.getElementById("password-close-btn");
const passwordFormEl = document.getElementById("password-form");
const currentPasswordEl = document.getElementById("current-password");
const newPasswordEl = document.getElementById("new-password");
const passwordSubmitBtnEl = document.getElementById("password-submit-btn");
const passwordFormStatusEl = document.getElementById("password-form-status");
const addDeviceModalEl = document.getElementById("add-device-modal");
const addDeviceBackdropEl = document.getElementById("add-device-backdrop");
const addDeviceCloseBtnEl = document.getElementById("add-device-close-btn");
const addDeviceFormEl = document.getElementById("add-device-form");
const addDeviceTemplateSelectEl = document.getElementById("add-device-template-select");
const addDeviceNameInputEl = document.getElementById("add-device-name-input");
const addDeviceSubmitBtnEl = document.getElementById("add-device-submit-btn");
const addDeviceCancelBtnEl = document.getElementById("add-device-cancel-btn");
const addDeviceModalStatusEl = document.getElementById("add-device-modal-status");
const irLearnModalEl = document.getElementById("ir-learn-modal");
const irLearnBackdropEl = document.getElementById("ir-learn-backdrop");
const irLearnCloseBtnEl = document.getElementById("ir-learn-close-btn");
const irDeviceSelectEl = document.getElementById("ir-device-select");
const irDeviceNameInputEl = document.getElementById("ir-device-name-input");
const irFilenameInputEl = document.getElementById("ir-filename-input");
const irSemanticKindSelectEl = document.getElementById("ir-semantic-kind-select");
const irSemanticValueFieldEl = document.getElementById("ir-semantic-value-field");
const irSemanticValueLabelEl = document.getElementById("ir-semantic-value-label");
const irSemanticValueInputEl = document.getElementById("ir-semantic-value-input");
const irSemanticValueHintEl = document.getElementById("ir-semantic-value-hint");
const irActionPhrasesInputEl = document.getElementById("ir-action-phrases-input");
const irLearnModalStatusEl = document.getElementById("ir-learn-modal-status");

let socket = null;
let recognition = null;
let lastEventId = 0;
let isListening = false;
let isSendingChat = false;
let currentVoiceSessionId = null;
let activeChatRequestId = null;
let hasShownWelcomeMessage = false;
let latestTranscript = "";
let voiceSendTimer = null;
let isSendingVoice = false;
let isLearningIr = false;
let isAuthenticated = false;
let isAuthSubmitting = false;
let appInitialized = false;
let pollingIntervalId = null;
let authMode = "login";
let isPasswordSubmitting = false;
let isAddDeviceSubmitting = false;
let irTemplateOptions = [];
let deviceInventory = [];

const ADDABLE_TEMPLATE_IDS = new Set(["den_thong_minh", "cong_tac", "dieu_hoa"]);

const VOICE_SEND_DEBOUNCE_MS = 1500;
const MIN_VOICE_TRANSCRIPT_LENGTH = 6;

const deviceStateMap = new Map();
const renderedMessageKeys = new Set();
const renderedEventIds = new Set();
const pendingUserTexts = new Map();
const pendingAssistantTexts = new Map();

const SpeechRecognitionApi = window.SpeechRecognition || window.webkitSpeechRecognition;

const DEVICE_TYPE_ICONS = {
    light: "💡",
    air_conditioner: "❄️",
    smart_switch: "🧲",
    fan: "🌀",
    tv: "📺",
    ir: "📡",
    relay: "🔌",
    unknown: "🔘",
};

const CHAT_ROLE_META = {
    user: { label: "Bạn", avatar: "🧑" },
    assistant: { label: "AI", avatar: "🤖" },
    system: { label: "Hệ thống", avatar: "✨" },
};

const USER_VISIBLE_EVENT_SOURCES = new Set(["user-chat", "assistant-chat", "chat", "assistant", "ai"]);
const BLOCKED_EVENT_SOURCES = new Set([
    "device-state",
    "device-control",
    "web-chat",
    "web-text",
    "web-voice",
    "stt",
    "realtime",
    "system_log",
    "socket",
    "ws",
    "websocket",
    "debug",
    "internal",
]);
const BLOCKED_MESSAGE_KEYWORDS = [
    "emit event thành công",
    "emit event thanh cong",
    "cập nhật trạng thái thiết bị",
    "cap nhat trang thai thiet bi",
    "device-state/info",
    "socket connected",
    "client kết nối websocket",
    "client ket noi websocket",
    "realtime info",
    "realtime snapshot",
    "snapshot",
    "debug",
    "websocket",
    "polling",
    "reconnect",
    "reconnecting",
    "kết nối lại",
    "ket noi lai",
    "đã kết nối realtime",
    "đang kết nối realtime",
    "mất kết nối realtime",
    "internal log",
    "không nhận diện được giọng nói",
    "khong nhan dien duoc giong noi",
];
const ALLOWED_ERROR_KEYWORDS = [
    "không",
    "lỗi",
    "thất bại",
    "chưa",
    "vui lòng",
    "hãy",
    "error",
    "failed",
    "micro",
    "jetson",
];

function setAuthFeedback(text = "", mode = "error") {
    if (!authErrorEl) {
        return;
    }

    authErrorEl.textContent = text;
    authErrorEl.classList.toggle("is-success", mode === "success");
}

function setPasswordFeedback(text = "", mode = "error") {
    if (!passwordFormStatusEl) {
        return;
    }

    passwordFormStatusEl.textContent = text;
    passwordFormStatusEl.classList.toggle("is-success", mode === "success");
}

function setIrLearnModalFeedback(text = "", mode = "error") {
    if (!irLearnModalStatusEl) {
        return;
    }

    irLearnModalStatusEl.textContent = text;
    irLearnModalStatusEl.classList.toggle("is-success", mode === "success");
}

function setAddDeviceFeedback(text = "", mode = "error") {
    if (!addDeviceModalStatusEl) {
        return;
    }

    addDeviceModalStatusEl.textContent = text;
    addDeviceModalStatusEl.classList.toggle("is-success", mode === "success");
}

function setAuthMode(mode = "login") {
    authMode = mode === "register" ? "register" : "login";
    const isRegisterMode = authMode === "register";

    authLoginTabEl?.classList.toggle("is-active", !isRegisterMode);
    authRegisterTabEl?.classList.toggle("is-active", isRegisterMode);
    authLoginTabEl?.setAttribute("aria-selected", String(!isRegisterMode));
    authRegisterTabEl?.setAttribute("aria-selected", String(isRegisterMode));
    authJetsonFieldEl?.classList.toggle("is-hidden", !isRegisterMode);

    if (authJetsonIdEl) {
        authJetsonIdEl.required = isRegisterMode;
        if (!isRegisterMode) {
            authJetsonIdEl.value = "";
        }
    }

    if (authSubmitBtnEl) {
        authSubmitBtnEl.textContent = isRegisterMode ? "Đăng ký tài khoản" : "Đăng nhập";
    }

    if (authFormNoteEl) {
        authFormNoteEl.textContent = isRegisterMode
            ? "Đăng ký tài khoản mới và nhập mã Jetson để liên kết thiết bị."
            : "Đăng nhập để mở quyền điều khiển thiết bị.";
    }

    setAuthFeedback("");
}

function updateAuthChip(text) {
    if (authChipTextEl) {
        authChipTextEl.textContent = text;
    }
}

function positionSettingsMenu() {
    if (!settingsBtnEl || !settingsMenuEl) {
        return;
    }

    settingsMenuEl.style.removeProperty("width");
    settingsMenuEl.style.removeProperty("--settings-menu-left");
    settingsMenuEl.style.removeProperty("--settings-menu-top");
}

function closeSettingsMenu() {
    settingsMenuEl?.classList.remove("is-open");
    settingsBtnEl?.setAttribute("aria-expanded", "false");
    settingsMenuEl?.setAttribute("aria-hidden", "true");
}

function openSettingsMenu() {
    if (!isAuthenticated) {
        return;
    }

    positionSettingsMenu();
    settingsMenuEl?.classList.add("is-open");
    settingsBtnEl?.setAttribute("aria-expanded", "true");
    settingsMenuEl?.setAttribute("aria-hidden", "false");
}

function toggleSettingsMenu() {
    if (settingsMenuEl?.classList.contains("is-open")) {
        closeSettingsMenu();
        return;
    }

    openSettingsMenu();
}

function openPasswordModal() {
    if (!isAuthenticated) {
        return;
    }

    closeSettingsMenu();
    setPasswordFeedback("");
    passwordFormEl?.reset();
    passwordModalEl?.classList.add("is-visible");
    passwordModalEl?.setAttribute("aria-hidden", "false");
    window.setTimeout(() => currentPasswordEl?.focus(), 0);
}

function closePasswordModal() {
    passwordModalEl?.classList.remove("is-visible");
    passwordModalEl?.setAttribute("aria-hidden", "true");
    passwordFormEl?.reset();
    setPasswordFeedback("");
}

function getAddableTemplateOptions() {
    return irTemplateOptions.filter((template) => ADDABLE_TEMPLATE_IDS.has(String(template.id || "").trim()));
}

function renderAddDeviceTemplateOptions() {
    if (!addDeviceTemplateSelectEl) {
        return;
    }

    const optionsMarkup = ['<option value="">Chọn loại thiết bị</option>'];
    getAddableTemplateOptions().forEach((template) => {
        const templateId = escapeHtml(template.id || "");
        const templateName = escapeHtml(template.template_name || templateId);
        optionsMarkup.push(`<option value="${templateId}">${templateName}</option>`);
    });

    addDeviceTemplateSelectEl.innerHTML = optionsMarkup.join("");
    addDeviceTemplateSelectEl.disabled = getAddableTemplateOptions().length === 0;
}

function getLearnableDevices() {
    return deviceInventory.filter((device) => String(device.control_type || "").trim().toLowerCase() === "ir");
}

function getDeviceById(deviceId) {
    return deviceInventory.find((device) => String(device.id || "") === String(deviceId || "")) || null;
}

function renderIrDeviceOptions() {
    if (!irDeviceSelectEl) {
        return;
    }

    const learnableDevices = getLearnableDevices();
    const optionsMarkup = ['<option value="">Chọn thiết bị đã thêm</option>'];
    learnableDevices.forEach((device) => {
        optionsMarkup.push(`<option value="${escapeHtml(device.id || "")}">${escapeHtml(device.name || device.id || "")}</option>`);
    });

    irDeviceSelectEl.innerHTML = optionsMarkup.join("");
    irDeviceSelectEl.disabled = learnableDevices.length === 0;
}

function syncIrDeviceSelection(deviceId = "") {
    const selectedDevice = getDeviceById(deviceId);
    if (!selectedDevice) {
        if (irDeviceNameInputEl) {
            irDeviceNameInputEl.value = "";
        }
        return;
    }

    if (irDeviceNameInputEl) {
        irDeviceNameInputEl.value = selectedDevice.name || selectedDevice.id || "";
    }

    const currentFilename = normalizeIrFilenameInput(irFilenameInputEl?.value || "");
    if (!currentFilename) {
        const suggestion = suggestIrFilename(selectedDevice.name || selectedDevice.id || "");
        if (suggestion && irFilenameInputEl) {
            irFilenameInputEl.value = suggestion;
        }
    }
}

async function loadIrTemplateOptions() {
    if (!isAuthenticated || irTemplateOptions.length > 0) {
        renderAddDeviceTemplateOptions();
        return;
    }

    if (addDeviceTemplateSelectEl) {
        addDeviceTemplateSelectEl.innerHTML = '<option value="">Đang tải danh sách mẫu thiết bị...</option>';
        addDeviceTemplateSelectEl.disabled = true;
    }

    try {
        const { result } = await fetchJson("/api/device-templates");
        irTemplateOptions = Array.isArray(result.templates) ? result.templates : [];
        renderAddDeviceTemplateOptions();
    } catch (error) {
        irTemplateOptions = [];
        if (addDeviceTemplateSelectEl) {
            addDeviceTemplateSelectEl.innerHTML = '<option value="">Không tải được danh sách mẫu thiết bị</option>';
            addDeviceTemplateSelectEl.disabled = true;
        }
        setAddDeviceFeedback(error.message || "Không tải được danh sách mẫu thiết bị.");
    }
}

function openAddDeviceModal() {
    if (!isAuthenticated || isAddDeviceSubmitting) {
        return;
    }

    closeSettingsMenu();
    setAddDeviceFeedback("");
    addDeviceFormEl?.reset();
    renderAddDeviceTemplateOptions();
    addDeviceModalEl?.classList.add("is-visible");
    addDeviceModalEl?.setAttribute("aria-hidden", "false");
    loadIrTemplateOptions().finally(() => {
        window.setTimeout(() => addDeviceTemplateSelectEl?.focus(), 0);
    });
}

function closeAddDeviceModal() {
    if (isAddDeviceSubmitting) {
        return;
    }

    addDeviceModalEl?.classList.remove("is-visible");
    addDeviceModalEl?.setAttribute("aria-hidden", "true");
    addDeviceFormEl?.reset();
    setAddDeviceFeedback("");
}

function openIrLearnModal() {
    if (!isAuthenticated || isLearningIr) {
        return;
    }

    closeSettingsMenu();
    setIrLearnModalFeedback("");
    irLearnFormEl?.reset();
    if (irSemanticKindSelectEl) {
        irSemanticKindSelectEl.value = "power.on";
    }
    updateIrSemanticForm();
    renderIrDeviceOptions();
    irLearnModalEl?.classList.add("is-visible");
    irLearnModalEl?.setAttribute("aria-hidden", "false");
    window.setTimeout(() => irDeviceSelectEl?.focus(), 0);
}

function closeIrLearnModal({ force = false } = {}) {
    if (isLearningIr && !force) {
        return;
    }

    irLearnModalEl?.classList.remove("is-visible");
    irLearnModalEl?.setAttribute("aria-hidden", "true");
    irLearnFormEl?.reset();
    updateIrSemanticForm();
    setIrLearnModalFeedback("");
}

function setControlLockState(locked) {
    document.body.classList.toggle("auth-locked", locked);
    appShellEl.classList.toggle("is-locked", locked);
    appShellEl.setAttribute("aria-hidden", String(locked));
    authOverlayEl.classList.toggle("is-visible", locked);
    authOverlayEl.setAttribute("aria-hidden", String(!locked));

    if (reloadBtnEl) {
        reloadBtnEl.disabled = locked;
    }

    if (micBtnEl) {
        micBtnEl.disabled = locked || isSendingChat;
    }

    if (learnCommandBtnEl) {
        learnCommandBtnEl.disabled = locked || isLearningIr;
    }

    if (addDeviceBtnEl) {
        addDeviceBtnEl.disabled = locked || isAddDeviceSubmitting;
    }

    if (irStartBtnEl) {
        irStartBtnEl.disabled = locked || isLearningIr;
    }

    if (irCancelBtnEl) {
        irCancelBtnEl.disabled = locked || isLearningIr;
    }

    if (addDeviceSubmitBtnEl) {
        addDeviceSubmitBtnEl.disabled = locked || isAddDeviceSubmitting;
    }

    if (addDeviceCancelBtnEl) {
        addDeviceCancelBtnEl.disabled = locked || isAddDeviceSubmitting;
    }

    if (locked) {
        window.setTimeout(() => {
            authEmailEl?.focus();
        }, 0);
    }
}

function stopRealtimeAndPolling() {
    if (socket) {
        socket.disconnect();
        socket = null;
    }

    if (pollingIntervalId) {
        window.clearInterval(pollingIntervalId);
        pollingIntervalId = null;
    }
}

function lockControlUi(message = "Vui lòng đăng nhập để mở quyền điều khiển thiết bị.") {
    isAuthenticated = false;
    appInitialized = false;
    stopRealtimeAndPolling();
    clearVoiceSendTimer();

    if (recognition && isListening) {
        try {
            recognition.stop();
        } catch (error) {
            console.warn("[auth] recognition.stop() failed", error);
        }
    }

    resetVoiceState();
    closeSettingsMenu();
    closePasswordModal();
    closeAddDeviceModal();
    setAuthFeedback(message, "error");
    updateAuthChip("Đăng nhập để mở quyền điều khiển");
    setControlLockState(true);
    setChatStatus("Vui lòng đăng nhập để sử dụng điều khiển thiết bị", "error");
    setVoiceUiState({
        listening: false,
        text: "Đăng nhập để dùng micro",
        transcript: "Toàn bộ lệnh điều khiển đang bị khóa cho đến khi đăng nhập thành công.",
    });
    setIrLearnStatus("Vui lòng đăng nhập để học lệnh và điều khiển thiết bị.", "error");
}

async function fetchJson(url, options = {}) {
    const response = await fetch(url, options);
    const result = await response.json().catch(() => ({}));

    if (response.status === 401) {
        const message = result.message || "Phiên đăng nhập không hợp lệ. Vui lòng đăng nhập lại.";
        const authError = new Error(message);
        authError.isAuth = true;
        lockControlUi(message);
        throw authError;
    }

    if (!response.ok || (result && result.ok === false && options.allowResultError !== true)) {
        const requestError = new Error(result.message || result.reply_text || "Yêu cầu không thành công.");
        requestError.result = result;
        throw requestError;
    }

    return { response, result };
}

async function handleLogout() {
    closeSettingsMenu();

    try {
        await fetchJson("/api/auth/logout", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
        });
    } catch (error) {
        // Ke ca khi request logout loi, van khoa UI tai local.
    }

    lockControlUi("Bạn đã đăng xuất. Vui lòng đăng nhập lại để tiếp tục.");
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

function createMessageId(prefix = "msg") {
    const randomText = Math.random().toString(36).slice(2, 10);
    return `${prefix}-${Date.now()}-${randomText}`;
}

function normalizeMessageText(text) {
    return String(text || "").trim().replaceAll(/\s+/g, " ").toLowerCase();
}

function buildDedupeKey(role, text, fingerprint = "") {
    return `${role}::${normalizeMessageText(text)}::${fingerprint}`;
}

function rememberRecentMessage(setMap, text, ttl = 12000) {
    const key = normalizeMessageText(text);
    setMap.set(key, Date.now() + ttl);

    window.setTimeout(() => {
        const expiresAt = setMap.get(key);
        if (expiresAt && expiresAt <= Date.now()) {
            setMap.delete(key);
        }
    }, ttl + 100);
}

function hasRecentMessage(setMap, text) {
    const key = normalizeMessageText(text);
    const expiresAt = setMap.get(key);
    if (!expiresAt) {
        return false;
    }

    if (expiresAt <= Date.now()) {
        setMap.delete(key);
        return false;
    }

    return true;
}

function formatTime(ts) {
    return new Date(ts || Date.now()).toLocaleTimeString("vi-VN", {
        hour: "2-digit",
        minute: "2-digit",
    });
}

function formatActionLabel(action) {
    const labels = { on: "Bật", off: "Tắt", "power.on": "Bật", "power.off": "Tắt" };
    return labels[action] || String(action || "").replaceAll("_", " ");
}

function formatState(state) {
    const labels = {
        on: "Đang bật",
        off: "Đang tắt",
        unknown: "Trạng thái chưa xác thực",
    };

    return labels[state] || state || "Chưa rõ";
}

function getEffectiveDeviceState(device) {
    if (!device) {
        return "unknown";
    }

    if (device.state && typeof device.state === "object") {
        if (device.state.power === "on" || device.state.power === "off") {
            return device.state.power;
        }
    }

    if (device.state === "on" || device.state === "off") {
        return device.state;
    }

    if (device.state === "power.on" || device.state === "power.off") {
        return device.state === "power.on" ? "on" : "off";
    }

    if (device.last_command_status === "sent" && ["on", "off", "power.on", "power.off"].includes(device.last_command)) {
        return ["on", "power.on"].includes(device.last_command) ? "on" : "off";
    }

    return "unknown";
}

function formatCommandStatus(device) {
    if (!device) {
        return "Trạng thái chưa xác thực";
    }

    const effectiveState = getEffectiveDeviceState(device);
    if (device.state_verified && (effectiveState === "on" || effectiveState === "off")) {
        return formatState(effectiveState);
    }

    if (effectiveState === "on" || effectiveState === "off") {
        return formatState(effectiveState);
    }

    return "Trạng thái chưa xác thực";
}

function getActionButtonClass(action) {
    if (action === "on" || action === "power.on") return "btn-on";
    if (action === "off" || action === "power.off") return "btn-off";
    return "btn-default";
}

function getDeviceIcon(device) {
    return DEVICE_TYPE_ICONS[device?.type] || DEVICE_TYPE_ICONS.unknown;
}

function getStatusBannerClass(state, processing = false) {
    if (processing) {
        return "device-status-banner";
    }

    if (state === "on") {
        return "device-status-banner is-on";
    }

    if (state === "off") {
        return "device-status-banner is-off";
    }

    return "device-status-banner";
}

function setSummaryText(text) {
    summaryTextEl.textContent = text;
}

function setIrLearnStatus() {}

function normalizeIrFilenameInput(value) {
    return String(value || "").trim().replaceAll(/\s+/g, "");
}

function slugifyVietnameseText(value) {
    return String(value || "")
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(/đ/gi, "d")
        .replace(/[^a-zA-Z0-9\s]/g, " ")
        .trim()
        .replace(/\s+/g, "_")
        .toLowerCase();
}

function suggestIrFilename(deviceName) {
    const normalizedName = slugifyVietnameseText(deviceName);
    if (!normalizedName) {
        return "";
    }

    return `${normalizedName}_on.bin`;
}

function suggestCommandFilename(deviceName, commandKey) {
    const normalizedName = slugifyVietnameseText(deviceName);
    const normalizedCommand = slugifyVietnameseText(String(commandKey || "").replaceAll(".", " "));
    if (!normalizedName || !normalizedCommand) {
        return "";
    }

    return `${normalizedName}_${normalizedCommand}.bin`;
}

function parseTagInput(value) {
    return String(value || "")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
}

function parseMultilinePhrases(value) {
    return Array.from(new Set(
        String(value || "")
            .split(/\n+/)
            .map((item) => item.trim())
            .filter(Boolean)
    ));
}

function getIrSemanticConfig(kind) {
    const configs = {
        "power.on": {
            requiresValue: false,
        },
        "power.off": {
            requiresValue: false,
        },
        "timer.off_after": {
            requiresValue: true,
            label: "Số phút",
            hint: "Ví dụ: nhập 1 để tạo lệnh hẹn tắt sau 1 phút.",
            min: "1",
            step: "1",
            placeholder: "Ví dụ: 1",
        },
        "climate.set_temperature": {
            requiresValue: true,
            label: "Nhiệt độ",
            hint: "Ví dụ: nhập 24 để tạo lệnh đặt điều hòa 24 độ.",
            min: "16",
            step: "1",
            placeholder: "Ví dụ: 24",
        },
    };
    return configs[kind] || configs["power.on"];
}

function updateIrSemanticForm() {
    const config = getIrSemanticConfig(String(irSemanticKindSelectEl?.value || "power.on"));
    const requiresValue = Boolean(config.requiresValue);

    irSemanticValueFieldEl?.classList.toggle("is-hidden", !requiresValue);
    if (irSemanticValueLabelEl) {
        irSemanticValueLabelEl.textContent = config.label || "Giá trị";
    }
    if (irSemanticValueHintEl) {
        irSemanticValueHintEl.textContent = config.hint || "";
    }
    if (irSemanticValueInputEl) {
        irSemanticValueInputEl.required = requiresValue;
        irSemanticValueInputEl.min = config.min || "1";
        irSemanticValueInputEl.step = config.step || "1";
        irSemanticValueInputEl.placeholder = config.placeholder || "";
        if (!requiresValue) {
            irSemanticValueInputEl.value = "";
        }
    }
}

function buildSemanticActionPayload(kind, rawValue) {
    const normalizedKind = String(kind || "").trim();
    const valueText = String(rawValue || "").trim();

    if (normalizedKind === "power.on") {
        return {
            actionKey: "power.on",
            semantic: { domain: "power", operation: "on" },
        };
    }

    if (normalizedKind === "power.off") {
        return {
            actionKey: "power.off",
            semantic: { domain: "power", operation: "off" },
        };
    }

    if (normalizedKind === "timer.off_after") {
        const minutes = Number.parseInt(valueText, 10);
        if (!Number.isFinite(minutes) || minutes <= 0) {
            throw new Error("Vui lòng nhập số phút hợp lệ cho lệnh hẹn tắt.");
        }
        return {
            actionKey: `timer.off_after_${minutes}_min`,
            semantic: {
                domain: "timer",
                operation: "off_after",
                duration_seconds: minutes * 60,
            },
        };
    }

    if (normalizedKind === "climate.set_temperature") {
        const temperature = Number.parseInt(valueText, 10);
        if (!Number.isFinite(temperature) || temperature <= 0) {
            throw new Error("Vui lòng nhập nhiệt độ hợp lệ.");
        }
        return {
            actionKey: `climate.set_${temperature}c`,
            semantic: {
                domain: "climate",
                operation: "set_temperature",
                temperature_c: temperature,
            },
        };
    }

    return {
        actionKey: inferActionKeyFromFilename(""),
        semantic: {},
    };
}

function buildDefaultActionPhrases(deviceName, kind, rawValue) {
    const targetName = String(deviceName || "").trim().toLowerCase();
    if (!targetName) {
        return [];
    }

    if (kind === "power.on") {
        return [`bật ${targetName}`];
    }
    if (kind === "power.off") {
        return [`tắt ${targetName}`];
    }
    if (kind === "timer.off_after") {
        const minutes = Number.parseInt(String(rawValue || "").trim(), 10);
        if (!Number.isFinite(minutes) || minutes <= 0) {
            return [];
        }
        return [`tắt ${targetName} sau ${minutes} phút`, `bật ${targetName} ${minutes} phút`];
    }
    if (kind === "climate.set_temperature") {
        const temperature = Number.parseInt(String(rawValue || "").trim(), 10);
        if (!Number.isFinite(temperature) || temperature <= 0) {
            return [];
        }
        return [`bật ${targetName} ${temperature} độ`, `${targetName} ${temperature} độ`];
    }
    return [];
}

function isValidIrFilename(filename) {
    return /^[a-zA-Z0-9]+_[a-zA-Z0-9]+_[a-zA-Z0-9]+\.bin$/i.test(normalizeIrFilenameInput(filename));
}

function setIrLearnLoadingState(loading) {
    isLearningIr = loading;
    if (irStartBtnEl) {
        irStartBtnEl.disabled = loading;
    }

    if (irCancelBtnEl) {
        irCancelBtnEl.disabled = loading;
    }

    irLearnCloseBtnEl && (irLearnCloseBtnEl.disabled = loading);
    irDeviceSelectEl && (irDeviceSelectEl.disabled = loading);
    if (irDeviceNameInputEl) {
        irDeviceNameInputEl.disabled = loading;
    }
    if (irFilenameInputEl) {
        irFilenameInputEl.disabled = loading;
    }
    if (irSemanticKindSelectEl) {
        irSemanticKindSelectEl.disabled = loading;
    }
    if (irSemanticValueInputEl) {
        irSemanticValueInputEl.disabled = loading;
    }
    if (irActionPhrasesInputEl) {
        irActionPhrasesInputEl.disabled = loading;
    }
}

function setAddDeviceLoadingState(loading) {
    isAddDeviceSubmitting = loading;
    if (addDeviceSubmitBtnEl) {
        addDeviceSubmitBtnEl.disabled = loading;
    }

    if (addDeviceCancelBtnEl) {
        addDeviceCancelBtnEl.disabled = loading;
    }

    if (addDeviceCloseBtnEl) {
        addDeviceCloseBtnEl.disabled = loading;
    }

    if (addDeviceTemplateSelectEl) {
        addDeviceTemplateSelectEl.disabled = loading;
    }

    if (addDeviceNameInputEl) {
        addDeviceNameInputEl.disabled = loading;
    }
}

function setChatStatus(text, mode = "live") {
    chatStatusTextEl.textContent = text;
    chatStatusBannerEl.className = "chat-status-banner";

    if (mode === "error") {
        chatStatusBannerEl.classList.add("is-error");
        return;
    }

    if (mode === "processing") {
        chatStatusBannerEl.classList.add("is-processing");
        return;
    }

    chatStatusBannerEl.classList.add("is-live");
}

function setVoiceUiState({ listening = false, transcript = "", text = "Chạm để bắt đầu nói" } = {}) {
    isListening = listening;
    if (voiceStatusTextEl) {
        voiceStatusTextEl.textContent = text;
    }
    micBtnEl.classList.toggle("is-listening", listening);
    micBtnEl.querySelector(".icon-btn-symbol").textContent = listening ? "⏹️" : "🎙️";
    micBtnEl.setAttribute("aria-label", listening ? "Dừng ghi âm" : "Bắt đầu ghi âm");
}

function clearVoiceSendTimer() {
    if (!voiceSendTimer) {
        return;
    }

    window.clearTimeout(voiceSendTimer);
    voiceSendTimer = null;
}

function resetVoiceState({ keepTranscript = false } = {}) {
    clearVoiceSendTimer();
    currentVoiceSessionId = null;
    isSendingVoice = false;

    if (!keepTranscript) {
        latestTranscript = "";
    }
}

function hasMeaningfulVoiceTranscript(transcript) {
    const normalizedTranscript = String(transcript || "").trim();
    return normalizedTranscript.length >= MIN_VOICE_TRANSCRIPT_LENGTH;
}

function updatePendingVoiceTranscript(transcript) {
    const normalizedTranscript = String(transcript || "").trim();
    latestTranscript = normalizedTranscript;
    setVoiceUiState({
        listening: true,
        text: "Đang chờ bạn nói xong...",
        transcript: normalizedTranscript ? `“${normalizedTranscript}”` : "Hãy tiếp tục nói để hoàn thành câu lệnh.",
    });
    setChatStatus("Đang chờ bạn nói xong...", "processing");
}

async function flushVoiceTranscript(options = {}) {
    const normalizedTranscript = String(options.transcript ?? latestTranscript ?? "").trim();
    const shouldStopRecognition = options.stopRecognition !== false;
    const isManualStop = options.isManualStop === true;

    clearVoiceSendTimer();

    if (!normalizedTranscript) {
        resetVoiceState();
        setVoiceUiState({
            listening: false,
            text: "Chạm để bắt đầu nói",
            transcript: "Không nhận được câu hoàn chỉnh, hãy thử nói lại.",
        });
        setChatStatus("Sẵn sàng nhận lệnh bằng giọng nói", "live");
        return;
    }

    if (!hasMeaningfulVoiceTranscript(normalizedTranscript)) {
        resetVoiceState();
        setVoiceUiState({
            listening: false,
            text: isManualStop ? "Câu nói quá ngắn" : "Thử lại bằng giọng nói",
            transcript: "Câu lệnh quá ngắn, vui lòng nói rõ hơn để hệ thống xử lý.",
        });
        setChatStatus("Câu lệnh quá ngắn, chưa gửi lên Jetson", "error");
        return;
    }

    if (isSendingVoice || isSendingChat || hasRecentMessage(pendingUserTexts, normalizedTranscript)) {
        resetVoiceState({ keepTranscript: true });
        setVoiceUiState({
            listening: false,
            text: "Đã nhận giọng nói",
            transcript: `“${normalizedTranscript}” đã được gửi trước đó.`,
        });
        setChatStatus("Sẵn sàng nhận lệnh bằng giọng nói", "live");
        return;
    }

    const requestId = currentVoiceSessionId || createMessageId("voice");
    isSendingVoice = true;
    currentVoiceSessionId = requestId;

    if (shouldStopRecognition && recognition) {
        try {
            recognition.stop();
        } catch (stopError) {
            console.warn("[voice-chat] recognition.stop() failed", stopError);
        }
    }

    setVoiceUiState({
        listening: false,
        text: "Đang gửi...",
        transcript: `“${normalizedTranscript}”`,
    });
    setChatStatus("Đang gửi lệnh lên Jetson...", "processing");

    addChatMessage("user", normalizedTranscript, Date.now(), {
        requestId,
        messageId: `${requestId}-user`,
    });

    console.log("[voice-chat] flushVoiceTranscript()", {
        requestId,
        transcript: normalizedTranscript,
        ts: new Date().toISOString(),
    });

    try {
        await sendChatText(normalizedTranscript, { requestId, skipUserBubble: true });
    } finally {
        resetVoiceState();
    }
}

function scheduleVoiceSend(transcript) {
    const normalizedTranscript = String(transcript || "").trim();
    if (!normalizedTranscript) {
        return;
    }

    latestTranscript = normalizedTranscript;
    clearVoiceSendTimer();
    voiceSendTimer = window.setTimeout(() => {
        flushVoiceTranscript({ transcript: latestTranscript, stopRecognition: true }).catch((error) => {
            console.error("[voice-chat] flushVoiceTranscript() failed", error);
        });
    }, VOICE_SEND_DEBOUNCE_MS);
}

function scrollChatToBottom() {
    window.requestAnimationFrame(() => {
        chatMessagesEl.scrollTo({
            top: chatMessagesEl.scrollHeight,
            behavior: "smooth",
        });
    });
}

function ensureChatEmptyStateRemoved() {
    const emptyEl = chatMessagesEl.querySelector(".chat-empty");
    if (emptyEl) {
        emptyEl.remove();
    }
}

function showChatEmptyState() {
    if (chatMessagesEl.children.length > 0) {
        return;
    }

    chatMessagesEl.innerHTML = `
        <div class="chat-empty">
            <div>
                <h3>Smart Home AI</h3>
                <p class="section-desc">Chạm nút micro để nói lệnh. Khi nhận diện xong, hệ thống sẽ tự gửi về Jetson và hiển thị phản hồi.</p>
            </div>
        </div>
    `;
}

function ensureWelcomeMessage() {
    if (hasShownWelcomeMessage) {
        return;
    }

    hasShownWelcomeMessage = addChatMessage("assistant", "Welcome SmartHome", Date.now(), {
        fingerprint: "welcome-message",
    }) || hasShownWelcomeMessage;
}

function shouldRenderChatMessage(message, source = "", level = "") {
    const normalizedMessage = normalizeMessageText(message);
    const normalizedSource = normalizeMessageText(source);
    const normalizedLevel = normalizeMessageText(level);

    if (!normalizedMessage) {
        return false;
    }

    if (BLOCKED_EVENT_SOURCES.has(normalizedSource)) {
        return false;
    }

    if (BLOCKED_MESSAGE_KEYWORDS.some((keyword) => normalizedMessage.includes(keyword))) {
        return false;
    }

    if (normalizedLevel && ["debug", "info", "trace", "verbose"].includes(normalizedLevel)) {
        return false;
    }

    if (USER_VISIBLE_EVENT_SOURCES.has(normalizedSource)) {
        return true;
    }

    if (["error", "warn", "warning"].includes(normalizedLevel)) {
        return ALLOWED_ERROR_KEYWORDS.some((keyword) => normalizedMessage.includes(keyword));
    }

    return false;
}

function addChatMessage(role, text, ts = Date.now(), options = {}) {
    const safeRole = CHAT_ROLE_META[role] ? role : "system";
    const normalizedText = String(text || "").trim();
    if (!normalizedText) {
        return false;
    }

    const dedupeKey = buildDedupeKey(
        safeRole,
        normalizedText,
        options.messageId || options.requestId || options.fingerprint || "local"
    );

    if (renderedMessageKeys.has(dedupeKey)) {
        return false;
    }

    renderedMessageKeys.add(dedupeKey);
    ensureChatEmptyStateRemoved();

    const meta = CHAT_ROLE_META[safeRole];
    const rowEl = document.createElement("div");
    rowEl.className = `chat-row role-${safeRole}${options.isError ? " is-error" : ""}`;
    rowEl.innerHTML = `
        ${safeRole === "user" ? "" : `<div class="chat-avatar">${meta.avatar}</div>`}
        <div class="chat-bubble-wrap">
            <div class="chat-bubble">${escapeHtml(normalizedText)}</div>
            <div class="chat-meta">
                <span>${escapeHtml(meta.label)}</span>
                <span>•</span>
                <time>${escapeHtml(formatTime(ts))}</time>
            </div>
        </div>
        ${safeRole === "user" ? `<div class="chat-avatar">${meta.avatar}</div>` : ""}
    `;

    chatMessagesEl.appendChild(rowEl);
    scrollChatToBottom();
    return true;
}

function updateDeviceState(deviceId, state, processing = false) {
    const stateEl = document.querySelector(`[data-device-state="${deviceId}"]`);
    const cardEl = document.querySelector(`[data-device-id="${deviceId}"]`);
    const bannerEl = document.querySelector(`[data-device-status-banner="${deviceId}"]`);

    if (!stateEl) {
        return;
    }

    const current = deviceStateMap.get(deviceId) || {};
    const nextDevice = typeof state === "object" ? state : { ...current, state };
    stateEl.textContent = formatCommandStatus(nextDevice);
    stateEl.classList.toggle("is-processing", processing);

    const effectiveState = getEffectiveDeviceState(nextDevice);

    if (cardEl) {
        cardEl.classList.toggle("is-on", effectiveState === "on");
    }

    if (bannerEl) {
        bannerEl.className = getStatusBannerClass(effectiveState, processing);
    }

    updateDeviceActionButtons(deviceId, nextDevice, processing);
}

function mergeDeviceState(deviceId, state) {
    const current = deviceStateMap.get(deviceId) || {};
    const nextState = typeof state === "object" ? { ...current, ...state } : { ...current, state };
    deviceStateMap.set(deviceId, nextState);
    updateDeviceState(deviceId, nextState, false);
}

function applyOptimisticDeviceState(deviceId, action) {
    const current = deviceStateMap.get(deviceId) || {};
    const optimisticState = {
        ...current,
        state: action,
        state_verified: false,
        last_command: action,
        last_command_status: "sent",
        last_command_at: new Date().toISOString(),
        last_command_message: `Da gui lenh ${action}`,
    };
    deviceStateMap.set(deviceId, optimisticState);
    updateDeviceState(deviceId, optimisticState, true);
}

function updateDeviceActionButtons(deviceId, device, processing = false) {
    const cardEl = document.querySelector(`[data-device-id="${deviceId}"]`);
    if (!cardEl) {
        return;
    }

    const buttons = Array.from(cardEl.querySelectorAll("[data-device-action]"));
    const currentState = getEffectiveDeviceState(device);

    buttons.forEach((button) => {
        const action = button.dataset.deviceAction;
        const isTogglePair = ["on", "off", "power.on", "power.off"].includes(action);
        const isAllowedNextAction = currentState === "on"
            ? ["off", "power.off"].includes(action)
            : currentState === "off"
                ? ["on", "power.on"].includes(action)
                : true;

        button.classList.toggle("is-active", isTogglePair && isAllowedNextAction);
        button.classList.toggle("is-inactive", isTogglePair && !isAllowedNextAction);
        button.setAttribute("aria-pressed", isTogglePair && isAllowedNextAction ? "true" : "false");

        if (processing) {
            button.disabled = true;
            return;
        }

        button.disabled = isTogglePair ? !isAllowedNextAction : false;
    });
}

function buildDeviceCard(device) {
    const visibleActions = (device.actions || []).filter((action) => ["on", "off", "power.on", "power.off"].includes(action));
    const actionsHtml = visibleActions
        .map((action) => {
            const label = device.action_labels?.[action] || formatActionLabel(action);
            return `
                <button
                    type="button"
                    class="action-btn ${getActionButtonClass(action)}"
                    data-device-action="${escapeHtml(action)}"
                >
                    ${escapeHtml(label)}
                </button>
            `;
        })
        .join("");
    const actionsSectionHtml = actionsHtml
        ? `<div class="actions">${actionsHtml}</div>`
        : '<div class="empty-device-actions">Chưa có lệnh nào. Hãy vào Cài đặt và chọn Học lệnh để thêm action.</div>';

    const currentState = getEffectiveDeviceState(device);
    const displayState = formatCommandStatus(device);

    return `
        <article class="device-card ${currentState === "on" ? "is-on" : ""}" data-device-id="${escapeHtml(device.id)}">
            <div class="device-card-top">
                <div class="device-title-group">
                    <div class="device-icon">${getDeviceIcon(device)}</div>
                    <div>
                        <h3>${escapeHtml(device.name)}</h3>
                        <p class="device-meta">${escapeHtml(device.type_label || device.type || "unknown")}</p>
                    </div>
                </div>
                <span class="device-id">${escapeHtml(device.id)}</span>
            </div>
            <div class="${getStatusBannerClass(currentState, false)}" data-device-status-banner="${escapeHtml(device.id)}">
                <div>
                    <span class="info-label">Trạng thái hiện tại</span>
                    <div class="device-status-text">
                        <span class="device-status-dot"></span>
                        <strong class="device-state" data-device-state="${escapeHtml(device.id)}">${escapeHtml(displayState)}</strong>
                    </div>
                </div>
            </div>
            <div class="device-info-grid">
                <div class="info-item">
                    <span class="info-label">Loại</span>
                    <strong>${escapeHtml(device.device_kind || device.type || "unknown")}</strong>
                </div>
                <div class="info-item">
                    <span class="info-label">Hãng / Giao tiếp</span>
                    <strong>${escapeHtml(`${device.brand || "unknown"} / ${device.control_type || "unknown"}`)}</strong>
                </div>
            </div>
            ${actionsSectionHtml}
        </article>
    `;
}

function bindDeviceActions() {
    document.querySelectorAll("[data-device-id] [data-device-action]").forEach((button) => {
        button.addEventListener("click", () => {
            const card = button.closest("[data-device-id]");
            if (!card) {
                return;
            }

            if (button.disabled) {
                return;
            }

            sendDeviceCommand(card.dataset.deviceId, button.dataset.deviceAction, button);
        });
    });
}

function renderDevices(devices) {
    if (!devices.length) {
        deviceListEl.innerHTML = '<p class="empty-state">Chưa có thiết bị nào trong hệ thống.</p>';
        setSummaryText("0 thiết bị");
        return;
    }

    deviceStateMap.clear();
    devices.forEach((device) => deviceStateMap.set(device.id, device));
    deviceListEl.innerHTML = devices.map((device) => buildDeviceCard(device)).join("");
    setSummaryText(`${devices.length} thiết bị khả dụng`);
    bindDeviceActions();
    devices.forEach((device) => updateDeviceActionButtons(device.id, device, false));
}

async function loadDevices() {
    deviceListEl.innerHTML = '<p class="empty-state">Đang tải thiết bị...</p>';
    setSummaryText("Đang đồng bộ...");

    try {
        const { result } = await fetchJson("/api/devices");
        deviceInventory = Array.isArray(result.devices) ? result.devices : [];
        renderIrDeviceOptions();
        renderDevices(deviceInventory);
    } catch (error) {
        if (error.isAuth) {
            return;
        }

        deviceInventory = [];
        renderIrDeviceOptions();
        deviceListEl.innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
        setSummaryText("Tải dữ liệu thất bại");
        addChatMessage("system", `Không tải được danh sách thiết bị: ${error.message}`, Date.now(), {
            isError: true,
            fingerprint: "load-devices-error",
        });
    }
}

async function submitAddDevice(event) {
    event.preventDefault();

    if (!isAuthenticated || isAddDeviceSubmitting || !addDeviceFormEl?.reportValidity()) {
        return;
    }

    const templateId = String(addDeviceTemplateSelectEl?.value || "").trim();
    const deviceName = String(addDeviceNameInputEl?.value || "").trim();

    if (!templateId) {
        setAddDeviceFeedback("Vui lòng chọn loại thiết bị.");
        addDeviceTemplateSelectEl?.focus();
        return;
    }

    if (!deviceName) {
        setAddDeviceFeedback("Vui lòng nhập tên thiết bị.");
        addDeviceNameInputEl?.focus();
        return;
    }

    setAddDeviceFeedback("");
    setAddDeviceLoadingState(true);

    try {
        const { result } = await fetchJson("/api/devices", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                template_id: templateId,
                device: {
                    name: deviceName,
                    aliases: [deviceName],
                },
            }),
        });

        const successText = result.message || "Thêm thiết bị thành công";
        setAddDeviceFeedback(successText, "success");
        await loadDevices();
        addChatMessage("assistant", `${successText}: ${deviceName}`, Date.now(), {
            fingerprint: `device-add-${result.device_id || Date.now()}`,
        });
        window.setTimeout(() => {
            closeAddDeviceModal();
        }, 500);
    } catch (error) {
        if (error.isAuth) {
            return;
        }

        setAddDeviceFeedback(error.message || "Thêm thiết bị thất bại.");
    } finally {
        setAddDeviceLoadingState(false);
    }
}

async function sendDeviceCommand(deviceId, action, buttonEl) {
    if (!isAuthenticated) {
        lockControlUi("Vui lòng đăng nhập trước khi điều khiển thiết bị.");
        return;
    }

    const actionButtons = buttonEl.parentElement?.querySelectorAll("button") || [];
    const previousState = { ...(deviceStateMap.get(deviceId) || {}) };

    actionButtons.forEach((button) => {
        button.disabled = true;
        button.classList.add("is-loading");
    });

    applyOptimisticDeviceState(deviceId, action);
    setChatStatus("Jetson đang xử lý thiết bị...", "processing");

    try {
        const { result } = await fetchJson("/api/device/control", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ device_id: deviceId, action }),
        });

        const replyText = result.reply_text || `Đã ${formatActionLabel(action).toLowerCase()} thiết bị ${deviceId}.`;
        addChatMessage("assistant", replyText, Date.now(), {
            fingerprint: `device-control-${deviceId}-${action}`,
        });

        if (result.intent?.device) {
            mergeDeviceState(result.intent.device, {
                state: result.state || "unknown",
                state_verified: result.state_verified,
                last_command: result.last_command,
                last_command_at: result.last_command_at,
                last_command_status: result.last_command_status,
                last_command_message: result.last_command_message,
            });
        }

        setChatStatus("Sẵn sàng nhận lệnh bằng giọng nói", "live");
    } catch (error) {
        if (error.isAuth) {
            deviceStateMap.set(deviceId, previousState);
            updateDeviceState(deviceId, previousState, false);
            return;
        }

        deviceStateMap.set(deviceId, previousState);
        updateDeviceState(deviceId, previousState, false);
        addChatMessage("system", `Không thể điều khiển thiết bị: ${error.message}`, Date.now(), {
            isError: true,
            fingerprint: `device-control-error-${deviceId}-${action}`,
        });
        setChatStatus("Có lỗi khi điều khiển thiết bị", "error");
    } finally {
        actionButtons.forEach((button) => {
            button.classList.remove("is-loading");
        });
        updateDeviceActionButtons(deviceId, deviceStateMap.get(deviceId) || previousState, false);
    }
}

function openIrLearnForm() {
    if (isLearningIr) {
        return;
    }

    openIrLearnModal();
}

function closeIrLearnForm() {
    closeIrLearnModal();
}

function inferActionKeyFromFilename(filename) {
    const safeFilename = normalizeIrFilenameInput(filename).replace(/\.bin$/i, "");
    const parts = safeFilename.split("_").filter(Boolean);
    const actionToken = parts[parts.length - 1] || "";

    if (!actionToken) {
        return "power.on";
    }

    if (actionToken === "on") {
        return "power.on";
    }

    if (actionToken === "off") {
        return "power.off";
    }

    return actionToken.replaceAll("_", ".");
}

async function learnIrCommand(event) {
    event?.preventDefault();

    if (!isAuthenticated) {
        lockControlUi("Vui lòng đăng nhập trước khi lưu thiết bị.");
        return;
    }

    if (isLearningIr) {
        return;
    }

    const deviceId = String(irDeviceSelectEl?.value || "").trim();
    const selectedDevice = getDeviceById(deviceId);
    const templateId = String(selectedDevice?.template_id || "").trim();
    const deviceName = String(selectedDevice?.name || irDeviceNameInputEl?.value || "").trim();
    const filename = normalizeIrFilenameInput(irFilenameInputEl?.value || "");
    const semanticKind = String(irSemanticKindSelectEl?.value || "power.on").trim();
    const semanticValue = String(irSemanticValueInputEl?.value || "").trim();
    const actionPhrases = parseMultilinePhrases(irActionPhrasesInputEl?.value || "");

    if (!deviceId || !selectedDevice) {
        setIrLearnModalFeedback("Vui lòng chọn thiết bị đã thêm trước khi học lệnh.");
        irDeviceSelectEl?.focus();
        return;
    }

    if (!deviceName) {
        setIrLearnModalFeedback("Vui lòng nhập tên thiết bị.");
        irDeviceNameInputEl?.focus();
        return;
    }

    if (!filename) {
        setIrLearnModalFeedback("Vui lòng nhập tên file .bin.");
        irFilenameInputEl?.focus();
        return;
    }

    if (!isValidIrFilename(filename)) {
        setIrLearnModalFeedback("Tên file .bin chưa đúng định dạng. Ví dụ: den_san_on.bin");
        irFilenameInputEl?.focus();
        return;
    }

    let actionPayload;
    try {
        actionPayload = buildSemanticActionPayload(semanticKind, semanticValue);
    } catch (error) {
        setIrLearnModalFeedback(error.message || "Thông tin ngữ nghĩa lệnh chưa hợp lệ.");
        irSemanticValueInputEl?.focus();
        return;
    }

    const phrasesPayload = actionPhrases.length
        ? actionPhrases
        : buildDefaultActionPhrases(deviceName, semanticKind, semanticValue);

    setIrLearnModalFeedback("");
    setIrLearnLoadingState(true);
    setChatStatus("Broadlink đang học file IR...", "processing");

    try {
        await fetchJson("/api/ir/learn", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                filename,
                device_name: deviceName,
                signal_type: "ir",
            }),
        });

        const { result } = await fetchJson("/api/device-learn/save", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                template_id: templateId,
                device: {
                    id: selectedDevice.id,
                    name: deviceName,
                    aliases: Array.isArray(selectedDevice.aliases) ? selectedDevice.aliases : [deviceName],
                },
                actions: {
                    [actionPayload.actionKey]: {
                        type: "ir",
                        file: filename,
                        semantic: actionPayload.semantic,
                        phrases: phrasesPayload,
                    },
                },
                presets: {},
            }),
        });

        const successText = result.message || "Học lệnh và lưu thiết bị thành công";
        setIrLearnModalFeedback(successText, "success");
        setChatStatus("Học lệnh thành công", "live");
        await loadDevices();
        addChatMessage("assistant", successText, Date.now(), {
            fingerprint: `device-learn-save-${result.device_id || Date.now()}`,
        });
        window.setTimeout(() => closeIrLearnModal({ force: true }), 500);
    } catch (error) {
        if (error.isAuth) {
            return;
        }

        const message = error.message || "Học lệnh thất bại";
        setIrLearnModalFeedback(message);
        setChatStatus("Có lỗi khi học lệnh", "error");
        addChatMessage("system", message, Date.now(), {
            isError: true,
            fingerprint: `device-learn-save-error-${Date.now()}`,
        });
    } finally {
        setIrLearnLoadingState(false);
    }
}

function renderEventAsChat(event) {
    if (!event || renderedEventIds.has(event.id)) {
        return;
    }

    renderedEventIds.add(event.id);

    const message = event?.message || event?.payload?.reply_text || "";
    const source = event?.source || event?.payload?.source || "";
    const level = event?.level || event?.payload?.level || "";

    if (!shouldRenderChatMessage(message, source, level)) {
        return;
    }

    addChatMessage("system", message, event.ts || Date.now(), {
        fingerprint: `event-${event.id}`,
    });
}

async function sendChatText(text, options = {}) {
    const normalizedText = String(text || "").trim();
    if (!normalizedText || isSendingChat) {
        return;
    }

    if (!isAuthenticated) {
        lockControlUi("Vui lòng đăng nhập trước khi gửi lệnh tới Jetson.");
        return;
    }

    const requestId = options.requestId || createMessageId("voice-request");
    activeChatRequestId = requestId;
    isSendingChat = true;

    rememberRecentMessage(pendingUserTexts, normalizedText);

    if (!options.skipUserBubble) {
        addChatMessage("user", normalizedText, Date.now(), {
            requestId,
            messageId: `${requestId}-user`,
        });
    }

    console.log("[voice-chat] sendChatText() called", {
        requestId,
        text: normalizedText,
        ts: new Date().toISOString(),
    });
    setChatStatus("Đang gửi lệnh lên Jetson...", "processing");
    setVoiceUiState({
        listening: false,
        text: "Đã nhận câu lệnh",
        transcript: `“${normalizedText}” đang được xử lý...`,
    });
    micBtnEl.disabled = true;

    try {
        const { result } = await fetchJson("/api/chat/send", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: normalizedText, request_id: requestId }),
        });

        if (result.reply_text) {
            rememberRecentMessage(pendingAssistantTexts, result.reply_text);
            addChatMessage("assistant", result.reply_text, Date.now(), {
                requestId,
                messageId: `${requestId}-assistant`,
            });
        }

        if (result.intent?.device && result.intent?.action) {
            mergeDeviceState(result.intent.device, {
                state: result.state || result.intent.action || "unknown",
                state_verified: result.state_verified,
                last_command: result.last_command || result.intent.action,
                last_command_at: result.last_command_at,
                last_command_status: result.last_command_status,
                last_command_message: result.last_command_message,
            });
        }

        setChatStatus("Sẵn sàng nhận lệnh bằng giọng nói", "live");
        setVoiceUiState({
            listening: false,
            text: "Chạm để bắt đầu nói",
            transcript: `Đã gửi: “${normalizedText}”`,
        });
    } catch (error) {
        if (error.isAuth) {
            return;
        }

        addChatMessage("system", error.message || "Có lỗi xảy ra khi gửi lệnh lên Jetson", Date.now(), {
            isError: true,
            requestId,
            messageId: `${requestId}-error`,
        });
        setChatStatus("Có lỗi khi xử lý yêu cầu", "error");
        setVoiceUiState({
            listening: false,
            text: "Thử lại bằng giọng nói",
            transcript: "Jetson chưa phản hồi đúng, hãy nói lại một lần nữa.",
        });
    } finally {
        isSendingChat = false;
        activeChatRequestId = null;
        micBtnEl.disabled = false;
    }
}

function stopVoiceRecognition() {
    if (!recognition || !isListening) {
        return;
    }

    const transcriptToFlush = latestTranscript;
    clearVoiceSendTimer();

    if (hasMeaningfulVoiceTranscript(transcriptToFlush)) {
        flushVoiceTranscript({ transcript: transcriptToFlush, stopRecognition: true, isManualStop: true }).catch((error) => {
            console.error("[voice-chat] manual flush failed", error);
        });
        return;
    }

    resetVoiceState();

    try {
        recognition.stop();
    } catch (stopError) {
        console.warn("[voice-chat] recognition.stop() failed", stopError);
    }

    setVoiceUiState({
        listening: false,
        text: transcriptToFlush ? "Câu nói quá ngắn" : "Đã dừng ghi âm",
        transcript: transcriptToFlush
            ? "Câu lệnh quá ngắn, chưa gửi lên Jetson. Hãy nói dài hơn một chút."
            : "Bạn có thể chạm lại để nói một lệnh mới.",
    });
    setChatStatus(transcriptToFlush ? "Câu lệnh quá ngắn, chưa gửi" : "Đã dừng ghi âm", transcriptToFlush ? "error" : "live");
}

function startVoiceRecognition() {
    if (!SpeechRecognitionApi) {
        addChatMessage("system", "Trình duyệt này chưa hỗ trợ nhận diện giọng nói. Hãy dùng Chrome hoặc Edge mới để dùng micro.", Date.now(), {
            isError: true,
            fingerprint: "speech-not-supported",
        });
        setChatStatus("Thiết bị không hỗ trợ SpeechRecognition", "error");
        setVoiceUiState({
            listening: false,
            text: "Trình duyệt chưa hỗ trợ micro",
            transcript: "Hãy mở bằng Chrome hoặc Edge để dùng điều khiển giọng nói.",
        });
        return;
    }

    if (isSendingChat) {
        return;
    }

    if (!recognition) {
        recognition = new SpeechRecognitionApi();
        recognition.lang = "vi-VN";
        recognition.interimResults = true;
        recognition.maxAlternatives = 1;
        recognition.continuous = false;

        recognition.onstart = () => {
            resetVoiceState();
            setVoiceUiState({
                listening: true,
                text: "Đang nghe...",
                transcript: "Hãy nói lệnh của bạn. Hệ thống sẽ đợi bạn nói xong rồi mới gửi.",
            });
            setChatStatus("Đang nghe giọng nói của bạn...", "processing");
        };

        recognition.onresult = (event) => {
            const transcript = Array.from(event.results || [])
                .map((result) => result?.[0]?.transcript || "")
                .join(" ")
                .trim();

            console.log("[voice-chat] recognition.onresult", {
                transcript,
                resultIndex: event.resultIndex,
                resultsLength: event.results?.length || 0,
                ts: new Date().toISOString(),
            });

            if (!transcript) {
                return;
            }

            updatePendingVoiceTranscript(transcript);
            scheduleVoiceSend(transcript);

            console.log("[voice-chat] scheduleVoiceSend()", {
                transcript,
                debounceMs: VOICE_SEND_DEBOUNCE_MS,
                ts: new Date().toISOString(),
            });
        };

        recognition.onerror = (event) => {
            resetVoiceState();
            const errorMap = {
                not_allowed: "Bạn chưa cấp quyền micro cho trình duyệt.",
                no_speech: "Không nghe thấy giọng nói, vui lòng thử lại.",
                audio_capture: "Không truy cập được microphone.",
                aborted: "Ghi âm đã được dừng.",
            };

            const message = errorMap[event.error] || "Không thể nhận diện giọng nói lúc này.";
            if (event.error !== "aborted") {
                setChatStatus(message, "error");
            } else {
                setChatStatus("Đã dừng ghi âm", "live");
            }

            setVoiceUiState({
                listening: false,
                text: event.error === "aborted" ? "Đã dừng ghi âm" : "Micro gặp lỗi",
                transcript: message,
            });
        };

        recognition.onend = () => {
            if (voiceSendTimer || isSendingVoice || isSendingChat) {
                return;
            }

            if (isListening && hasMeaningfulVoiceTranscript(latestTranscript)) {
                flushVoiceTranscript({ transcript: latestTranscript, stopRecognition: false }).catch((error) => {
                    console.error("[voice-chat] onend flush failed", error);
                });
                return;
            }

            if (isListening) {
                resetVoiceState();
                setVoiceUiState({
                    listening: false,
                    text: "Chạm để bắt đầu nói",
                    transcript: "Không nhận được câu hoàn chỉnh, hãy thử nói lại.",
                });
                setChatStatus("Sẵn sàng nhận lệnh bằng giọng nói", "live");
            }
        };
    }

    if (isListening) {
        stopVoiceRecognition();
        return;
    }

    currentVoiceSessionId = createMessageId("voice");
    recognition.start();
}

function handleSnapshot(payload) {
    const devices = payload?.devices || [];
    if (devices.length) {
        renderDevices(devices);
    }
}

function handleDeviceStateChanged(payload) {
    if (payload?.id) {
        mergeDeviceState(payload.id, payload);
    }
}

function setupRealtime() {
    if (!isAuthenticated || socket) {
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
        socket = io({
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

    socket.on("connect_error", () => {
        // Jetson/Werkzeug hiện tại không ổn định với websocket, giữ polling để tránh 500.
    });

    socket.on("disconnect", () => {
        if (!isAuthenticated) {
            socket = null;
        }
    });

    socket.on("devices_snapshot", handleSnapshot);
    socket.on("device_state_changed", handleDeviceStateChanged);
    socket.on("system_log", (payload) => {
        if (!payload?.message) {
            return;
        }

        const normalizedMessage = normalizeMessageText(payload.message);
        if (hasRecentMessage(pendingAssistantTexts, normalizedMessage) || hasRecentMessage(pendingUserTexts, normalizedMessage)) {
            return;
        }

        if (shouldRenderChatMessage(payload.message, payload.source || "system_log", payload.level || "info")) {
            addChatMessage("system", payload.message, payload.ts || Date.now(), {
                fingerprint: `socket-log-${normalizedMessage}`,
                isError: ["error", "warn", "warning"].includes(normalizeMessageText(payload.level || "")),
            });
        }
    });
}

function initializeApp() {
    if (appInitialized) {
        return;
    }

    appInitialized = true;
    showChatEmptyState();
    ensureWelcomeMessage();
    setupRealtime();
    pollEvents();
    pollingIntervalId = window.setInterval(pollEvents, 3000);
}

async function unlockControlUi(sessionData = {}) {
    isAuthenticated = true;
    setAuthFeedback("", "success");
    updateAuthChip(
        sessionData.jetson_id
            ? `Jetson ${sessionData.jetson_id}`
            : "Đăng nhập thành công"
    );
    setControlLockState(false);
    setChatStatus("Sẵn sàng nhận lệnh bằng giọng nói", "live");
    setVoiceUiState({
        listening: false,
        text: SpeechRecognitionApi ? "Chạm để bắt đầu nói" : "Trình duyệt chưa hỗ trợ micro",
        transcript: SpeechRecognitionApi
            ? "Không có ô nhập tay, sau khi nhận diện xong hệ thống sẽ tự gửi lên Jetson."
            : "Hãy mở bằng Chrome hoặc Edge để dùng điều khiển giọng nói.",
    });
    setIrLearnStatus("Sẵn sàng học lệnh. Hệ thống sẽ tự học và tự phân loại tín hiệu.", "idle");
    initializeApp();
    await loadIrTemplateOptions();
    await loadDevices();
    await pollEvents();
}

async function submitLogin(event) {
    event.preventDefault();

    if (isAuthSubmitting || !authFormEl.reportValidity()) {
        return;
    }

    const formData = new FormData(authFormEl);
    const email = String(formData.get("email") || "").trim();
    const password = String(formData.get("password") || "");
    const jetsonId = String(formData.get("jetson_id") || "").trim();
    const endpoint = authMode === "register" ? "/api/auth/register" : "/api/auth/login";
    const successChipText = authMode === "register"
        ? "Đang tạo tài khoản và liên kết Jetson..."
        : "Đang xác thực với MongoDB Atlas...";

    isAuthSubmitting = true;
    authSubmitBtnEl.disabled = true;
    setAuthFeedback("");
    updateAuthChip(successChipText);

    try {
        const { result } = await fetchJson(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password, jetson_id: jetsonId }),
        });

        authFormEl.reset();
        setAuthMode("login");
        await unlockControlUi(result);
    } catch (error) {
        setControlLockState(true);
        setAuthFeedback(error.message || (authMode === "register" ? "Đăng ký thất bại." : "Đăng nhập thất bại."));
        updateAuthChip(authMode === "register" ? "Nhập thông tin để tạo tài khoản" : "Đăng nhập để mở quyền điều khiển");
        (authMode === "register" ? authJetsonIdEl : authPasswordEl)?.focus();
    } finally {
        isAuthSubmitting = false;
        authSubmitBtnEl.disabled = false;
    }
}

async function submitPasswordChange(event) {
    event.preventDefault();

    if (!isAuthenticated || isPasswordSubmitting || !passwordFormEl.reportValidity()) {
        return;
    }

    const formData = new FormData(passwordFormEl);
    const currentPassword = String(formData.get("current_password") || "");
    const newPassword = String(formData.get("new_password") || "");

    isPasswordSubmitting = true;
    passwordSubmitBtnEl.disabled = true;
    setPasswordFeedback("");

    try {
        const { result } = await fetchJson("/api/auth/change-password", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                current_password: currentPassword,
                new_password: newPassword,
            }),
        });

        setPasswordFeedback(result.message || "Đổi mật khẩu thành công.", "success");
        passwordFormEl.reset();
        window.setTimeout(() => {
            closePasswordModal();
        }, 700);
    } catch (error) {
        setPasswordFeedback(error.message || "Đổi mật khẩu thất bại.");
        currentPasswordEl?.focus();
    } finally {
        isPasswordSubmitting = false;
        passwordSubmitBtnEl.disabled = false;
    }
}

async function bootstrapAuthentication() {
    setControlLockState(true);
    showChatEmptyState();
    ensureWelcomeMessage();
    setChatStatus("Vui lòng đăng nhập để sử dụng điều khiển thiết bị", "error");
    setVoiceUiState({
        listening: false,
        text: "Đăng nhập để dùng micro",
        transcript: "Toàn bộ lệnh điều khiển đang bị khóa cho tới khi đăng nhập thành công.",
    });
    setIrLearnStatus("Vui lòng đăng nhập để học lệnh và điều khiển thiết bị.", "error");
    updateAuthChip("Kiểm tra phiên đăng nhập...");

    try {
        const { result } = await fetchJson("/api/auth/status", { allowResultError: true });
        if (result.authenticated) {
            await unlockControlUi(result);
            return;
        }

        lockControlUi("Vui lòng đăng nhập để mở quyền điều khiển thiết bị.");
    } catch (error) {
        lockControlUi(error.message || "Không kiểm tra được trạng thái đăng nhập.");
    }
}

async function pollEvents() {
    if (!isAuthenticated) {
        return;
    }

    try {
        const { result } = await fetchJson(`/api/events?since_id=${lastEventId}&limit=80`);
        (result.events || []).forEach((event) => renderEventAsChat(event));
        lastEventId = Number(result.last_id || lastEventId);
    } catch (error) {
        if (error.isAuth) {
            return;
        }

        // Không hiển thị lỗi polling để tránh spam chat.
    }
}

reloadBtnEl.addEventListener("click", loadDevices);
chatFormEl.addEventListener("submit", (event) => event.preventDefault());
micBtnEl.addEventListener("click", startVoiceRecognition);
authFormEl.addEventListener("submit", submitLogin);
authLoginTabEl?.addEventListener("click", () => setAuthMode("login"));
authRegisterTabEl?.addEventListener("click", () => setAuthMode("register"));
settingsBtnEl?.addEventListener("click", toggleSettingsMenu);
addDeviceBtnEl?.addEventListener("click", openAddDeviceModal);
learnCommandBtnEl?.addEventListener("click", openIrLearnModal);
changePasswordBtnEl?.addEventListener("click", openPasswordModal);
logoutBtnEl?.addEventListener("click", handleLogout);
passwordCloseBtnEl?.addEventListener("click", closePasswordModal);
passwordBackdropEl?.addEventListener("click", closePasswordModal);
passwordFormEl?.addEventListener("submit", submitPasswordChange);
addDeviceCloseBtnEl?.addEventListener("click", closeAddDeviceModal);
addDeviceBackdropEl?.addEventListener("click", closeAddDeviceModal);
addDeviceFormEl?.addEventListener("submit", submitAddDevice);
irLearnCloseBtnEl?.addEventListener("click", closeIrLearnForm);
irLearnBackdropEl?.addEventListener("click", closeIrLearnForm);
irLearnFormEl?.addEventListener("submit", learnIrCommand);

document.addEventListener("click", (event) => {
    if (!settingsMenuEl || !settingsBtnEl) {
        return;
    }

    const target = event.target;
    if (target instanceof Node && !settingsMenuEl.contains(target) && !settingsBtnEl.contains(target)) {
        closeSettingsMenu();
    }
});

document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
        closeSettingsMenu();
        closePasswordModal();
        closeAddDeviceModal();
        closeIrLearnForm();
    }
});

window.addEventListener("resize", () => {
    if (window.innerWidth <= 640) {
        settingsMenuEl?.style.removeProperty("width");
        settingsMenuEl?.style.removeProperty("--settings-menu-left");
        settingsMenuEl?.style.removeProperty("--settings-menu-top");
    }

    if (settingsMenuEl?.classList.contains("is-open")) {
        positionSettingsMenu();
    }
});

window.addEventListener("scroll", () => {
    if (settingsMenuEl?.classList.contains("is-open")) {
        positionSettingsMenu();
    }
}, { passive: true });

if (irCancelBtnEl) {
    irCancelBtnEl.addEventListener("click", closeIrLearnForm);
}

if (addDeviceCancelBtnEl) {
    addDeviceCancelBtnEl.addEventListener("click", closeAddDeviceModal);
}

if (irDeviceSelectEl) {
    irDeviceSelectEl.addEventListener("change", () => {
        syncIrDeviceSelection(irDeviceSelectEl.value);
    });
}

if (irSemanticKindSelectEl) {
    irSemanticKindSelectEl.addEventListener("change", updateIrSemanticForm);
}

setAuthMode("login");
updateIrSemanticForm();
bootstrapAuthentication();
